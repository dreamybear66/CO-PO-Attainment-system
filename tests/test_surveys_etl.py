"""Survey submission checks (FR-5.1) and the survey ETL into indirect_attainment (FR-5.2)."""

import hashlib
from decimal import Decimal as D

import pytest
from psycopg.rows import dict_row

from api.jobs.etl import run_survey_etl
from api.services.surveys import SurveyError, submit_survey
from api.survey_hash import respondent_hash

ALL = {1: 4, 2: 4, 3: 4}


def answer(usn, ratings, db, mongo, offering_id=1):
    return submit(db, mongo, usn, [{"co_id": co, "rating": r} for co, r in ratings.items()], offering_id)


def submit(db, mongo, usn, answers, offering_id=1):
    return submit_survey(db, mongo, usn=usn, offering_id=offering_id, survey_type="course_exit", answers=answers)


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
        answer("1RV99XX999", ALL, db, mongo)


def test_rejects_co_of_another_course(db, mongo):
    db.execute("INSERT INTO course VALUES (2, 'WX201', 'Other', 3, 5, 1); "
               "INSERT INTO course_outcome VALUES (10, 2, 1, 'other', 2)")
    with pytest.raises(SurveyError, match="do not belong"):
        answer(usn(1), {**ALL, 10: 4}, db, mongo)


def test_rejects_out_of_range_rating(db, mongo):
    with pytest.raises(SurveyError, match="1 to 5"):
        answer(usn(1), {**ALL, 1: 6}, db, mongo)


def test_one_response_per_student(db, mongo):
    answer(usn(1), ALL, db, mongo)
    with pytest.raises(SurveyError, match="already answered"):
        answer(usn(1), {**ALL, 1: 5}, db, mongo)


def test_respondent_is_stored_as_a_keyed_hash(db, mongo):
    answer(usn(1), ALL, db, mongo)
    doc = mongo.survey_responses.find_one()
    assert usn(1) not in str(doc)
    assert doc["respondent_hash"] == respondent_hash(usn(1), 1, "course_exit")
    # not the plain hash anyone could recompute from the USN
    assert doc["respondent_hash"] != hashlib.sha256(f"{usn(1)}:1:course_exit".encode()).hexdigest()


@pytest.mark.parametrize("answers", [
    [{"co_id": 1, "rating": True}, {"co_id": 2, "rating": 4}, {"co_id": 3, "rating": 4}],
    [{"co_id": 1, "rating": 4.0}, {"co_id": 2, "rating": 4}, {"co_id": 3, "rating": 4}],
    [{"co_id": True, "rating": 4}, {"co_id": 2, "rating": 4}, {"co_id": 3, "rating": 4}],
    [{"co_id": "1", "rating": 4}, {"co_id": 2, "rating": 4}, {"co_id": 3, "rating": 4}],
    [{"rating": 4}, {"co_id": 2, "rating": 4}, {"co_id": 3, "rating": 4}],
    [{"co_id": 1, "rating": 4, "usn": "x"}, {"co_id": 2, "rating": 4}, {"co_id": 3, "rating": 4}],
    ["CO1: 4"],
    [],
])
def test_rejects_malformed_answers(db, mongo, answers):
    with pytest.raises(SurveyError):
        submit(db, mongo, usn(1), answers)
    assert mongo.survey_responses.count_documents({}) == 0


def test_rejects_malformed_offering_id(db, mongo):
    with pytest.raises(SurveyError, match="whole number"):
        submit(db, mongo, usn(1), [{"co_id": co, "rating": 4} for co in ALL], offering_id="1")


def test_rejects_a_partial_survey(db, mongo):
    with pytest.raises(SurveyError, match="missing CO2, CO3"):
        answer(usn(1), {1: 5}, db, mongo)


def test_rejects_a_survey_before_the_offering_is_finished(db, mongo):
    db.execute("INSERT INTO assessment (offering_id, type, name, max_marks) VALUES (1, 'CIE_QUIZ', 'Quiz 1', 10)")
    with pytest.raises(SurveyError, match="still running"):
        answer(usn(1), ALL, db, mongo)


def test_works_on_dict_row_connections(db, mongo, connect):
    conn = connect()
    conn.row_factory = dict_row
    answer(usn(1), ALL, conn, mongo)
    assert mongo.survey_responses.count_documents({}) == 1
