"""Students who need help: weak-student lists and early warning (phase 9, FR-6.4, FR-6.5).

GET  /api/offerings/{id}/students        students below target per CO, and the latest early warning
GET  /api/offerings/{id}/weak-students   per student below target: missed COs, questions that cost the
                                         most marks, and weak prerequisite COs (root cause per student)
POST /api/offerings/{id}/early-warning   run the early warning now (it also runs after each CIE lock)
"""

import logging

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from api import config, db
from api.auth import database, require
from api.db import User
from api.services import early_warning

router = APIRouter(prefix="/api")
editors = require("admin", "faculty")
staff = require("admin", "faculty", "coordinator")
log = logging.getLogger(__name__)


def _visible(conn, offering_id: int) -> dict:
    row = conn.execute("SELECT o.offering_id, o.course_id FROM course_offering o "
                       "WHERE o.offering_id = %s AND fn_can_view_offering(o.offering_id)", (offering_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Offering not found")
    return row


@router.get("/offerings/{offering_id}/students")
def students(offering_id: int, user: User = Depends(staff), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        _visible(conn, offering_id)
        finished = conn.execute("""
            SELECT EXISTS (SELECT 1 FROM assessment WHERE offering_id = %s)
               AND NOT EXISTS (SELECT 1 FROM assessment WHERE offering_id = %s AND NOT locked) AS f""",
                                (offering_id, offering_id)).fetchone()["f"]
        target = conn.execute("SELECT ac.target_pct FROM v_offering_config oc JOIN attainment_config ac USING (config_id) "
                              "WHERE oc.offering_id = %s", (offering_id,)).fetchone()
        cos = conn.execute("""
            SELECT co.co_id, co.co_number, co.statement FROM course_outcome co
            JOIN course_offering o ON o.course_id = co.course_id WHERE o.offering_id = %s ORDER BY co.co_number""",
                           (offering_id,)).fetchall()
        # CO scores from the marks entered so far (all of them once the term is over).
        scores = conn.execute("""
            SELECT s.co_id, s.usn, st.name, round(s.pct, 1) AS pct
            FROM student_co_score s JOIN student st USING (usn)
            WHERE s.offering_id = %s ORDER BY s.co_id, s.pct, s.usn""", (offering_id,)).fetchall()
        run = conn.execute("SELECT stage, model, flag_prob, computed_at FROM early_warning_run WHERE offering_id = %s",
                           (offering_id,)).fetchone()
        flagged = conn.execute("""
            SELECT w.usn, st.name, w.co_id, w.probability, w.reasons FROM early_warning w JOIN student st USING (usn)
            WHERE w.offering_id = %s AND w.flagged ORDER BY w.probability DESC, w.usn""", (offering_id,)).fetchall() if run else []
        enrolled = conn.execute("SELECT count(*) AS n FROM enrollment WHERE offering_id = %s", (offering_id,)).fetchone()["n"]
    target_pct = float(target["target_pct"]) if target else None
    weak = []
    for co in cos:
        rows = [s for s in scores if s["co_id"] == co["co_id"]]
        below = [{"usn": s["usn"], "name": s["name"], "pct": s["pct"]} for s in rows
                 if target_pct is not None and s["pct"] < target_pct]
        weak.append({**co, "scored": len(rows), "below": below})
    return {"finished": finished, "target_pct": target_pct, "enrolled": enrolled, "weak": weak,
            "early_warning": {**run, "flagged": flagged} if run else None}


QUESTIONS_SHOWN = 3


@router.get("/offerings/{offering_id}/weak-students")
def weak_students(offering_id: int, user: User = Depends(staff), dbname=Depends(database)):
    """Root cause per student. For every student below the CO target in one or more COs (their CO
    scores from the best two CIEs and the SEE, under the rule version of the offering's results):
    each missed CO with their score, the questions on those COs where they lost the most marks
    (outside any CIE they dropped), and the prerequisite COs (co_dependency, as in fn_root_cause)
    with their earlier score and whether they were weak there too."""
    with db.session(user, dbname) as conn:
        _visible(conn, offering_id)
        cfg = conn.execute("SELECT ac.config_id, ac.target_pct FROM attainment_config ac "
                           "WHERE ac.config_id = fn_result_config(%s)", (offering_id,)).fetchone()
        if not cfg:
            return {"target_pct": None, "students": []}
        missed = conn.execute("""
            SELECT s.usn, st.name, s.co_id, co.co_number, co.statement, round(s.pct, 1) AS pct
            FROM student_co_score_by_config s
            JOIN student st USING (usn) JOIN course_outcome co USING (co_id)
            WHERE s.offering_id = %s AND s.config_id = %s AND s.pct < %s
            ORDER BY s.usn, co.co_number""", (offering_id, cfg["config_id"], cfg["target_pct"])).fetchall()
        prereqs = conn.execute("SELECT * FROM fn_student_root_cause(%s)", (offering_id,)).fetchall()
        questions = conn.execute("""
            WITH weak AS (
                SELECT s.usn, s.co_id FROM student_co_score_by_config s
                WHERE s.offering_id = %(o)s AND s.config_id = %(c)s AND s.pct < %(t)s
            ),
            q AS (
                SELECT e.usn, a.name AS assessment, a.cie_no, aq.question_id, aq.q_no, aq.max_marks,
                       coalesce(m.marks_obtained, 0) AS got, m.is_absent,
                       array_agg(co.co_number ORDER BY co.co_number) AS cos, array_agg(qcm.co_id) AS co_ids
                FROM student_question_mark m
                JOIN enrollment e           USING (enrollment_id)
                JOIN assessment_question aq ON aq.question_id = m.question_id
                JOIN assessment a           ON a.assessment_id = aq.assessment_id
                JOIN question_co_map qcm    ON qcm.question_id = m.question_id
                JOIN course_outcome co      ON co.co_id = qcm.co_id
                WHERE e.offering_id = %(o)s AND e.usn IN (SELECT usn FROM weak) AND a.type <> 'EL'
                GROUP BY e.usn, a.name, a.cie_no, aq.question_id, aq.q_no, aq.max_marks, m.marks_obtained, m.is_absent
            ),
            ranked AS (
                SELECT q.*, q.max_marks - q.got AS lost,
                       row_number() OVER (PARTITION BY q.usn ORDER BY q.max_marks - q.got DESC,
                                          (q.max_marks - q.got) / q.max_marks DESC, q.question_id) AS place
                FROM q
                WHERE q.max_marks > q.got
                  AND EXISTS (SELECT 1 FROM weak w WHERE w.usn = q.usn AND w.co_id = ANY (q.co_ids))
                  AND NOT EXISTS (SELECT 1 FROM student_cie_result r
                                  WHERE r.offering_id = %(o)s AND r.usn = q.usn AND r.cie_no = q.cie_no AND NOT r.kept)
            )
            SELECT usn, assessment, q_no, cos, max_marks, got, is_absent, lost FROM ranked
            WHERE place <= %(n)s ORDER BY usn, place""",
                                 {"o": offering_id, "c": cfg["config_id"], "t": cfg["target_pct"],
                                  "n": QUESTIONS_SHOWN}).fetchall()
    by_student: dict[str, dict] = {}
    for m in missed:
        st = by_student.setdefault(m["usn"], {"usn": m["usn"], "name": m["name"], "missed": [], "questions": []})
        st["missed"].append({"co_id": m["co_id"], "co_number": m["co_number"], "statement": m["statement"],
                             "pct": m["pct"], "prereqs": []})
    for r in prereqs:
        co = next((c for c in by_student.get(r["usn"], {}).get("missed", []) if c["co_id"] == r["co_id"]), None)
        if co is not None and r["up_pct"] is not None:        # only prerequisites the student has a score on
            co["prereqs"].append({"course_code": r["up_course_code"], "co_number": r["up_co_number"],
                                  "statement": r["up_statement"], "depth": r["depth"],
                                  "academic_year": r["up_academic_year"], "pct": r["up_pct"],
                                  "target_pct": r["up_target_pct"], "below": r["up_below"]})
    for q in questions:
        by_student[q["usn"]]["questions"].append({k: q[k] for k in ("assessment", "q_no", "cos", "max_marks", "got",
                                                                     "is_absent", "lost")})
    students = sorted(by_student.values(),
                      key=lambda s: (-len(s["missed"]), sum(float(c["pct"]) for c in s["missed"]) / len(s["missed"]),
                                     s["usn"]))
    for st in students:
        st["weak_prereqs"] = sum(1 for c in st["missed"] for p in c["prereqs"] if p["below"])
    return {"target_pct": cfg["target_pct"], "students": students}


def _run(user: User, dbname, offering_id: int) -> dict:
    # Training reads other teachers' finished offerings: owner connection, model only leaves it.
    with psycopg.connect(config.owner_dsn(dbname)) as owner:
        result = early_warning.predict(owner, offering_id)
    with db.session(user, dbname) as conn:
        _visible(conn, offering_id)
        early_warning.save(conn, offering_id, result)
    return result


@router.post("/offerings/{offering_id}/early-warning")
def run_early_warning(offering_id: int, user: User = Depends(editors), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        _visible(conn, offering_id)          # other teachers' offerings are invisible (404)
    try:
        result = _run(user, dbname, offering_id)
    except early_warning.EarlyWarningError as exc:
        raise HTTPException(409, str(exc)) from None
    flagged = sum(p["flagged"] for p in result["predictions"])
    return {"flagged": flagged, "predictions": len(result["predictions"]), "stage": result["stage"],
            "model": result["model"]}


def refresh_after_lock(user: User, dbname, offering_id: int) -> None:
    """Called after a CIE assessment is locked. Best effort: the lock stands whatever happens here."""
    try:
        _run(user, dbname, offering_id)
    except early_warning.EarlyWarningError:
        pass                                    # e.g. no earlier offering to learn from yet
    except Exception:                           # never turn a successful lock into an error
        log.exception("early warning after lock failed for offering %s", offering_id)
