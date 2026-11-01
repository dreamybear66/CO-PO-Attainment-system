"""HoD and coordinator work: unlock approvals, rule versions, audit verification."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from api import db
from api.auth import database, require
from api.db import User
from api.jobs import audit
from api.mongo import get_db

router = APIRouter(prefix="/api")


@router.get("/unlock-requests")
def unlock_requests(status: str | None = "pending", user: User = Depends(require("admin", "faculty")),
                    dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        return conn.execute("""
            SELECT r.request_id, r.assessment_id, r.reason, r.status, r.requested_at, r.decided_at,
                   a.name AS assessment, o.offering_id, c.code, o.academic_year, o.section
            FROM unlock_request r
            JOIN assessment a      ON a.assessment_id = r.assessment_id
            JOIN course_offering o ON o.offering_id = a.offering_id
            JOIN course c          ON c.course_id = o.course_id
            WHERE %s::text IS NULL OR r.status = %s
            ORDER BY r.requested_at DESC""", (status, status)).fetchall()


class Decision(BaseModel):
    approve: bool


@router.post("/unlock-requests/{request_id}/decision")
def decide(request_id: int, body: Decision, user: User = Depends(require("admin")), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        cur = conn.execute(
            "UPDATE unlock_request SET status = %s, decided_by = %s, decided_at = now() "
            "WHERE request_id = %s AND status = 'pending'",
            ("approved" if body.approve else "rejected", user.user_id, request_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "No pending request with that id")
    return {"request_id": request_id, "status": "approved" if body.approve else "rejected"}


@router.get("/configs")
def configs(user: User = Depends(require("admin", "coordinator", "faculty")), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        return conn.execute("""
            SELECT c.*, (SELECT json_object_agg(component, weight_pct) FROM config_component_weight w
                         WHERE w.config_id = c.config_id) AS component_weights,
                   (SELECT count(*) FROM co_attainment ca WHERE ca.config_id = c.config_id) AS results_using
            FROM attainment_config c ORDER BY c.valid_from DESC""").fetchall()


class ConfigIn(BaseModel):
    program_id: int = 1
    valid_from: date
    target_pct: float = Field(ge=0, le=100)
    l3_pct: float = Field(ge=0, le=100)
    l2_pct: float = Field(ge=0, le=100)
    l1_pct: float = Field(ge=0, le=100)
    direct_weight: float = Field(ge=0, le=100)
    indirect_weight: float = Field(ge=0, le=100)
    co_target_level: float = Field(ge=0, le=3)
    po_target_level: float = Field(ge=0, le=3)
    component_weights: dict[str, float]

    @model_validator(mode="after")
    def sums(self):
        if self.direct_weight + self.indirect_weight != 100:
            raise ValueError("Direct and indirect weights must add up to 100")
        if round(sum(self.component_weights.values()), 2) != 100:
            raise ValueError("Component weights must add up to 100")
        if not self.l3_pct >= self.l2_pct >= self.l1_pct:
            raise ValueError("Thresholds must satisfy level 3 >= level 2 >= level 1")
        return self


@router.post("/configs", status_code=201)
def new_config(body: ConfigIn, user: User = Depends(require("admin")), dbname=Depends(database)):
    """Start a new rule version: the open version ends where this one begins."""
    with db.session(user, dbname) as conn:
        conn.execute("UPDATE attainment_config SET valid_to = %s WHERE program_id = %s AND valid_to IS NULL "
                     "AND valid_from < %s", (body.valid_from, body.program_id, body.valid_from))
        cid = conn.execute("""
            INSERT INTO attainment_config (program_id, target_pct, l3_pct, l2_pct, l1_pct, direct_weight,
                indirect_weight, co_target_level, po_target_level, valid_from)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING config_id""",
            (body.program_id, body.target_pct, body.l3_pct, body.l2_pct, body.l1_pct, body.direct_weight,
             body.indirect_weight, body.co_target_level, body.po_target_level, body.valid_from)).fetchone()["config_id"]
        for comp, w in body.component_weights.items():
            conn.execute("INSERT INTO config_component_weight VALUES (%s, %s, %s)", (cid, comp, w))
    return {"config_id": cid}


@router.get("/audit/verify")
def verify_audit(request: Request, user: User = Depends(require("admin", "coordinator")), dbname=Depends(database)):
    mongo = get_db(getattr(request.app.state, "mongo_name", None))
    with db.session(user, dbname) as conn:
        result = audit.verify(conn, mongo)
        anchors = conn.execute("SELECT seq, head_hash, anchored_at FROM audit_anchor ORDER BY seq DESC LIMIT 5").fetchall()
        pending = conn.execute("SELECT count(*) AS n FROM audit_outbox WHERE sent_at IS NULL").fetchone()["n"] \
            if user.role == "admin" else None
    seq, head_hash = audit.head(mongo)
    return {**result, "head": {"seq": seq, "hash": head_hash}, "anchors": anchors, "pending_outbox": pending}
