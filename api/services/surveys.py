"""Course-exit survey submission (PRD FR-5.1).

MongoDB has no foreign keys, so every reference is checked against PostgreSQL before insert: the
student is enrolled in the offering, the offering is finished (all its assessments locked), and
the answers rate every CO of its course exactly once, each with a whole number from 1 to 5.
Respondents are stored as a keyed hash (api.survey_hash, shared with datagen), never by USN.
Queries use a tuple-row cursor, so callers may pass connections with any row factory.
"""

from datetime import datetime, timezone

from psycopg.rows import tuple_row
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from api.survey_hash import respondent_hash

SURVEY_TYPES = {"course_exit"}


class SurveyError(ValueError):
    pass


def finished_sql(offering: str) -> str:
    """SQL condition: the offering (a column or parameter expression) has assessments and all are
    locked. Surveys open only then; GET /api/me/surveys lists offerings by the same rule."""
    return (f"(EXISTS (SELECT 1 FROM assessment a WHERE a.offering_id = {offering}) AND NOT EXISTS "
            f"(SELECT 1 FROM assessment a WHERE a.offering_id = {offering} AND NOT a.locked))")


def _whole(value) -> bool:
    return type(value) is int       # bool is a subclass of int, but True is not a rating or an id


def _check_answers(answers, course_cos: dict[int, int], offering_id: int) -> None:
    """course_cos maps co_id -> CO number for the offering's course."""
    if not isinstance(answers, list) or not answers:
        raise SurveyError("Answers must rate each CO of the course once")
    for a in answers:
        if not isinstance(a, dict) or set(a) != {"co_id", "rating"} or not _whole(a["co_id"]):
            raise SurveyError("Each answer needs a whole-number co_id and a rating")
        if not _whole(a["rating"]) or not 1 <= a["rating"] <= 5:
            raise SurveyError("Ratings must be whole numbers from 1 to 5")
    rated = [a["co_id"] for a in answers]
    if len(set(rated)) != len(rated):
        raise SurveyError("Each CO may be rated only once")
    unknown = set(rated) - course_cos.keys()
    if unknown:
        raise SurveyError(f"CO(s) {sorted(unknown)} do not belong to offering {offering_id}")
    missing = sorted(course_cos[co] for co in course_cos.keys() - set(rated))
    if missing:
        raise SurveyError("Rate every CO of the course; missing " + ", ".join(f"CO{n}" for n in missing))


def submit_survey(pg, mongo: Database, *, usn: str, offering_id: int, survey_type: str,
                  answers: list[dict]) -> str:
    """Validate and store one response. `pg` is an open psycopg connection."""
    if survey_type not in SURVEY_TYPES:
        raise SurveyError(f"Unknown survey type {survey_type!r}")
    if not _whole(offering_id):
        raise SurveyError("offering_id must be a whole number")
    cur = pg.cursor(row_factory=tuple_row)
    if not cur.execute("SELECT 1 FROM enrollment WHERE offering_id = %s AND usn = %s",
                       (offering_id, usn)).fetchone():
        raise SurveyError(f"{usn} is not enrolled in offering {offering_id}")
    if not cur.execute(f"SELECT {finished_sql('%s')}", (offering_id, offering_id)).fetchone()[0]:
        raise SurveyError(f"Offering {offering_id} is still running; its survey opens once every "
                          "assessment is locked")
    course_cos = dict(cur.execute(
        "SELECT co.co_id, co.co_number FROM course_outcome co "
        "JOIN course_offering o ON o.course_id = co.course_id WHERE o.offering_id = %s",
        (offering_id,)).fetchall())
    _check_answers(answers, course_cos, offering_id)

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
