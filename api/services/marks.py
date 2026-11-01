"""Question-wise marks upload from CSV (PRD FR-3.3).

Expected columns: `usn`, then one column per question named by its q_no (Q1, Q2, ...).
A cell holds the marks, or AB for an absent student. The whole file is validated first and
nothing is written if any row has an error; the database triggers check again on insert.
"""

import csv
import io
from decimal import Decimal, InvalidOperation

ABSENT = {"AB", "A", "ABSENT"}


def template(conn, assessment_id: int) -> str:
    qs = [r["q_no"] for r in conn.execute(
        "SELECT q_no FROM assessment_question WHERE assessment_id = %s ORDER BY question_id", (assessment_id,))]
    usns = [r["usn"] for r in conn.execute(
        "SELECT e.usn FROM enrollment e JOIN assessment a ON a.offering_id = e.offering_id "
        "WHERE a.assessment_id = %s ORDER BY e.usn", (assessment_id,))]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["usn", *qs])
    for u in usns:
        w.writerow([u, *[""] * len(qs)])
    return out.getvalue()


def parse(conn, assessment_id: int, text: str) -> tuple[list[tuple], list[dict]]:
    """Returns (rows to upsert, errors). Each error: {row, usn, column, message}."""
    questions = {r["q_no"]: (r["question_id"], r["max_marks"]) for r in conn.execute(
        "SELECT q_no, question_id, max_marks FROM assessment_question WHERE assessment_id = %s", (assessment_id,))}
    enrolled = {r["usn"]: r["enrollment_id"] for r in conn.execute(
        "SELECT e.usn, e.enrollment_id FROM enrollment e JOIN assessment a ON a.offering_id = e.offering_id "
        "WHERE a.assessment_id = %s", (assessment_id,))}
    errors: list[dict] = []
    rows: list[tuple] = []

    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    header = [h.strip() for h in (reader.fieldnames or [])]
    if not header or header[0].lower() != "usn":
        return [], [{"row": 1, "usn": None, "column": None, "message": "First column must be 'usn'"}]
    unknown = [h for h in header[1:] if h not in questions]
    if unknown:
        errors.append({"row": 1, "usn": None, "column": ", ".join(unknown),
                       "message": "Not a question of this assessment"})
    columns = [h for h in header[1:] if h in questions]

    seen = set()
    for line_no, raw in enumerate(reader, start=2):
        rec = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        usn = rec.get(header[0], "").upper()
        if usn not in enrolled:
            errors.append({"row": line_no, "usn": usn, "column": "usn", "message": "Not enrolled in this offering"})
            continue
        if usn in seen:
            errors.append({"row": line_no, "usn": usn, "column": "usn", "message": "Appears more than once"})
            continue
        seen.add(usn)
        for col in columns:
            qid, qmax = questions[col]
            cell = rec.get(col, "")
            if cell.upper() in ABSENT:
                rows.append((enrolled[usn], qid, None, True))
                continue
            try:
                value = Decimal(cell)
            except InvalidOperation:
                errors.append({"row": line_no, "usn": usn, "column": col,
                               "message": "Empty" if not cell else f"'{cell}' is not a number or AB"})
                continue
            if not 0 <= value <= qmax:
                errors.append({"row": line_no, "usn": usn, "column": col,
                               "message": f"{value} is outside 0 to {qmax}"})
                continue
            rows.append((enrolled[usn], qid, value, False))
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
