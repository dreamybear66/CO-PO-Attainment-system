"""Course-exit survey submission (PRD FR-5.1).

MongoDB has no foreign keys, so every reference is checked against PostgreSQL before insert:
the offering exists, the student is enrolled in it, and every rated CO belongs to its course.
Respondents are stored as a hash, never by USN.
"""

import hashlib
from datetime import datetime, timezone

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

SURVEY_TYPES = {"course_exit"}


class SurveyError(ValueError):
    pass


def respondent_hash(usn: str, offering_id: int, survey_type: str) -> str:
    return hashlib.sha256(f"{usn}:{offering_id}:{survey_type}".encode()).hexdigest()


def submit_survey(pg, mongo: Database, *, usn: str, offering_id: int, survey_type: str,
                  answers: list[dict]) -> str:
    """Validate and store one response. `pg` is an open psycopg connection."""
    if survey_type not in SURVEY_TYPES:
        raise SurveyError(f"Unknown survey type {survey_type!r}")
    enrolled = pg.execute(
        "SELECT 1 FROM enrollment WHERE offering_id = %s AND usn = %s", (offering_id, usn)
    ).fetchone()
    if not enrolled:
        raise SurveyError(f"{usn} is not enrolled in offering {offering_id}")

    course_cos = {r[0] for r in pg.execute(
        "SELECT co.co_id FROM course_outcome co JOIN course_offering o ON o.course_id = co.course_id "
        "WHERE o.offering_id = %s", (offering_id,))}
    rated = [a["co_id"] for a in answers]
    if not answers or len(set(rated)) != len(rated):
        raise SurveyError("Answers must rate each CO once")
    unknown = set(rated) - course_cos
    if unknown:
        raise SurveyError(f"CO(s) {sorted(unknown)} do not belong to offering {offering_id}")
    for a in answers:
        if not isinstance(a.get("rating"), int) or not 1 <= a["rating"] <= 5:
            raise SurveyError("Ratings must be whole numbers from 1 to 5")

    doc = {
        "survey_type": survey_type,
        "offering_id": offering_id,
        "respondent_hash": respondent_hash(usn, offering_id, survey_type),
        "submitted_at": datetime.now(timezone.utc),
        "answers": [{"co_id": a["co_id"], "rating": a["rating"]} for a in answers],
    }
    try:
        return str(mongo.survey_responses.insert_one(doc).inserted_id)
    except DuplicateKeyError:
        raise SurveyError("This student has already answered this survey") from None
