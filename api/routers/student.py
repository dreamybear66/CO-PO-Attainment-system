"""Student view: own CO-wise scores and course-exit surveys."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api import db
from api.auth import database, require
from api.db import User
from api.mongo import get_db
from api.services.surveys import SurveyError, respondent_hash, submit_survey

router = APIRouter(prefix="/api/me")
student = require("student")


@router.get("/scores")
def my_scores(user: User = Depends(student), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        return conn.execute("""
            SELECT o.offering_id, c.code, c.title, o.academic_year, o.term, co.co_id, co.co_number,
                   co.statement, round(s.pct, 1) AS pct, cfg.target_pct
            FROM student_co_score s
            JOIN course_offering o     ON o.offering_id = s.offering_id
            JOIN course c              ON c.course_id = o.course_id
            JOIN course_outcome co     ON co.co_id = s.co_id
            JOIN v_offering_config oc  ON oc.offering_id = s.offering_id
            JOIN attainment_config cfg ON cfg.config_id = oc.config_id
            WHERE s.usn = %s
            ORDER BY o.academic_year DESC, o.term DESC, c.code, co.co_number""", (user.usn,)).fetchall()


@router.get("/surveys")
def my_surveys(request: Request, user: User = Depends(student), dbname=Depends(database)):
    """Offerings whose assessments are all locked, with whether the survey is answered."""
    mongo = get_db(getattr(request.app.state, "mongo_name", None))
    with db.session(user, dbname) as conn:
        rows = conn.execute("""
            SELECT o.offering_id, c.code, c.title, o.academic_year, o.term,
                   (SELECT json_agg(json_build_object('co_id', co.co_id, 'co_number', co.co_number,
                                                      'statement', co.statement) ORDER BY co.co_number)
                    FROM course_outcome co WHERE co.course_id = c.course_id) AS cos
            FROM enrollment e
            JOIN course_offering o ON o.offering_id = e.offering_id
            JOIN course c          ON c.course_id = o.course_id
            WHERE e.usn = %s
              AND EXISTS (SELECT 1 FROM assessment a WHERE a.offering_id = o.offering_id)
              AND NOT EXISTS (SELECT 1 FROM assessment a WHERE a.offering_id = o.offering_id AND NOT a.locked)
            ORDER BY o.academic_year DESC, o.term DESC, c.code""", (user.usn,)).fetchall()
    for r in rows:
        r["answered"] = mongo.survey_responses.count_documents(
            {"respondent_hash": respondent_hash(user.usn, r["offering_id"], "course_exit")}, limit=1) > 0
    return rows


class Answer(BaseModel):
    co_id: int
    rating: int = Field(ge=1, le=5)


class SurveyIn(BaseModel):
    offering_id: int
    answers: list[Answer]


@router.post("/surveys", status_code=201)
def answer_survey(body: SurveyIn, request: Request, user: User = Depends(student), dbname=Depends(database)):
    mongo = get_db(getattr(request.app.state, "mongo_name", None))
    with db.session(user, dbname) as conn:
        try:
            doc_id = submit_survey(conn, mongo, usn=user.usn, offering_id=body.offering_id,
                                   survey_type="course_exit", answers=[a.model_dump() for a in body.answers])
        except SurveyError as exc:
            raise HTTPException(422, str(exc)) from None
    return {"id": doc_id}
