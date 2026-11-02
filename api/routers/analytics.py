"""Trends, rankings, programme-level PO and improvement actions (PRD FR-6.1, FR-4.4, FR-4.5).

Programme-wide figures (result years, weakest COs, programme PO) come from owner-run aggregate
functions, so every staff role sees the same programme numbers. Course trends and actions read the
base tables, so row-level security limits faculty to their own offerings there.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api import db
from api.auth import database, require
from api.db import User

router = APIRouter(prefix="/api")
staff = require("admin", "faculty", "coordinator")


@router.get("/courses")
def courses(user: User = Depends(staff), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        return conn.execute("SELECT course_id, code, title, semester FROM course ORDER BY semester, code").fetchall()


@router.get("/academic-years")
def academic_years(user: User = Depends(staff), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        return [r["y"] for r in conn.execute("SELECT fn_result_years() AS y")]


@router.get("/analytics/trend")
def course_trend(course_id: int, user: User = Depends(staff), dbname=Depends(database)):
    """Final level per CO and academic year (sections averaged), with the change on last year (LAG)."""
    with db.session(user, dbname) as conn:
        return conn.execute("""
            WITH yearly AS (
                SELECT co.co_id, co.co_number, co.statement, o.academic_year,
                       round(avg(ca.final_level), 2) AS final_level, count(*) AS sections,
                       max(cfg.co_target_level) AS target
                FROM co_attainment ca
                JOIN course_offering o     ON o.offering_id = ca.offering_id
                JOIN course_outcome co     ON co.co_id = ca.co_id
                JOIN attainment_config cfg ON cfg.config_id = ca.config_id
                WHERE o.course_id = %s
                GROUP BY co.co_id, co.co_number, co.statement, o.academic_year
            )
            SELECT y.*, y.final_level - lag(y.final_level) OVER (PARTITION BY y.co_id ORDER BY y.academic_year)
                   AS change_vs_prev_year
            FROM yearly y ORDER BY y.co_number, y.academic_year""", (course_id,)).fetchall()


@router.get("/analytics/weakest")
def weakest(academic_year: str, limit: int = 10, user: User = Depends(staff), dbname=Depends(database)):
    """Weakest COs of a year across the programme (RANK over the sections' average)."""
    with db.session(user, dbname) as conn:
        return conn.execute("SELECT * FROM fn_weakest_cos(%s, %s)", (academic_year, limit)).fetchall()


@router.get("/analytics/program-po")
def program_po(user: User = Depends(staff), dbname=Depends(database)):
    """Programme-level PO per academic year: plain average of offering-level values (S10), each
    year against its own rule versions' target."""
    with db.session(user, dbname) as conn:
        return conn.execute("SELECT * FROM fn_program_po_attainment()").fetchall()


@router.get("/actions")
def actions(status: str | None = None, user: User = Depends(staff), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        return conn.execute("""
            SELECT f.*, c.code, co.co_number, o.academic_year, o.section, nxt.academic_year AS follow_up_year
            FROM v_improvement_followup f
            JOIN course_offering o ON o.offering_id = f.offering_id
            JOIN course c          ON c.course_id = o.course_id
            JOIN course_outcome co ON co.co_id = f.co_id
            LEFT JOIN course_offering nxt ON nxt.offering_id = f.follow_up_offering_id
            WHERE %s::text IS NULL OR f.status = %s
            ORDER BY o.academic_year DESC, c.code, o.section, co.co_number""", (status, status)).fetchall()


class ActionPatch(BaseModel):
    status: str


@router.patch("/actions/{action_id}")
def update_action(action_id: int, body: ActionPatch, user: User = Depends(require("admin", "faculty")),
                  dbname=Depends(database)):
    if body.status not in ("open", "in_progress", "done"):
        raise HTTPException(422, "Status must be open, in_progress or done")
    with db.session(user, dbname) as conn:
        cur = conn.execute("UPDATE improvement_action SET status = %s WHERE action_id = %s", (body.status, action_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "Action not found")
    return {"action_id": action_id, "status": body.status}
