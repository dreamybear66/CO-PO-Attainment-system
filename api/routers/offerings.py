"""Offerings, assessments, marks, locking, computation, root cause and what-if (faculty and HoD)."""

import psycopg
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from api import db
from api.auth import database, require
from api.db import User
from api.errors import message
from api.services import marks, whatif

router = APIRouter(prefix="/api")
staff = require("admin", "faculty", "coordinator")
editors = require("admin", "faculty")

OFFERING_SQL = """
SELECT o.offering_id, c.course_id, c.code, c.title, c.semester, o.academic_year, o.term, o.section,
       f.name AS faculty, o.faculty_id,
       (SELECT count(*) FROM assessment a WHERE a.offering_id = o.offering_id) AS assessments,
       (SELECT count(*) FROM assessment a WHERE a.offering_id = o.offering_id AND a.locked) AS locked,
       (SELECT max(computed_at) FROM co_attainment ca WHERE ca.offering_id = o.offering_id) AS computed_at,
       (SELECT count(*) FROM co_attainment ca JOIN attainment_config cfg USING (config_id)
         WHERE ca.offering_id = o.offering_id AND ca.final_level < cfg.co_target_level) AS cos_below_target
FROM course_offering o
JOIN course c  ON c.course_id = o.course_id
JOIN faculty f ON f.faculty_id = o.faculty_id
"""


