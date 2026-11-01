"""Survey submission checks (FR-5.1) and the survey ETL into indirect_attainment (FR-5.2)."""

from decimal import Decimal as D

import pytest

from api.jobs.etl import run_survey_etl
from api.services.surveys import SurveyError, submit_survey


def answer(usn, ratings, db, mongo):
    return submit_survey(db, mongo, usn=usn, offering_id=1, survey_type="course_exit",
                         answers=[{"co_id": co, "rating": r} for co, r in ratings.items()])


def usn(i):
    return f"1RV25WX{i:03d}"


def test_etl_computes_pct_and_level(db, mongo):
    db.execute("DELETE FROM indirect_attainment")
    # 10 respondents: CO1 8 favourable (80% -> 3), CO2 6 (60% -> 2), CO3 4 (40% -> 0)
    for i in range(1, 11):
        answer(usn(i), {1: 5 if i <= 8 else 2, 2: 4 if i <= 6 else 3, 3: 4 if i <= 4 else 1}, db, mongo)
    result = run_survey_etl(db, mongo)
    assert result == {"groups": 3, "loaded": 3, "skipped": 0}
    rows = db.execute("SELECT co_id, respondents, pct_favourable, level FROM indirect_attainment ORDER BY co_id").fetchall()
    assert rows == [(1, 10, D("80.00"), 3), (2, 10, D("60.00"), 2), (3, 10, D("40.00"), 0)]


def test_etl_is_idempotent_and_feeds_the_engine(db, mongo):
    for i in range(1, 6):
        answer(usn(i), {1: 5, 2: 5, 3: 2}, db, mongo)
    run_survey_etl(db, mongo)
    run_survey_etl(db, mongo)
    assert db.execute("SELECT count(*) FROM indirect_attainment").fetchone()[0] == 3
    db.execute("CALL sp_compute_attainment(1)")
    # CO3: direct 0, indirect 0 (0% favourable) -> 0.00
    assert db.execute("SELECT indirect_level, final_level FROM co_attainment WHERE co_id = 3").fetchone() == (0, D("0.00"))


def test_rejects_student_not_enrolled(db, mongo):
    with pytest.raises(SurveyError, match="not enrolled"):
        answer("1RV99XX999", {1: 4}, db, mongo)


def test_rejects_co_of_another_course(db, mongo):
    db.execute("INSERT INTO course VALUES (2, 'WX201', 'Other', 3, 5, 1); "
               "INSERT INTO course_outcome VALUES (10, 2, 1, 'other', 2)")
    with pytest.raises(SurveyError, match="do not belong"):
        answer(usn(1), {10: 4}, db, mongo)


def test_rejects_out_of_range_rating(db, mongo):
    with pytest.raises(SurveyError, match="1 to 5"):
        answer(usn(1), {1: 6}, db, mongo)


def test_one_response_per_student(db, mongo):
    answer(usn(1), {1: 4}, db, mongo)
    with pytest.raises(SurveyError, match="already answered"):
        answer(usn(1), {1: 5}, db, mongo)


def test_respondent_is_stored_as_hash(db, mongo):
    answer(usn(1), {1: 4}, db, mongo)
    doc = mongo.survey_responses.find_one()
    assert usn(1) not in str(doc) and len(doc["respondent_hash"]) == 64
