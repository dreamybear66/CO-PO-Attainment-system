"""An assessment's questions: number, maximum, CO tags (equal weights) and Bloom level.

Used by the scan confirmation, the PUT questions endpoint and EL creation. While no marks are
entered the questions are replaced and the assessment's maximum follows their sum; once marks
exist only the CO tags and Bloom levels may change.
"""

from decimal import ROUND_DOWN, Decimal

from pydantic import BaseModel, Field, field_validator

from api.ocr import layout


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


class QuestionError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def weights(n: int) -> list[Decimal]:
    """Equal CO weights that add up to exactly 1 at three decimals (0.333, 0.333, 0.334)."""
    base = (Decimal(1) / n).quantize(Decimal("0.001"), rounding=ROUND_DOWN)
    return [base] * (n - 1) + [Decimal(1) - base * (n - 1)]


def saved(conn, assessment_id: int) -> list[dict]:
    """The saved questions in order: [{q_no, max_marks, bloom, cos}]."""
    return conn.execute("""
        SELECT q.q_no, q.max_marks::int AS max_marks, q.bloom_level AS bloom,
               coalesce(array_agg(co.co_number ORDER BY co.co_number)
                        FILTER (WHERE co.co_number IS NOT NULL), '{}') AS cos
        FROM assessment_question q
        LEFT JOIN question_co_map m USING (question_id)
        LEFT JOIN course_outcome co USING (co_id)
        WHERE q.assessment_id = %s GROUP BY q.question_id ORDER BY q.question_id""", (assessment_id,)).fetchall()


def marks_entered(conn, assessment_id: int) -> int:
    return conn.execute("""
        SELECT count(*) AS n FROM student_question_mark m JOIN assessment_question q USING (question_id)
        WHERE q.assessment_id = %s""", (assessment_id,)).fetchone()["n"]


def same(a: list[dict], b: list[dict]) -> bool:
    def norm(qs):
        return [(q["q_no"], int(q["max_marks"]), sorted(q["cos"]), q["bloom"]) for q in qs]
    return norm(a) == norm(b)


def replace(conn, assessment_id: int, course_id: int, qs: list[QuestionIn]) -> bool:
    """Save `qs` as the assessment's questions. Returns False when they equal the saved ones (nothing
    written). Raises QuestionError for unknown COs, repeated numbers or a reshape after marks."""
    if len({q.q_no for q in qs}) != len(qs):
        raise QuestionError(422, "A question number appears more than once")
    co_ids = {r["co_number"]: r["co_id"] for r in conn.execute(
        "SELECT co_number, co_id FROM course_outcome WHERE course_id = %s", (course_id,))}
    unknown = sorted({c for q in qs for c in q.cos} - set(co_ids))
    if unknown:
        raise QuestionError(422, "Not COs of this course: " + ", ".join(f"CO{c}" for c in unknown))
    if same([q.model_dump() for q in qs], saved(conn, assessment_id)):
        return False
    rows = {r["q_no"]: r for r in conn.execute(
        "SELECT question_id, q_no, max_marks FROM assessment_question WHERE assessment_id = %s",
        (assessment_id,))}
    if marks_entered(conn, assessment_id):
        if {q.q_no: q.max_marks for q in qs} != {k: int(v["max_marks"]) for k, v in rows.items()}:
            raise QuestionError(409, "Marks are already entered, so only CO tags and Bloom levels can change; "
                                     "the question numbers and maximum marks must match the saved ones")
        ids = {q.q_no: rows[q.q_no]["question_id"] for q in qs}
        conn.execute("DELETE FROM question_co_map WHERE question_id = ANY(%s)", (list(ids.values()),))
        for q in qs:
            conn.execute("UPDATE assessment_question SET bloom_level = %s WHERE question_id = %s",
                         (q.bloom, ids[q.q_no]))
    else:
        if rows:
            old = [v["question_id"] for v in rows.values()]
            conn.execute("DELETE FROM question_co_map WHERE question_id = ANY(%s)", (old,))
            conn.execute("DELETE FROM assessment_question WHERE question_id = ANY(%s)", (old,))
        ids = {}
        for q in qs:
            ids[q.q_no] = conn.execute(
                "INSERT INTO assessment_question (assessment_id, q_no, max_marks, bloom_level) "
                "VALUES (%s, %s, %s, %s) RETURNING question_id",
                (assessment_id, q.q_no, q.max_marks, q.bloom)).fetchone()["question_id"]
        # The paper is the source of the maximum: lock checks that the questions add up to it.
        conn.execute("UPDATE assessment SET max_marks = %s WHERE assessment_id = %s AND max_marks <> %s",
                     (sum(q.max_marks for q in qs), assessment_id, sum(q.max_marks for q in qs)))
    for q in qs:
        for co, w in zip(q.cos, weights(len(q.cos))):
            conn.execute("INSERT INTO question_co_map (question_id, co_id, weight) VALUES (%s, %s, %s)",
                         (ids[q.q_no], co_ids[co], w))
    return True
