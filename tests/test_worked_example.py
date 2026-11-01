"""PRD Section 5 / Section 8 'Correctness': the database must reproduce the hand calculation."""

from decimal import Decimal as D

from tests.conftest import raises_sqlstate


def co_rows(db):
    return db.execute(
        "SELECT co_id, pct_attained, direct_level, indirect_level, final_level, config_id "
        "FROM co_attainment WHERE offering_id = 1 ORDER BY co_id"
    ).fetchall()


def test_co_attainment_matches_hand_calculation(db):
    db.execute("CALL sp_compute_attainment(1)")
    assert co_rows(db) == [
        (1, D("80.00"), 3, 3, D("3.00"), 1),
        (2, D("65.00"), 2, 3, D("2.20"), 1),
        (3, D("45.00"), 0, 2, D("0.40"), 1),
    ]


def test_po_attainment_matches_hand_calculation(db):
    db.execute("CALL sp_compute_attainment(1)")
    rows = db.execute("SELECT po_id, attainment FROM po_attainment WHERE offering_id = 1 ORDER BY po_id").fetchall()
    assert rows == [(1, D("2.30")), (2, D("1.48"))]


def test_improvement_action_only_for_co_below_target(db):
    db.execute("CALL sp_compute_attainment(1)")
    actions = db.execute("SELECT co_id, source, owner FROM improvement_action").fetchall()
    assert actions == [(3, "auto", 1)]


def test_recompute_is_idempotent(db):
    db.execute("CALL sp_compute_attainment(1)")
    db.execute("CALL sp_compute_attainment(1)")
    assert db.execute("SELECT count(*) FROM co_attainment").fetchone()[0] == 3
    assert db.execute("SELECT count(*) FROM improvement_action").fetchone()[0] == 1


def test_official_results_use_the_offerings_rule_version(db):
    db.execute("""
        INSERT INTO attainment_config (config_id, program_id, target_pct, l3_pct, l2_pct, l1_pct,
            direct_weight, indirect_weight, co_target_level, po_target_level, valid_from, valid_to)
        VALUES (2, 1, 40, 70, 60, 50, 80, 20, 2.0, 2.0, '2010-08-01', '2020-08-01');
        INSERT INTO config_component_weight VALUES (2, 'SEE', 100);
    """)
    with raises_sqlstate("CP015"):                 # an older, more lenient version
        db.execute("CALL sp_compute_attainment(1, 2)")
    db.execute("CALL sp_compute_attainment(1, 1)")   # naming its own version is fine
    assert [r[5] for r in co_rows(db)] == [1, 1, 1]


def test_refuses_when_an_assessment_is_unlocked(db):
    db.execute("INSERT INTO assessment (offering_id, type, name, max_marks) VALUES (1, 'CIE_QUIZ', 'Quiz 1', 10)")
    with raises_sqlstate("CP012"):
        db.execute("CALL sp_compute_attainment(1)")


def test_refuses_when_a_co_is_not_assessed(db):
    db.execute("INSERT INTO course_outcome (course_id, co_number, statement, bloom_level) VALUES (1, 4, 'untested', 2)")
    with raises_sqlstate("CP013"):
        db.execute("CALL sp_compute_attainment(1)")


def test_missing_survey_counts_as_indirect_zero(db):
    db.execute("DELETE FROM indirect_attainment WHERE co_id = 1")
    db.execute("CALL sp_compute_attainment(1)")
    assert co_rows(db)[0][3:5] == (0, D("2.40"))


def test_programme_po_is_plain_average_of_offerings(db):
    db.execute("CALL sp_compute_attainment(1)")
    db.execute("INSERT INTO course_offering (offering_id, course_id, academic_year, term, faculty_id, section) "
               "VALUES (2, 1, '2025-26', 'even', 1, 'B')")
    db.execute("INSERT INTO po_attainment (offering_id, po_id, config_id, attainment) VALUES (2, 1, 1, 1.70)")
    row = db.execute("SELECT offerings, attainment FROM v_program_po_attainment WHERE po_id = 1").fetchone()
    assert row == (2, D("2.00"))   # (2.30 + 1.70) / 2


def test_dashboards_refreshed_after_compute(db):
    db.execute("CALL sp_compute_attainment(1)")
    assert db.execute("SELECT count(*) FROM mv_co_po_heatmap WHERE offering_id = 1").fetchone()[0] == 5
    assert db.execute("SELECT count(*) FROM mv_co_trend").fetchone()[0] == 3
