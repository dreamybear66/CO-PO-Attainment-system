"""Students who need help: weak-student lists and early warning (phase 9, FR-6.4, FR-6.5).

GET  /api/offerings/{id}/students        students below target per CO, and the latest early warning
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
