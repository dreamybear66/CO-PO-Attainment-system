"""PRD Section 8 'Constraints' (NFR-1): invalid data is rejected inside the database."""

import psycopg
import pytest

from tests.conftest import raises_sqlstate


@pytest.fixture
def open_assessment(db):
    """An unlocked quiz on the worked-example offering with one question tagged to CO1."""
    db.execute("""
        INSERT INTO assessment (assessment_id, offering_id, type, name, max_marks) VALUES (2, 1, 'CIE_QUIZ', 'Quiz 1', 10);
        INSERT INTO assessment_question (question_id, assessment_id, q_no, max_marks) VALUES (21, 2, 'Q1', 10);
        INSERT INTO question_co_map (question_id, co_id, weight) VALUES (21, 1, 1);
    """)
    return db


# ---------------------------------------------------------------- marks

def test_marks_above_maximum(open_assessment):
    with raises_sqlstate("CP002"):
        open_assessment.execute("INSERT INTO student_question_mark VALUES (1, 21, 11, false)")


def test_negative_marks(open_assessment):
    with raises_sqlstate("CP002"):     # mark_guard fires before the CHECK constraint
        open_assessment.execute("INSERT INTO student_question_mark VALUES (1, 21, -1, false)")


def test_mark_for_enrollment_of_another_offering(open_assessment):
    open_assessment.execute("""
        INSERT INTO course_offering VALUES (2, 1, '2025-26', 'even', 1, 'B');
        INSERT INTO enrollment VALUES (500, 2, '1RV25WX001');
    """)
    with raises_sqlstate("CP003"):
        open_assessment.execute("INSERT INTO student_question_mark VALUES (500, 21, 5, false)")


def test_edit_after_lock(db):
    with raises_sqlstate("CP001"):
        db.execute("UPDATE student_question_mark SET marks_obtained = 9 WHERE enrollment_id = 1 AND question_id = 1")


def test_delete_after_lock(db):
    with raises_sqlstate("CP001"):
        db.execute("DELETE FROM student_question_mark WHERE enrollment_id = 1 AND question_id = 1")


def test_late_enrollment_into_locked_offering(db):
    db.execute("INSERT INTO student (usn, name, program_id, admission_year, section) VALUES ('1RV25WX099', 'Late', 1, 2025, 'A')")
    with raises_sqlstate("CP001"):     # the student could never get marks in the locked SEE
        db.execute("INSERT INTO enrollment VALUES (99, 1, '1RV25WX099')")


def test_move_enrollment_into_locked_offering(db):
    db.execute("""
        INSERT INTO course_offering VALUES (2, 1, '2025-26', 'even', 1, 'B');
        INSERT INTO student (usn, name, program_id, admission_year, section) VALUES ('1RV25WX099', 'Late', 1, 2025, 'B');
        INSERT INTO enrollment VALUES (99, 2, '1RV25WX099');
    """)
    with raises_sqlstate("CP001"):
        db.execute("UPDATE enrollment SET offering_id = 1 WHERE enrollment_id = 99")


def test_question_changes_after_lock(db):
    with raises_sqlstate("CP001"):
        db.execute("UPDATE assessment_question SET max_marks = 20 WHERE question_id = 1")
    with raises_sqlstate("CP001"):
        db.execute("UPDATE question_co_map SET co_id = 2 WHERE question_id = 1")


def test_locked_assessment_cannot_be_edited_or_deleted(db):
    with raises_sqlstate("CP001"):
        db.execute("UPDATE assessment SET max_marks = 40 WHERE assessment_id = 1")
    with raises_sqlstate("CP001"):
        db.execute("DELETE FROM assessment WHERE assessment_id = 1")


# ---------------------------------------------------------------- enrolment and mappings

def test_duplicate_enrollment(db):
    db.execute("INSERT INTO course_offering VALUES (2, 1, '2025-26', 'even', 1, 'B')")   # no locked assessment
    db.execute("INSERT INTO enrollment (offering_id, usn) VALUES (2, '1RV25WX001')")
    with raises_sqlstate("23505"):
        db.execute("INSERT INTO enrollment (offering_id, usn) VALUES (2, '1RV25WX001')")


def test_invalid_strength(db):
    with raises_sqlstate("23514"):
        db.execute("UPDATE co_po_map SET strength = 4 WHERE co_id = 1 AND po_id = 1")


def test_question_weights_must_sum_to_one(open_assessment):
    with raises_sqlstate("CP004"):
        with open_assessment.transaction():
            open_assessment.execute("UPDATE question_co_map SET weight = 0.5 WHERE question_id = 21")


def test_question_weights_split_across_cos(open_assessment):
    with open_assessment.transaction():
        open_assessment.execute("UPDATE question_co_map SET weight = 0.5 WHERE question_id = 21")
        open_assessment.execute("INSERT INTO question_co_map VALUES (21, 2, 0.5)")
    assert open_assessment.execute("SELECT sum(weight) FROM question_co_map WHERE question_id = 21").fetchone()[0] == 1


def test_question_weights_in_equal_thirds(open_assessment):
    with open_assessment.transaction():   # 3 x 0.333 = 0.999, within the 0.001 tolerance
        open_assessment.execute("UPDATE question_co_map SET weight = 0.333 WHERE question_id = 21")
        open_assessment.execute("INSERT INTO question_co_map VALUES (21, 2, 0.333), (21, 3, 0.333)")


