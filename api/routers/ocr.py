"""Answer-sheet OCR (phase 7, FR-3.7 to FR-3.9): scan one sitting, then save what the teacher confirms.

POST /api/offerings/{id}/scan?sitting=CIE1|CIE2|SEE   read the PDF; returns suggestions only, saves nothing
POST /api/offerings/{id}/scan/confirm                 save the confirmed questions and marks, in one transaction
PUT  /api/assessments/{id}/questions                  save one assessment's questions, max marks, COs and Bloom levels

One PDF per sitting: page 1 is the question paper, every later page a student's cover page. A CIE
paper has Part A (the quiz) and Part B (the test), numbered on across parts; CIE n fills 'Quiz n'
with Part A and 'CIE Test n' with Part B, and the SEE fills 'SEE'. An assessment that does not
exist yet is created from the paper. Within each assessment the questions are renumbered from Q1
in paper order (paper Q6, the first Part B question, is 'CIE Test 1' Q1); the cover-page row of a
question is its paper number. Confirmed marks go through the same validation, triggers and audit
as typed marks (api/services/marks.py). The PDF and the page images are not stored on the server.
"""

from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api import db
from api.auth import database, require
from api.db import User
from api.errors import message
from api.ocr import layout, reader
from api.ocr.paper import SITTINGS
from api.routers.offerings import record_denied
from api.services import marks
from api.services import questions as qsvc

router = APIRouter(prefix="/api")
editors = require("admin", "faculty")
MAX_BYTES = 40 * 1024 * 1024

Sitting = Literal["CIE1", "CIE2", "SEE"]
PART_LABEL = {"A": "Part A - Quiz", "B": "Part B - Test"}


class Locked(Exception):
    pass


class RowErrors(Exception):
    def __init__(self, errors: list[dict]):
        super().__init__(f"{len(errors)} problem(s)")
        self.errors = errors


