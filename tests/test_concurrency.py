"""PRD Section 8 'Concurrency' (NFR-3) and NFR-2 atomicity."""

from decimal import Decimal as D

import psycopg
import pytest

from tests.conftest import raises_sqlstate


def test_second_run_waits_or_is_refused(db, connect):
    first = connect(autocommit=False)
    first.execute("CALL sp_compute_attainment(1)")          # holds the offering row lock

    second = connect()
    second.execute("SET lock_timeout = '500ms'")
    with raises_sqlstate("55P03"):                          # lock_not_available: refused
        second.execute("CALL sp_compute_attainment(1)")

    first.commit()
    second.execute("CALL sp_compute_attainment(1)")         # proceeds once the first commits
    assert db.execute("SELECT count(*) FROM co_attainment WHERE offering_id = 1").fetchone()[0] == 3


def test_failed_run_leaves_previous_results(db):
    db.execute("CALL sp_compute_attainment(1)")
    before = db.execute("SELECT co_id, final_level, computed_at FROM co_attainment ORDER BY co_id").fetchall()

    db.execute("INSERT INTO course_outcome (course_id, co_number, statement, bloom_level) VALUES (1, 4, 'untested', 2)")
    with pytest.raises(psycopg.Error):
        db.execute("CALL sp_compute_attainment(1)")

    after = db.execute("SELECT co_id, final_level, computed_at FROM co_attainment ORDER BY co_id").fetchall()
    assert after == before
    assert [r[1] for r in after] == [D("3.00"), D("2.20"), D("0.40")]


@pytest.fixture
def quiz(db):
    """An unlocked quiz on the worked-example offering with every mark entered, ready to lock."""
    db.execute("""
        INSERT INTO assessment (assessment_id, offering_id, type, name, max_marks) VALUES (2, 1, 'CIE_QUIZ', 'Quiz 1', 10);
        INSERT INTO assessment_question (question_id, assessment_id, q_no, max_marks) VALUES (21, 2, 'Q1', 10);
        INSERT INTO question_co_map (question_id, co_id, weight) VALUES (21, 1, 1);
        INSERT INTO student_question_mark SELECT i, 21, 5, false FROM generate_series(1, 60) i;
    """)
    return db


def test_lock_waits_for_an_uncommitted_mark_edit(quiz, connect):
    editor = connect(autocommit=False)
    editor.execute("UPDATE student_question_mark SET marks_obtained = 9 WHERE enrollment_id = 1 AND question_id = 21")
    locker = connect()
    locker.execute("SET lock_timeout = '500ms'")
    with raises_sqlstate("55P03"):                          # waits instead of locking under the edit
        locker.execute("UPDATE assessment SET locked = true WHERE assessment_id = 2")
    editor.commit()
    locker.execute("UPDATE assessment SET locked = true WHERE assessment_id = 2")
    assert quiz.execute("SELECT marks_obtained FROM student_question_mark "
                        "WHERE enrollment_id = 1 AND question_id = 21").fetchone()[0] == 9


def test_lock_after_a_concurrent_mark_delete_sees_the_gap(quiz, connect):
    editor = connect(autocommit=False)
    editor.execute("DELETE FROM student_question_mark WHERE enrollment_id = 1 AND question_id = 21")
    locker = connect()
    locker.execute("SET lock_timeout = '500ms'")
    with raises_sqlstate("55P03"):
        locker.execute("UPDATE assessment SET locked = true WHERE assessment_id = 2")
    editor.commit()
    with raises_sqlstate("CP006"):                          # 59 of 60 marks
        locker.execute("UPDATE assessment SET locked = true WHERE assessment_id = 2")


def test_unlock_waits_for_a_running_compute(db, connect):
    db.execute("""
        INSERT INTO app_user (user_id, username, password_hash, role, faculty_id) VALUES
            (1, 'fac', 'x', 'faculty', 1), (2, 'hod', 'x', 'admin', NULL);
        INSERT INTO unlock_request (assessment_id, requested_by, reason, status, decided_by, decided_at)
        VALUES (1, 1, 'Q3 marks of two students were swapped', 'approved', 2, now());
    """)
    compute = connect(autocommit=False)
    compute.execute("CALL sp_compute_attainment(1)")
    unlocker = connect()
    unlocker.execute("SET lock_timeout = '500ms'")
    with raises_sqlstate("55P03"):                          # cannot unlock under a running compute
        unlocker.execute("UPDATE assessment SET locked = false WHERE assessment_id = 1")
    compute.commit()
    unlocker.execute("UPDATE assessment SET locked = false WHERE assessment_id = 1")


def test_compute_does_not_block_inserts_that_reference_the_offering(db, connect):
    compute = connect(autocommit=False)
    compute.execute("CALL sp_compute_attainment(1, p_refresh => false)")
    other = connect()
    other.execute("SET lock_timeout = '500ms'")
    other.execute("INSERT INTO improvement_action (co_id, offering_id, description, owner) VALUES (1, 1, 'note', 1)")
    other.execute("INSERT INTO assessment (offering_id, type, name, max_marks) VALUES (1, 'EL', 'EL', 40)")
    compute.commit()


def test_refused_caller_does_not_queue_for_the_lock(db, api_connect, connect):
    running = connect(autocommit=False)
    running.execute("CALL sp_compute_attainment(1)")                    # holds the offering's lock
    intruder = api_connect("faculty", faculty_id=2)                     # does not teach offering 1
    intruder.execute("SET lock_timeout = '500ms'")
    with raises_sqlstate("42501"):                                      # refused at once, not 55P03
        intruder.execute("CALL sp_compute_attainment(1)")
    running.commit()


def test_dashboards_stay_readable_during_a_compute(db, connect):
    compute = connect(autocommit=False)
    compute.execute("CALL sp_compute_attainment(1)")                  # refreshes the views
    reader = connect()
    reader.execute("SET lock_timeout = '500ms'")
    assert reader.execute("SELECT count(*) FROM mv_co_po_heatmap").fetchone()[0] == 0   # old contents
    compute.commit()
    assert reader.execute("SELECT count(*) FROM mv_co_po_heatmap").fetchone()[0] == 5