def test_moving_a_co_tag_rechecks_the_question_it_left(open_assessment):
    with open_assessment.transaction():
        open_assessment.execute("""
            UPDATE question_co_map SET weight = 0.5 WHERE question_id = 21;
            INSERT INTO question_co_map VALUES (21, 2, 0.5);
            INSERT INTO assessment_question (question_id, assessment_id, q_no, max_marks) VALUES (22, 2, 'Q2', 10);
            INSERT INTO question_co_map VALUES (22, 1, 0.5), (22, 3, 0.5);
        """)
    with raises_sqlstate("CP004"):        # question 21 would be left with weights summing to 0.5
        with open_assessment.transaction():
            open_assessment.execute("DELETE FROM question_co_map WHERE question_id = 22 AND co_id = 3")
            open_assessment.execute("UPDATE question_co_map SET question_id = 22 WHERE question_id = 21 AND co_id = 2")


def test_component_weights_must_sum_to_100(db):
    with raises_sqlstate("CP004"):
        with db.transaction():
            db.execute("UPDATE config_component_weight SET weight_pct = 40 WHERE config_id = 1 AND component = 'SEE'")


def test_question_tagged_with_co_of_another_course(open_assessment):
    open_assessment.execute("""
        INSERT INTO course VALUES (2, 'WX201', 'Other', 3, 5, 1);
        INSERT INTO course_outcome VALUES (10, 2, 1, 'other course CO', 2);
    """)
    with raises_sqlstate("CP003"):
        with open_assessment.transaction():
            open_assessment.execute("UPDATE question_co_map SET co_id = 10 WHERE question_id = 21")


# ---------------------------------------------------------------- prerequisites and dependencies

@pytest.fixture
def two_courses(db):
    """Course 2 has course 1 as prerequisite."""
    db.execute("""
        INSERT INTO course VALUES (2, 'WX201', 'Follow-on', 3, 5, 1);
        INSERT INTO course_prerequisite VALUES (2, 1);
        INSERT INTO course_outcome VALUES (10, 2, 1, 'follow-on CO1', 3);
    """)
    return db


def test_dependency_on_prerequisite_course_is_allowed(two_courses):
    two_courses.execute("INSERT INTO co_dependency VALUES (10, 1, 3)")


def test_dependency_outside_prerequisite_graph(two_courses):
    with raises_sqlstate("CP005"):
        two_courses.execute("INSERT INTO co_dependency VALUES (1, 10, 2)")


def test_prerequisite_cycle(two_courses):
    with raises_sqlstate("CP005"):
        two_courses.execute("INSERT INTO course_prerequisite VALUES (1, 2)")


def test_co_po_map_across_programmes(db):
    db.execute("""
        INSERT INTO program VALUES (2, 1, 'Other programme', 'B.E.');
        INSERT INTO program_outcome VALUES (20, 2, 'PO1', 'PO', 'other');
    """)
    with raises_sqlstate("CP003"):
        db.execute("INSERT INTO co_po_map VALUES (1, 20, 2)")


# ---------------------------------------------------------------- lock and unlock workflow

def test_lock_needs_every_mark(open_assessment):
    open_assessment.execute("INSERT INTO student_question_mark VALUES (1, 21, 5, false)")
    with raises_sqlstate("CP006"):
        open_assessment.execute("UPDATE assessment SET locked = true WHERE assessment_id = 2")


def test_lock_with_every_mark_or_absence(open_assessment):
    open_assessment.execute("""
        INSERT INTO student_question_mark
        SELECT i, 21, CASE WHEN i = 1 THEN NULL ELSE 5 END, i = 1 FROM generate_series(1, 60) i
    """)
    open_assessment.execute("UPDATE assessment SET locked = true WHERE assessment_id = 2")
    assert open_assessment.execute("SELECT locked_at IS NOT NULL FROM assessment WHERE assessment_id = 2").fetchone()[0]


def test_lock_needs_question_maxima_to_match(db):
    db.execute("""
        INSERT INTO assessment (assessment_id, offering_id, type, name, max_marks) VALUES (3, 1, 'EL', 'EL', 40);
        INSERT INTO assessment_question VALUES (31, 3, 'R1', 10);
        INSERT INTO question_co_map VALUES (31, 1, 1);
        INSERT INTO student_question_mark SELECT i, 31, 5, false FROM generate_series(1, 60) i;
    """)
    with raises_sqlstate("CP006"):
        db.execute("UPDATE assessment SET locked = true WHERE assessment_id = 3")


def test_assessment_cannot_be_inserted_locked(db):
    with raises_sqlstate("CP006"):
        db.execute("INSERT INTO assessment (offering_id, type, name, max_marks, locked, locked_at) "
                   "VALUES (1, 'SEE', 'SEE 2', 100, true, now())")


def test_unlock_needs_approved_request(db):
    with raises_sqlstate("CP007"):
        db.execute("UPDATE assessment SET locked = false WHERE assessment_id = 1")


def test_unlock_with_approved_request_uses_it(db):
    db.execute("""
        INSERT INTO app_user (user_id, username, password_hash, role, faculty_id) VALUES
            (1, 'fac', 'x', 'faculty', 1), (2, 'hod', 'x', 'admin', NULL);
        INSERT INTO unlock_request (request_id, assessment_id, requested_by, reason, status, decided_by, decided_at)
        VALUES (1, 1, 1, 'Q3 marks of two students were swapped', 'approved', 2, now());
    """)
    db.execute("UPDATE assessment SET locked = false WHERE assessment_id = 1")
    assert db.execute("SELECT status FROM unlock_request WHERE request_id = 1").fetchone()[0] == "used"
    db.execute("UPDATE student_question_mark SET marks_obtained = 9 WHERE enrollment_id = 1 AND question_id = 1")
    db.execute("UPDATE assessment SET locked = true WHERE assessment_id = 1")
    with raises_sqlstate("CP007"):   # the request was used up
        db.execute("UPDATE assessment SET locked = false WHERE assessment_id = 1")