def _offering(conn, offering_id: int) -> dict:
    row = conn.execute("SELECT offering_id, course_id FROM course_offering "
                       "WHERE offering_id = %s AND fn_can_view_offering(offering_id)", (offering_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Offering not found")
    return row


def _targets(conn, offering_id: int, sitting: str) -> dict[str, dict]:
    """Part -> the assessment it fills: existing (with its state) or to be created."""
    out = {}
    for part, (name, kind) in SITTINGS[sitting]["parts"].items():
        a = conn.execute("SELECT assessment_id, type::text AS type, max_marks, locked FROM assessment "
                         "WHERE offering_id = %s AND name = %s", (offering_id, name)).fetchone()
        if a and a["type"] != kind:
            raise HTTPException(409, f"'{name}' exists but is not a {kind} assessment; rename it first")
        t = {"part": part, "name": name, "type": kind, "assessment_id": None, "create": True,
             "locked": False, "max_marks": None, "marks_entered": 0, "saved": [], "with_marks": set()}
        if a:
            t.update(assessment_id=a["assessment_id"], create=False, locked=a["locked"],
                     max_marks=float(a["max_marks"]), saved=qsvc.saved(conn, a["assessment_id"]),
                     marks_entered=qsvc.marks_entered(conn, a["assessment_id"]),
                     with_marks={r["usn"] for r in conn.execute("""
                         SELECT DISTINCT e.usn FROM student_question_mark m JOIN enrollment e USING (enrollment_id)
                         JOIN assessment_question q USING (question_id) WHERE q.assessment_id = %s""",
                                                               (a["assessment_id"],))})
        out[part] = t
    locked = [t["name"] for t in out.values() if t["locked"]]
    if locked:
        raise Locked(f"{' and '.join(locked)} {'is' if len(locked) == 1 else 'are'} locked; "
                     "request an unlock before saving new sheets")
    return out


def _paper_number(q_no: str) -> int:
    return int(q_no[1:])


def renumber(qs: list[dict]) -> dict[str, str]:
    """Paper q_no -> the q_no within its assessment: Q1, Q2, ... per part in paper order."""
    out, count = {}, {}
    for q in sorted(qs, key=lambda q: _paper_number(q["q_no"])):
        count[q["part"]] = count.get(q["part"], 0) + 1
        out[q["q_no"]] = f"Q{count[q['part']]}"
    return out


def _saved_paper(targets: dict[str, dict]) -> list[dict]:
    """The saved questions laid out as a paper (Part A first, numbered on into Part B): used when
    page 1 cannot be read at all."""
    out = []
    for part in ("A", "B"):
        for q in targets.get(part, {}).get("saved", []):
            out.append({**q, "q_no": f"Q{len(out) + 1}", "cos": list(q["cos"]), "text": "", "part": part})
    return out


@router.post("/offerings/{offering_id}/scan")
def scan(offering_id: int, sitting: Sitting = Query(...), file: UploadFile = File(...),
         user: User = Depends(editors), dbname=Depends(database)):
    # A plain def: OCR takes seconds, so it runs in the threadpool and does not stall other requests.
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"The PDF is larger than {MAX_BYTES // (1024 * 1024)} MB")
    with db.session(user, dbname) as conn:
        o = _offering(conn, offering_id)
        try:
            targets = _targets(conn, offering_id, sitting)
        except Locked as exc:
            raise HTTPException(409, str(exc)) from None
        cos = {r["co_number"] for r in conn.execute(
            "SELECT co_number FROM course_outcome WHERE course_id = %s", (o["course_id"],))}
        enrolled = [r["usn"] for r in conn.execute(
            "SELECT usn FROM enrollment WHERE offering_id = %s ORDER BY usn", (offering_id,))]
        rule = conn.execute("""
            SELECT ac.ocr_review_confidence FROM v_offering_config oc JOIN attainment_config ac USING (config_id)
            WHERE oc.offering_id = %s""", (offering_id,)).fetchone()
        threshold = float(rule["ocr_review_confidence"]) if rule else reader.DEFAULT_REVIEW_CONFIDENCE
    # The database work is done; OCR runs outside the transaction.
    try:
        raw = reader.read_pdf(data, fallback=_saved_paper(targets))
    except reader.OcrError as exc:
        raise HTTPException(422, str(exc)) from exc

    paper = raw["paper"]
    warnings = list(paper["warnings"])
    questions = paper["questions"]
    beyond = [q["q_no"] for q in questions if reader.cover_row(q) is None]
    if beyond:
        warnings.append(f"The cover page has rows for Q1-Q{layout.MAX_QUESTIONS} only, so {', '.join(beyond)} "
                        "cannot be read or saved")
        questions = [q for q in questions if reader.cover_row(q) is not None]
    if not questions:
        raise HTTPException(422, "No question lines could be read on page 1, and this sitting has no saved "
                                 "questions to fall back on; check that page 1 is the question paper")
    if sitting == "SEE":
        if any(q["part"] == "A" for q in questions):
            warnings.append("The SEE paper has a Part A heading; the SEE has no quiz, so every question is "
                            "counted in the SEE")
        for q in questions:
            q["part"] = "B"
    elif not any(q["part"] for q in questions):
        warnings.append("No 'Part A - Quiz' or 'Part B - Test' heading was read; choose each question's part")
    for q in questions:
        q["problems"] = [f"CO{c} is not a CO of this course" for c in q["cos"] if c not in cos]
        if not 0 < q["max_marks"] <= 99:
            q["problems"].append("Max marks must be 1 to 99 to fit the two mark boxes")
        if q["part"] is None:
            q["problems"].append("Not under a Part A or Part B heading; choose its part")
    numbers = renumber([q for q in questions if q["part"]])
    for q in questions:
        q["number"] = numbers.get(q["q_no"])
    total_max = sum(q["max_marks"] for q in questions)
    if paper["paper_max"] is not None and paper["paper_max"] != total_max:
        warnings.append(f"Page 1 says max. marks {paper['paper_max']}; the questions add up to {total_max}")

    review = reader.review(raw, questions, enrolled, threshold)
    parts = []
    for part, t in targets.items():
        mine = [{"q_no": numbers[q["q_no"]], "max_marks": q["max_marks"], "cos": q["cos"], "bloom": q["bloom"]}
                for q in questions if q["part"] == part]
        total = sum(q["max_marks"] for q in mine)
        if t["create"] and mine:
            warnings.append(f"'{t['name']}' is not in this offering yet; it will be created, out of {total}")
        elif mine and t["marks_entered"] == 0 and t["max_marks"] != total:
            warnings.append(f"'{t['name']}' is out of {t['max_marks']:g}; its questions add up to {total}, "
                            "which becomes its maximum when saved")
        parts.append({
            "part": part, "heading": PART_LABEL[part] if sitting != "SEE" else "SEE paper",
            "name": t["name"], "type": t["type"], "assessment_id": t["assessment_id"], "create": t["create"],
            "max_marks": t["max_marks"], "marks_entered": t["marks_entered"],
            "same_as_saved": qsvc.same(mine, t["saved"]), "saved": t["saved"],
            # Students with no sheet in this PDF who already have marks: saved as AB only if the teacher says so.
            "absent_with_marks": sorted(set(review["absent"]) & t["with_marks"]),
        })
    return {
        "sitting": sitting, "label": SITTINGS[sitting]["label"], "offering_id": offering_id,
        "parts": parts,
        "paper": {"questions": questions, "warnings": warnings, "paper_max": paper["paper_max"]},
        "sheets": review["sheets"],
        "absent": review["absent"],
        "threshold": threshold,
    }


class ScanQuestionIn(qsvc.QuestionIn):
    part: Literal["A", "B"]


class ScanSheetIn(BaseModel):
    page: int | None = None
    usn: str = Field(max_length=20)
    marks: dict[str, int | float | str | None] = Field(max_length=layout.MAX_QUESTIONS)


class ConfirmIn(BaseModel):
    sitting: Sitting
    questions: list[ScanQuestionIn] = Field(min_length=1, max_length=layout.MAX_QUESTIONS)
    sheets: list[ScanSheetIn] = Field(max_length=reader.MAX_PAGES)
    # Students with no sheet who already have marks keep them unless this is set.
    overwrite_absent: bool = False


@router.post("/offerings/{offering_id}/scan/confirm")
def confirm(offering_id: int, body: ConfirmIn, user: User = Depends(editors), dbname=Depends(database)):
    """Save a confirmed scan: create missing assessments, save each part's questions (renumbered
    from Q1), then every sheet's marks and AB for students with no sheet, all in one transaction.
    Any row error returns 422 with every problem and saves nothing."""
    qs = body.questions
    if len({q.q_no for q in qs}) != len(qs):
        raise HTTPException(422, "A question number appears more than once")
    beyond = [q.q_no for q in qs if _paper_number(q.q_no) > layout.MAX_QUESTIONS or _paper_number(q.q_no) < 1]
    if beyond:
        raise HTTPException(422, f"The cover page has rows for Q1-Q{layout.MAX_QUESTIONS} only: {', '.join(beyond)}")
    if body.sitting == "SEE":
        qs = [q.model_copy(update={"part": "B"}) for q in qs]
    numbers = renumber([q.model_dump() for q in qs])
    result = []
    try:
        with db.session(user, dbname) as conn:
            o = _offering(conn, offering_id)
            targets = _targets(conn, offering_id, body.sitting)
            enrolled = [r["usn"] for r in conn.execute(
                "SELECT usn FROM enrollment WHERE offering_id = %s", (offering_id,))]
            on_sheet = {s.usn.strip().upper() for s in body.sheets}
            absent = [u for u in enrolled if u not in on_sheet]
            errors: list[dict] = []
            for part, t in targets.items():
                mine = sorted((q for q in qs if q.part == part), key=lambda q: _paper_number(q.q_no))
                if not mine:
                    continue
                aid = t["assessment_id"]
                if aid is None:
                    aid = conn.execute(
                        "INSERT INTO assessment (offering_id, type, name, max_marks) VALUES (%s, %s, %s, %s) "
                        "RETURNING assessment_id",
                        (offering_id, t["type"], t["name"], sum(q.max_marks for q in mine))).fetchone()["assessment_id"]
                own = [qsvc.QuestionIn(q_no=numbers[q.q_no], max_marks=q.max_marks, cos=q.cos, bloom=q.bloom)
                       for q in mine]
                try:
                    changed = qsvc.replace(conn, aid, o["course_id"], own)
                except qsvc.QuestionError as exc:
                    raise HTTPException(exc.status, f"{t['name']}: {exc.detail}") from None
                paper_of = {numbers[q.q_no]: q.q_no for q in mine}
                entries = [{"row": s.page, "usn": s.usn,
                            "marks": {numbers[q.q_no]: s.marks.get(q.q_no) for q in mine}} for s in body.sheets]
                entries += [{"row": None, "usn": u, "marks": {numbers[q.q_no]: "AB" for q in mine}}
                            for u in absent if body.overwrite_absent or u not in t["with_marks"]]
                rows, errs = marks.validate(conn, aid, entries, label=lambda q, p=paper_of: p.get(q, q))
                errors += [e for e in errs if e not in errors]   # a bad USN is reported once, not per part
                saved = 0 if errs else marks.save(conn, rows)
                result.append({"assessment_id": aid, "name": t["name"], "created": t["create"],
                               "questions_saved": changed, "questions": len(own), "marks_saved": saved})
            if errors:
                raise RowErrors(errors)
    except Locked as exc:
        record_denied(user, dbname, "student_question_mark", {"offering_id": offering_id, "sitting": body.sitting}, str(exc))
        return JSONResponse({"detail": str(exc), "code": "CP001"}, status_code=409)
    except RowErrors as exc:
        return JSONResponse({"detail": f"{len(exc.errors)} problem(s); nothing was saved", "errors": exc.errors},
                            status_code=422)
    except psycopg.Error as exc:
        if exc.sqlstate != "CP001":
            raise
        record_denied(user, dbname, "student_question_mark", {"offering_id": offering_id, "sitting": body.sitting},
                      message(exc))
        return JSONResponse({"detail": message(exc), "code": "CP001"}, status_code=409)
    return {"assessments": result, "saved": sum(r["marks_saved"] for r in result)}


@router.put("/assessments/{assessment_id}/questions")
def save_questions(assessment_id: int, body: qsvc.QuestionsIn, user: User = Depends(editors), dbname=Depends(database)):
    """Replace the questions of an assessment with no marks yet; once marks exist, only CO tags and
    Bloom levels may change (the question numbers and maxima must stay as they are)."""
    with db.session(user, dbname) as conn:
        a = conn.execute("""
            SELECT a.assessment_id, a.locked, o.course_id FROM assessment a JOIN course_offering o USING (offering_id)
            WHERE a.assessment_id = %s AND fn_can_view_offering(a.offering_id)""", (assessment_id,)).fetchone()
        if not a:
            raise HTTPException(404, "Assessment not found")
        if a["locked"]:
            raise HTTPException(409, "Assessment is locked; questions and CO tags cannot be changed")
        try:
            qsvc.replace(conn, assessment_id, a["course_id"], body.questions)
        except qsvc.QuestionError as exc:
            raise HTTPException(exc.status, exc.detail) from None
    return {"saved": len(body.questions)}
