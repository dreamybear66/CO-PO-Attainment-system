"""Component-weighted student CO score (PRD Section 5, steps 1-2; decisions S5, S6).

Weights are data in config_component_weight: CIE test 30, CIE quiz 20, SEE 50. Experiential
learning (EL) is one final mark with no CO and never counts towards a CO.
"""

from decimal import Decimal as D

import pytest

from tests.conftest import raises_sqlstate


@pytest.fixture
def offering2(db):
    """Offering 2 of the worked-example course, two students. CO1 is tested by the test, the quiz
    and the SEE, CO2 by the test and the SEE. Student 1 scores 70/80/60 % and 18 of 20 in EL;
    student 2 is absent in the SEE."""
    db.execute("""
        INSERT INTO student (usn, name, program_id, admission_year, section) VALUES
            ('1RV25WX101', 'A', 1, 2025, 'B'), ('1RV25WX102', 'B', 1, 2025, 'B');
        INSERT INTO course_offering (offering_id, course_id, academic_year, term, faculty_id, section)
        VALUES (2, 1, '2025-26', 'even', 1, 'B');
        INSERT INTO enrollment (enrollment_id, offering_id, usn) VALUES (101, 2, '1RV25WX101'), (102, 2, '1RV25WX102');
        INSERT INTO assessment (assessment_id, offering_id, type, name, max_marks, cie_no) VALUES
            (11, 2, 'CIE_THEORY', 'CIE Test 1', 20, 1), (12, 2, 'CIE_QUIZ', 'Quiz 1', 10, 1),
            (13, 2, 'EL', 'EL', 20, NULL), (14, 2, 'SEE', 'SEE', 20, NULL);
        INSERT INTO assessment_question (question_id, assessment_id, q_no, max_marks) VALUES
            (111, 11, 'Q1', 10), (112, 11, 'Q2', 10),
            (121, 12, 'Q1', 10),
            (131, 13, 'Q1', 20),
            (141, 14, 'Q1', 10), (142, 14, 'Q2', 10);
        INSERT INTO question_co_map (question_id, co_id, weight) VALUES
            (111, 1, 1), (112, 2, 1), (121, 1, 1), (141, 1, 1), (142, 2, 1);
        INSERT INTO student_question_mark (enrollment_id, question_id, marks_obtained, is_absent) VALUES
            (101, 111, 7, false), (101, 112, 7, false), (101, 121, 8, false),
            (101, 131, 18, false), (101, 141, 6, false), (101, 142, 6, false),
            (102, 111, 7, false), (102, 112, 7, false), (102, 121, 8, false),
            (102, 131, 18, false), (102, 141, NULL, true), (102, 142, NULL, true);
    """)
    return db


def scores(db, usn):
    return {co: round(pct, 2) for _, co, pct in db.execute(
        "SELECT usn, co_id, pct FROM fn_student_co_score(2, 1) WHERE usn = %s ORDER BY co_id", (usn,))}


def test_every_component_that_tests_the_co(offering2):
    # (30 x 70 + 20 x 80 + 50 x 60) / 100
    assert scores(offering2, "1RV25WX101")[1] == D("67.00")


def test_component_not_testing_the_co_is_left_out(offering2):
    # (30 x 70 + 50 x 60) / 80
    assert scores(offering2, "1RV25WX101")[2] == D("63.75")


def test_absent_counts_as_zero(offering2):
    # (30 x 70 + 20 x 80 + 50 x 0) / 100
    assert scores(offering2, "1RV25WX102")[1] == D("37.00")


def test_view_uses_the_offerings_rule_version(offering2):
    row = offering2.execute(
        "SELECT round(pct, 2) FROM student_co_score WHERE offering_id = 2 AND usn = '1RV25WX101' AND co_id = 1"
    ).fetchone()
    assert row == (D("67.00"),)


def test_weights_come_from_the_rule_version(offering2):
    offering2.execute("UPDATE config_component_weight SET weight_pct = CASE component "
                      "WHEN 'CIE_THEORY' THEN 40 WHEN 'CIE_QUIZ' THEN 10 ELSE 50 END WHERE config_id = 1")
    # (40 x 70 + 10 x 80 + 50 x 60) / 100
    assert scores(offering2, "1RV25WX101")[1] == D("66.00")


def test_el_never_counts_towards_a_co(offering2):
    before = scores(offering2, "1RV25WX101")
    offering2.execute("UPDATE student_question_mark SET marks_obtained = 0 WHERE question_id = 131")
    assert scores(offering2, "1RV25WX101") == before
    with raises_sqlstate("CP017"):                       # EL cannot be tagged to a CO
        offering2.execute("INSERT INTO question_co_map VALUES (131, 1, 1)")