def visible_offering(conn, offering_id: int) -> dict:
    row = conn.execute(OFFERING_SQL + " WHERE o.offering_id = %s AND fn_can_view_offering(o.offering_id)",
                       (offering_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Offering not found")
    return row


# ---------------------------------------------------------------- offerings

@router.get("/offerings")
def list_offerings(academic_year: str | None = None, course_id: int | None = None,
                   user: User = Depends(staff), dbname=Depends(database)):
    where = ["fn_can_view_offering(o.offering_id)"]
    params: list = []
    if academic_year:
        where.append("o.academic_year = %s")
        params.append(academic_year)
    if course_id:
        where.append("o.course_id = %s")
        params.append(course_id)
    with db.session(user, dbname) as conn:
        return conn.execute(OFFERING_SQL + " WHERE " + " AND ".join(where) +
                            " ORDER BY o.academic_year DESC, o.term DESC, c.code, o.section", params).fetchall()


@router.get("/offerings/{offering_id}")
def offering_detail(offering_id: int, user: User = Depends(staff), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        head = visible_offering(conn, offering_id)
        assessments = conn.execute("""
            SELECT a.assessment_id, a.name, a.type, a.max_marks, a.locked, a.locked_at,
                   (SELECT count(*) FROM assessment_question q WHERE q.assessment_id = a.assessment_id) AS questions,
                   (SELECT count(*) FROM student_question_mark m JOIN assessment_question q USING (question_id)
                     WHERE q.assessment_id = a.assessment_id) AS marks_entered,
                   (SELECT count(*) FROM enrollment e WHERE e.offering_id = a.offering_id)
                   * (SELECT count(*) FROM assessment_question q WHERE q.assessment_id = a.assessment_id) AS marks_expected,
                   (SELECT r.status FROM unlock_request r WHERE r.assessment_id = a.assessment_id
                     ORDER BY r.requested_at DESC LIMIT 1) AS unlock_status
            FROM assessment a WHERE a.offering_id = %s
            ORDER BY array_position(ARRAY['CIE_THEORY','CIE_QUIZ','EL','SEE']::assessment_component[], a.type), a.name
        """, (offering_id,)).fetchall()
        cos = conn.execute("""
            SELECT co.co_id, co.co_number, co.statement, co.bloom_level
            FROM course_outcome co WHERE co.course_id = %s ORDER BY co.co_number""", (head["course_id"],)).fetchall()
        cfg = conn.execute("""
            SELECT c.*, (SELECT json_object_agg(component, weight_pct) FROM config_component_weight w
                          WHERE w.config_id = c.config_id) AS component_weights
            FROM v_offering_config oc JOIN attainment_config c USING (config_id) WHERE oc.offering_id = %s
        """, (offering_id,)).fetchone()
        enrolled = conn.execute("SELECT count(*) AS n FROM enrollment WHERE offering_id = %s", (offering_id,)).fetchone()["n"]
    return {**head, "enrolled": enrolled, "assessments": assessments, "cos": cos, "config": cfg}


# ---------------------------------------------------------------- marks and locking

def assessment_or_404(conn, assessment_id: int) -> dict:
    row = conn.execute("SELECT assessment_id, offering_id, locked FROM assessment WHERE assessment_id = %s",
                       (assessment_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Assessment not found")
    return row


@router.get("/assessments/{assessment_id}/template", response_class=PlainTextResponse)
def marks_template(assessment_id: int, user: User = Depends(editors), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        assessment_or_404(conn, assessment_id)
        csv_text = marks.template(conn, assessment_id)
    return PlainTextResponse(csv_text, media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="assessment-{assessment_id}.csv"'})


@router.post("/assessments/{assessment_id}/marks")
async def upload_marks(assessment_id: int, file: UploadFile = File(...),
                       user: User = Depends(editors), dbname=Depends(database)):
    text = (await file.read()).decode("utf-8", errors="replace")
    locked_msg = "Assessment is locked; marks cannot be changed"
    try:
        with db.session(user, dbname) as conn:
            if assessment_or_404(conn, assessment_id)["locked"]:
                saved = None
            else:
                rows, errors = marks.parse(conn, assessment_id, text)
                if errors:
                    return JSONResponse({"detail": f"{len(errors)} problem(s); nothing was saved",
                                         "errors": errors}, status_code=422)
                saved = marks.save(conn, rows)
    except psycopg.Error as exc:
        if exc.sqlstate == "CP001":
            saved, locked_msg = None, message(exc)
        else:
            raise
    if saved is None:
        record_denied(user, dbname, "student_question_mark", {"assessment_id": assessment_id}, locked_msg)
        return JSONResponse({"detail": locked_msg, "code": "CP001"}, status_code=409)
    return {"saved": saved}


def record_denied(user: User, dbname, table: str, key: dict, detail: str) -> None:
    """Rejected writes roll back, so the attempt is logged in a transaction of its own."""
    import json
    with db.session(user, dbname) as conn:
        conn.execute("SELECT fn_audit_denied(%s, %s::jsonb, %s::jsonb)",
                     (table, json.dumps(key), json.dumps({"error": detail})))


@router.post("/assessments/{assessment_id}/lock")
def lock(assessment_id: int, user: User = Depends(editors), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        assessment_or_404(conn, assessment_id)
        conn.execute("UPDATE assessment SET locked = true WHERE assessment_id = %s AND NOT locked", (assessment_id,))
    return {"locked": True}


class UnlockRequestIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/assessments/{assessment_id}/unlock-requests", status_code=201)
def request_unlock(assessment_id: int, body: UnlockRequestIn, user: User = Depends(editors), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        a = assessment_or_404(conn, assessment_id)
        if not a["locked"]:
            raise HTTPException(409, "Assessment is not locked")
        rid = conn.execute("INSERT INTO unlock_request (assessment_id, requested_by, reason) VALUES (%s, %s, %s) "
                           "RETURNING request_id", (assessment_id, user.user_id, body.reason)).fetchone()["request_id"]
    return {"request_id": rid}


@router.post("/assessments/{assessment_id}/unlock")
def unlock(assessment_id: int, user: User = Depends(editors), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        assessment_or_404(conn, assessment_id)
        conn.execute("UPDATE assessment SET locked = false WHERE assessment_id = %s AND locked", (assessment_id,))
    return {"locked": False}


# ---------------------------------------------------------------- attainment

def attainment(conn, offering_id: int) -> dict:
    cos = conn.execute("""
        SELECT co.co_id, co.co_number, co.statement, ca.students, ca.pct_attained, ca.direct_level,
               ca.indirect_level, ca.final_level, cfg.co_target_level AS target, ca.config_id, ca.computed_at,
               ia.respondents, ia.pct_favourable
        FROM co_attainment ca
        JOIN course_outcome co      ON co.co_id = ca.co_id
        JOIN attainment_config cfg  ON cfg.config_id = ca.config_id
        LEFT JOIN indirect_attainment ia ON ia.offering_id = ca.offering_id AND ia.co_id = ca.co_id
        WHERE ca.offering_id = %s ORDER BY co.co_number""", (offering_id,)).fetchall()
    pos = conn.execute("""
        SELECT po.po_id, po.code, po.type, po.statement, pa.attainment, cfg.po_target_level AS target
        FROM po_attainment pa
        JOIN program_outcome po    ON po.po_id = pa.po_id
        JOIN attainment_config cfg ON cfg.config_id = pa.config_id
        WHERE pa.offering_id = %s ORDER BY po.po_id""", (offering_id,)).fetchall()
    cells = conn.execute("""
        SELECT m.co_id, m.po_id, m.strength
        FROM co_po_map m JOIN course_outcome co USING (co_id)
        JOIN course_offering o ON o.course_id = co.course_id
        WHERE o.offering_id = %s""", (offering_id,)).fetchall()
    actions = conn.execute("""
        SELECT f.*, co.co_number, prev.academic_year AS from_year, nxt.academic_year AS follow_up_year
        FROM v_improvement_followup f
        JOIN course_outcome co ON co.co_id = f.co_id
        JOIN course_offering prev ON prev.offering_id = f.offering_id
        LEFT JOIN course_offering nxt ON nxt.offering_id = f.follow_up_offering_id
        WHERE f.offering_id = %s OR f.follow_up_offering_id = %s
        ORDER BY f.offering_id = %s, co.co_number""", (offering_id, offering_id, offering_id)).fetchall()
    return {"cos": cos, "pos": pos, "map": cells, "actions": actions}


@router.get("/offerings/{offering_id}/attainment")
def get_attainment(offering_id: int, user: User = Depends(staff), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        visible_offering(conn, offering_id)
        return attainment(conn, offering_id)


@router.post("/offerings/{offering_id}/compute")
def compute(offering_id: int, user: User = Depends(editors), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        visible_offering(conn, offering_id)
        conn.execute("SET LOCAL lock_timeout = '5s'")
        conn.execute("CALL sp_compute_attainment(%s)", (offering_id,))
        return attainment(conn, offering_id)


# ---------------------------------------------------------------- root cause and what-if

@router.get("/offerings/{offering_id}/cos/{co_id}/root-cause")
def root_cause(offering_id: int, co_id: int, user: User = Depends(staff), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        visible_offering(conn, offering_id)
        return conn.execute("SELECT * FROM fn_root_cause(%s, %s)", (offering_id, co_id)).fetchall()


@router.post("/offerings/{offering_id}/cos/{co_id}/root-cause/action", status_code=201)
def root_cause_action(offering_id: int, co_id: int, user: User = Depends(editors), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        action_id = conn.execute("SELECT fn_root_cause_action(%s, %s) AS id", (offering_id, co_id)).fetchone()["id"]
    if action_id is None:
        raise HTTPException(409, "No upstream CO passes the evidence thresholds")
    return {"action_id": action_id}


class WhatIfIn(BaseModel):
    name: str = Field(default="Scenario", max_length=80)
    target_pct: float | None = Field(default=None, ge=0, le=100)
    l3_pct: float | None = Field(default=None, ge=0, le=100)
    l2_pct: float | None = Field(default=None, ge=0, le=100)
    l1_pct: float | None = Field(default=None, ge=0, le=100)
    direct_weight: float | None = Field(default=None, ge=0, le=100)
    indirect_weight: float | None = Field(default=None, ge=0, le=100)
    co_target_level: float | None = Field(default=None, ge=0, le=3)
    po_target_level: float | None = Field(default=None, ge=0, le=3)


@router.post("/offerings/{offering_id}/whatif")
def run_whatif(offering_id: int, body: WhatIfIn, user: User = Depends(editors), dbname=Depends(database)):
    rules = {k: v for k, v in body.model_dump().items() if k != "name" and v is not None}
    with db.session(user, dbname) as conn:
        visible_offering(conn, offering_id)
        sid = whatif.create_and_run(conn, offering_id=offering_id, created_by=user.user_id, name=body.name, rules=rules)
        return whatif.compare(conn, sid)
