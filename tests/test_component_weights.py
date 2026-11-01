"""Component-weighted student CO score (PRD Section 5, steps 1-2; decisions S5, S6).

Weights are shares of the final mark: CIE theory 20, CIE quiz 10, EL 20, SEE 50.
"""

from decimal import Decimal as D

import pytest


@pytest.fixture
def offering2(db):
    """Offering 2 of the worked-example course, two students. CO1 is tested by all four
    components, CO2 by all but the quiz. Student 1 scores 70/80/90/60 %; student 2 is absent
    in the SEE."""
    db.execute("""
        INSERT INTO student (usn, name, program_id, admission_year, section) VALUES
            ('1RV25WX101', 'A', 1, 2025, 'B'), ('1RV25WX102', 'B', 1, 2025, 'B');
        INSERT INTO course_offering (offering_id, course_id, academic_year, term, faculty_id, section)
        VALUES (2, 1, '2025-26', 'even', 1, 'B');
        INSERT INTO enrollment (enrollment_id, offering_id, usn) VALUES (101, 2, '1RV25WX101'), (102, 2, '1RV25WX102');
        INSERT INTO assessment (assessment_id, offering_id, type, name, max_marks) VALUES
            (11, 2, 'CIE_THEORY', 'CIE Test 1', 20), (12, 2, 'CIE_QUIZ', 'Quiz 1', 10),
            (13, 2, 'EL', 'EL', 20), (14, 2, 'SEE', 'SEE', 20);
        INSERT INTO assessment_question (question_id, assessment_id, q_no, max_marks) VALUES
            (111, 11, 'Q1', 10), (112, 11, 'Q2', 10),
            (121, 12, 'Q1', 10),
            (131, 13, 'Q1', 10), (132, 13, 'Q2', 10),
            (141, 14, 'Q1', 10), (142, 14, 'Q2', 10);
        INSERT INTO question_co_map (question_id, co_id, weight) VALUES
            (111, 1, 1), (112, 2, 1), (121, 1, 1), (131, 1, 1), (132, 2, 1), (141, 1, 1), (142, 2, 1);
        INSERT INTO student_question_mark (enrollment_id, question_id, marks_obtained, is_absent) VALUES
            (101, 111, 7, false), (101, 112, 7, false), (101, 121, 8, false),
            (101, 131, 9, false), (101, 132, 9, false), (101, 141, 6, false), (101, 142, 6, false),
            (102, 111, 7, false), (102, 112, 7, false), (102, 121, 8, false),
            (102, 131, 9, false), (102, 132, 9, false), (102, 141, NULL, true), (102, 142, NULL, true);
    """)
    return db


def scores(db, usn):
    return {co: round(pct, 2) for _, co, pct in db.execute(
        "SELECT usn, co_id, pct FROM fn_student_co_score(2, 1) WHERE usn = %s ORDER BY co_id", (usn,))}


def test_all_four_components(offering2):
    # (20 x 70 + 10 x 80 + 20 x 90 + 50 x 60) / 100
    assert scores(offering2, "1RV25WX101")[1] == D("70.00")


def test_component_not_testing_the_co_is_left_out(offering2):
    # (20 x 70 + 20 x 90 + 50 x 60) / 90
    assert scores(offering2, "1RV25WX101")[2] == D("68.89")


def test_absent_counts_as_zero(offering2):
    # (20 x 70 + 10 x 80 + 20 x 90 + 50 x 0) / 100
    assert scores(offering2, "1RV25WX102")[1] == D("40.00")


def test_view_uses_the_offerings_rule_version(offering2):
    row = offering2.execute(
        "SELECT round(pct, 2) FROM student_co_score WHERE offering_id = 2 AND usn = '1RV25WX101' AND co_id = 1"
    ).fetchone()
    assert row == (D("70.00"),)
