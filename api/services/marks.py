"""Question-wise marks: the one validated path into `student_question_mark` (PRD FR-3.3).

Marks arrive two ways: typed in the app (experiential learning) and confirmed from scanned answer
sheets (CIE tests, quizzes and the SEE). Both hand `validate` a batch of rows
`{"row": n, "usn": "1RV...", "marks": {"Q1": 7, "Q2": "AB"}}`: a value is a number of marks, or AB
for an absent student. The whole batch is checked first and nothing is written if any row has an
error; the database triggers check again on insert, and every change reaches the audit chain.
"""

from collections.abc import Callable
from decimal import Decimal, InvalidOperation

ABSENT = {"AB", "A", "ABSENT"}


def questions(conn, assessment_id: int) -> dict[str, tuple[int, Decimal]]:
    """q_no -> (question_id, max_marks), in question order."""
    return {r["q_no"]: (r["question_id"], r["max_marks"]) for r in conn.execute(
        "SELECT q_no, question_id, max_marks FROM assessment_question WHERE assessment_id = %s "
        "ORDER BY question_id", (assessment_id,))}


def enrolled(conn, assessment_id: int) -> dict[str, int]:
    """USN -> enrollment_id for the assessment's offering."""
    return {r["usn"]: r["enrollment_id"] for r in conn.execute(
        "SELECT e.usn, e.enrollment_id FROM enrollment e JOIN assessment a ON a.offering_id = e.offering_id "
        "WHERE a.assessment_id = %s", (assessment_id,))}


def _value(cell) -> tuple[Decimal | None, bool, str | None]:
    """(marks, absent, problem) of one cell."""
    if cell is None or (isinstance(cell, str) and not cell.strip()):
        return None, False, "Empty"
    if isinstance(cell, bool):
        return None, False, f"'{cell}' is not a number or AB"
    if isinstance(cell, str):
        if cell.strip().upper() in ABSENT:
            return None, True, None
        text = cell.strip()
    else:
        text = str(cell)                                  # str() keeps 2.5 as 2.5, not a binary fraction
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None, False, f"'{cell}' is not a number or AB"
    if not value.is_finite():                             # NaN, sNaN and Infinity
        return None, False, f"'{cell}' is not a number or AB"
    return value, False, None


def validate(conn, assessment_id: int, entries: list[dict],
             label: Callable[[str], str] = lambda q: q) -> tuple[list[tuple], list[dict]]:
    """Returns (rows to upsert, errors). Each error: {row, usn, column, message}; `label` names a
    question in the errors (the scan uses the paper's numbering). A question left out of a row is
    not touched."""
    qs = questions(conn, assessment_id)
    students = enrolled(conn, assessment_id)
    errors: list[dict] = []
    rows: list[tuple] = []
    seen = set()
    for entry in entries:
        line, usn = entry.get("row"), (entry.get("usn") or "").strip().upper()
        if usn not in students:
            errors.append({"row": line, "usn": usn, "column": "usn", "message": "Not enrolled in this offering"})
            continue
        if usn in seen:
            errors.append({"row": line, "usn": usn, "column": "usn", "message": "Appears more than once"})
            continue
        seen.add(usn)
        for q_no, cell in entry.get("marks", {}).items():
            if q_no not in qs:
                errors.append({"row": line, "usn": usn, "column": label(q_no),
                               "message": "Not a question of this assessment"})
                continue
            qid, qmax = qs[q_no]
            value, absent, problem = _value(cell)
            if problem:
                errors.append({"row": line, "usn": usn, "column": label(q_no), "message": problem})
            elif absent:
                rows.append((students[usn], qid, None, True))
            elif not 0 <= value <= qmax:
                errors.append({"row": line, "usn": usn, "column": label(q_no),
                               "message": f"{value} is outside 0 to {qmax.normalize():f}"})
            else:
                rows.append((students[usn], qid, value, False))
    return rows, errors


def save(conn, rows: list[tuple]) -> int:
    if not rows:
        return 0
    cols = list(zip(*rows))
    conn.execute("""
        INSERT INTO student_question_mark (enrollment_id, question_id, marks_obtained, is_absent)
        SELECT * FROM unnest(%s::int[], %s::int[], %s::numeric[], %s::boolean[])
        ON CONFLICT (enrollment_id, question_id)
        DO UPDATE SET marks_obtained = EXCLUDED.marks_obtained, is_absent = EXCLUDED.is_absent
        WHERE (student_question_mark.marks_obtained, student_question_mark.is_absent)
              IS DISTINCT FROM (EXCLUDED.marks_obtained, EXCLUDED.is_absent)
    """, (list(cols[0]), list(cols[1]), list(cols[2]), list(cols[3])))
    return len(rows)


def sheet(conn, assessment_id: int) -> dict:
    """Every enrolled student's marks for the assessment, for the typed-marks table:
    {questions: [{q_no, max_marks}], students: [{usn, name, marks: {q_no: n | 'AB' | None}}]}."""
    qs = conn.execute("SELECT q_no, max_marks FROM assessment_question WHERE assessment_id = %s "
                      "ORDER BY question_id", (assessment_id,)).fetchall()
    people = conn.execute("""
        SELECT e.usn, s.name, e.enrollment_id FROM enrollment e
        JOIN assessment a ON a.offering_id = e.offering_id JOIN student s ON s.usn = e.usn
        WHERE a.assessment_id = %s ORDER BY e.usn""", (assessment_id,)).fetchall()
    got = {}
    for r in conn.execute("""
            SELECT m.enrollment_id, q.q_no, m.marks_obtained, m.is_absent
            FROM student_question_mark m JOIN assessment_question q USING (question_id)
            WHERE q.assessment_id = %s""", (assessment_id,)):
        v = "AB" if r["is_absent"] else r["marks_obtained"]
        got[(r["enrollment_id"], r["q_no"])] = int(v) if isinstance(v, Decimal) and v == v.to_integral() else (
            float(v) if isinstance(v, Decimal) else v)
    return {
        "questions": [{"q_no": q["q_no"], "max_marks": float(q["max_marks"])} for q in qs],
        "students": [{"usn": p["usn"], "name": p["name"],
                      "marks": {q["q_no"]: got.get((p["enrollment_id"], q["q_no"])) for q in qs}} for p in people],
    }
