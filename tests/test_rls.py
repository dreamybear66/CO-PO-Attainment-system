"""PRD Section 8 'Access control' (NFR-5): roles and row-level security, checked as the API connects."""

import psycopg
import pytest

from api import db as api_db
from api.db import User
from tests.conftest import TEST_DB, raises_sqlstate

FAC_A = User(1, "fac_a", "faculty", faculty_id=1)
FAC_B = User(2, "fac_b", "faculty", faculty_id=2)
COORD = User(3, "coord", "coordinator")
ADMIN = User(4, "hod", "admin", faculty_id=None)
STUDENT = User(5, "1rv25wx001", "student", usn="1RV25WX001")


@pytest.fixture
def two_faculty(db):
    """Offering 1 (worked example) is taught by faculty 1; offering 2 by faculty 2."""
    db.execute("""
        INSERT INTO faculty VALUES (2, 1, 'Faculty B', 'b@example.edu');
        INSERT INTO course_offering VALUES (2, 1, '2025-26', 'even', 2, 'B');
        INSERT INTO enrollment VALUES (200, 2, '1RV25WX002');
        INSERT INTO assessment (assessment_id, offering_id, type, name, max_marks) VALUES (20, 2, 'SEE', 'SEE', 10);
        INSERT INTO assessment_question VALUES (201, 20, 'Q1', 10);
        INSERT INTO question_co_map VALUES (201, 1, 1);
        INSERT INTO student_question_mark VALUES (200, 201, 7, false);
    """)
    yield db
    api_db.close_pools()


def run(user, sql, params=None):
    with api_db.session(user, TEST_DB) as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else []


def test_faculty_sees_no_rows_of_another_faculty(two_faculty):
    assert run(FAC_B, "SELECT * FROM student_question_mark sqm JOIN enrollment e USING (enrollment_id) "
                      "WHERE e.offering_id = 1") == []
    assert len(run(FAC_A, "SELECT * FROM student_question_mark sqm JOIN enrollment e USING (enrollment_id) "
                          "WHERE e.offering_id = 1")) == 180


def test_faculty_sees_only_own_results(two_faculty):
    two_faculty.execute("CALL sp_compute_attainment(1)")
    assert run(FAC_B, "SELECT * FROM co_attainment") == []
    assert len(run(FAC_A, "SELECT * FROM co_attainment")) == 3


def test_faculty_cannot_write_another_offering(two_faculty):
    with raises_sqlstate("42501"):
        run(FAC_B, "INSERT INTO assessment (offering_id, type, name, max_marks) VALUES (1, 'EL', 'EL', 40)")


def test_faculty_cannot_compute_another_offering(two_faculty):
    with raises_sqlstate("42501"):
        run(FAC_B, "CALL sp_compute_attainment(1)")
    run(FAC_A, "CALL sp_compute_attainment(1)")


def test_coordinator_reads_everything_but_writes_nothing(two_faculty):
    assert len(run(COORD, "SELECT * FROM student_question_mark")) == 181
    with raises_sqlstate("42501"):
        run(COORD, "UPDATE improvement_action SET status = 'done'")
    with raises_sqlstate("42501"):
        run(COORD, "CALL sp_compute_attainment(1)")


def test_student_sees_only_own_marks_and_scores(two_faculty):
    assert len(run(STUDENT, "SELECT * FROM student_question_mark")) == 3
    scores = run(STUDENT, "SELECT DISTINCT usn FROM student_co_score")
    assert scores == [{"usn": "1RV25WX001"}]
    assert run(STUDENT, "SELECT usn FROM student") == [{"usn": "1RV25WX001"}]


def test_password_hashes_are_not_readable(two_faculty):
    for user in (FAC_A, COORD, STUDENT, ADMIN):
        if user is ADMIN:
            continue
        with raises_sqlstate("42501"):
            run(user, "SELECT password_hash FROM app_user")


def test_materialized_views_are_hidden_from_faculty(two_faculty):
    with raises_sqlstate("42501"):
        run(FAC_A, "SELECT * FROM mv_co_po_heatmap")
    run(COORD, "SELECT * FROM mv_co_po_heatmap")


def test_api_login_alone_reads_nothing(two_faculty):
    with api_db.anonymous(TEST_DB) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM student_question_mark")
        conn.rollback()
