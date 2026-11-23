"""Answer-sheet OCR (phase 7, FR-3.7 to FR-3.9): read a scanned PDF, then save what the teacher confirms.

POST /api/assessments/{id}/ocr        read the PDF; returns suggestions only, saves nothing
PUT  /api/assessments/{id}/questions  save the confirmed questions, max marks, COs and Bloom levels

Confirmed marks are sent as a CSV to the existing POST /api/assessments/{id}/marks, so they pass
the same validation, triggers and audit as a hand-made CSV. The PDF and the page images are not
stored on the server.
"""

from decimal import ROUND_DOWN, Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from api import db
from api.auth import database, require
from api.db import User
from api.ocr import layout, reader

router = APIRouter(prefix="/api")
editors = require("admin", "faculty")
MAX_BYTES = 40 * 1024 * 1024


def _assessment(conn, assessment_id: int) -> dict:
    row = conn.execute("""
        SELECT a.assessment_id, a.name, a.type, a.max_marks, a.locked, a.offering_id, o.course_id
        FROM assessment a JOIN course_offering o USING (offering_id)
        WHERE a.assessment_id = %s AND fn_can_view_offering(a.offering_id)""", (assessment_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Assessment not found")
    return row


def _existing_questions(conn, assessment_id: int) -> list[dict]:
    return conn.execute("""
        SELECT q.q_no, q.max_marks::int AS max_marks, q.bloom_level AS bloom,
               coalesce(array_agg(co.co_number ORDER BY co.co_number)
                        FILTER (WHERE co.co_number IS NOT NULL), '{}') AS cos
        FROM assessment_question q
        LEFT JOIN question_co_map m USING (question_id)
        LEFT JOIN course_outcome co USING (co_id)
        WHERE q.assessment_id = %s GROUP BY q.question_id ORDER BY q.question_id""", (assessment_id,)).fetchall()


def _marks_entered(conn, assessment_id: int) -> int:
    return conn.execute("""
        SELECT count(*) AS n FROM student_question_mark m JOIN assessment_question q USING (question_id)
        WHERE q.assessment_id = %s""", (assessment_id,)).fetchone()["n"]


@router.post("/assessments/{assessment_id}/ocr")
def read_answer_sheets(assessment_id: int, file: UploadFile = File(...),
                       user: User = Depends(editors), dbname=Depends(database)):
    # A plain def: OCR takes seconds, so it runs in the threadpool and does not stall other requests.
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"The PDF is larger than {MAX_BYTES // (1024 * 1024)} MB")
    with db.session(user, dbname) as conn:
        a = _assessment(conn, assessment_id)
        if a["locked"]:
            raise HTTPException(409, "Assessment is locked; request an unlock before reading new sheets")
        cos = {r["co_number"] for r in conn.execute(
            "SELECT co_number FROM course_outcome WHERE course_id = %s", (a["course_id"],))}
        existing = _existing_questions(conn, assessment_id)
        marks_entered = _marks_entered(conn, assessment_id)
        enrolled = [r["usn"] for r in conn.execute(
            "SELECT usn FROM enrollment WHERE offering_id = %s ORDER BY usn", (a["offering_id"],))]
        with_marks = {r["usn"] for r in conn.execute("""
            SELECT DISTINCT e.usn FROM student_question_mark m JOIN enrollment e USING (enrollment_id)
            JOIN assessment_question q USING (question_id) WHERE q.assessment_id = %s""", (assessment_id,))}
        rule = conn.execute("""
            SELECT ac.ocr_review_confidence FROM v_offering_config oc JOIN attainment_config ac USING (config_id)
            WHERE oc.offering_id = %s""", (a["offering_id"],)).fetchone()
        threshold = float(rule["ocr_review_confidence"]) if rule else reader.DEFAULT_REVIEW_CONFIDENCE
    # The database work is done; OCR runs outside the transaction.
    try:
        raw = reader.read_pdf(data, fallback=[{**q, "cos": list(q["cos"]), "text": ""} for q in existing])
    except reader.OcrError as exc:
        raise HTTPException(422, str(exc)) from exc

    paper = raw["paper"]
    warnings = list(paper["warnings"])
    questions = paper["questions"]
    beyond = [q["q_no"] for q in questions if reader.cover_row(q) is None]
    if beyond:
        warnings.append(f"The cover page has rows for Q1-Q{layout.MAX_QUESTIONS} only, so {', '.join(beyond)} "
                        "cannot be read or saved here; enter those marks by CSV")
        questions = [q for q in questions if reader.cover_row(q) is not None]
    for q in questions:
        q["problems"] = [f"CO{c} is not a CO of this course" for c in q["cos"] if c not in cos]
        if not 0 < q["max_marks"] <= 99:
            q["problems"].append("Max marks must be 1 to 99 to fit the two mark boxes")
    total_max = sum(q["max_marks"] for q in questions)
    if total_max != a["max_marks"]:
        warnings.append(f"The questions add up to {total_max} marks; the assessment is out of {a['max_marks']:g}")
    if paper["paper_max"] is not None and paper["paper_max"] != a["max_marks"]:
        warnings.append(f"Page 1 says max. marks {paper['paper_max']}; the assessment is out of {a['max_marks']:g}")

    def norm(qs):
        return [(q["q_no"], int(q["max_marks"]), sorted(q["cos"]), q["bloom"]) for q in qs]

    review = reader.review(raw, questions, enrolled, threshold)
    return {
        "assessment": {"assessment_id": a["assessment_id"], "name": a["name"], "max_marks": a["max_marks"]},
        "paper": {"questions": questions, "warnings": warnings, "paper_max": paper["paper_max"],
                  "same_as_saved": norm(questions) == norm(existing),
                  "saved": existing, "marks_entered": marks_entered},
        "sheets": review["sheets"],
        "absent": review["absent"],
        # Students with no sheet in this PDF who already have marks: saved as AB only if the teacher says so.
        "absent_with_marks": sorted(set(review["absent"]) & with_marks),
        "threshold": threshold,
    }


class QuestionIn(BaseModel):
    q_no: str = Field(pattern=r"^Q\d{1,2}$")
    max_marks: int = Field(ge=1, le=99)
    cos: list[int] = Field(min_length=1, max_length=6)
    bloom: int | None = Field(default=None, ge=1, le=6)

    @field_validator("cos")
    @classmethod
    def distinct(cls, v: list[int]) -> list[int]:
        if len(set(v)) != len(v):
            raise ValueError("a CO is listed twice")
        return v


class QuestionsIn(BaseModel):
    questions: list[QuestionIn] = Field(min_length=1, max_length=layout.MAX_QUESTIONS)


def _weights(n: int) -> list[Decimal]:
    """Equal CO weights that add up to exactly 1 at three decimals (0.333, 0.333, 0.334)."""
    base = (Decimal(1) / n).quantize(Decimal("0.001"), rounding=ROUND_DOWN)
    return [base] * (n - 1) + [Decimal(1) - base * (n - 1)]


@router.put("/assessments/{assessment_id}/questions")
def save_questions(assessment_id: int, body: QuestionsIn, user: User = Depends(editors), dbname=Depends(database)):
    """Replace the questions of an assessment with no marks yet; once marks exist, only CO tags and
    Bloom levels may change (the question numbers and maxima must stay as they are)."""
    qs = body.questions
    if len({q.q_no for q in qs}) != len(qs):
        raise HTTPException(422, "A question number appears more than once")
    with db.session(user, dbname) as conn:
        a = _assessment(conn, assessment_id)
        if a["locked"]:
            raise HTTPException(409, "Assessment is locked; questions and CO tags cannot be changed")
        co_ids = {r["co_number"]: r["co_id"] for r in conn.execute(
            "SELECT co_number, co_id FROM course_outcome WHERE course_id = %s", (a["course_id"],))}
        unknown = sorted({c for q in qs for c in q.cos} - set(co_ids))
        if unknown:
            raise HTTPException(422, "Not COs of this course: " + ", ".join(f"CO{c}" for c in unknown))
        saved = {r["q_no"]: r for r in conn.execute(
            "SELECT question_id, q_no, max_marks FROM assessment_question WHERE assessment_id = %s",
            (assessment_id,))}
        if _marks_entered(conn, assessment_id):
            if {q.q_no: q.max_marks for q in qs} != {k: int(v["max_marks"]) for k, v in saved.items()}:
                raise HTTPException(409, "Marks are already entered, so only CO tags and Bloom levels can change; "
                                         "the question numbers and maximum marks must match the saved ones")
            ids = {q.q_no: saved[q.q_no]["question_id"] for q in qs}
            conn.execute("DELETE FROM question_co_map WHERE question_id = ANY(%s)", (list(ids.values()),))
            for q in qs:
                conn.execute("UPDATE assessment_question SET bloom_level = %s WHERE question_id = %s",
                             (q.bloom, ids[q.q_no]))
        else:
            if saved:
                old = [v["question_id"] for v in saved.values()]
                conn.execute("DELETE FROM question_co_map WHERE question_id = ANY(%s)", (old,))
                conn.execute("DELETE FROM assessment_question WHERE question_id = ANY(%s)", (old,))
            ids = {}
            for q in qs:
                ids[q.q_no] = conn.execute(
                    "INSERT INTO assessment_question (assessment_id, q_no, max_marks, bloom_level) "
                    "VALUES (%s, %s, %s, %s) RETURNING question_id",
                    (assessment_id, q.q_no, q.max_marks, q.bloom)).fetchone()["question_id"]
        for q in qs:
            for co, w in zip(q.cos, _weights(len(q.cos))):
                conn.execute("INSERT INTO question_co_map (question_id, co_id, weight) VALUES (%s, %s, %s)",
                             (ids[q.q_no], co_ids[co], w))
    return {"saved": len(qs)}
