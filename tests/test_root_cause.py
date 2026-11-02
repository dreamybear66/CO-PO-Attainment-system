"""PRD Section 8 'Root-cause analysis' (FR-6.2, Section 11.6): planted cause, decoy, random data."""

import pytest

from datagen import scenario as sc
from tests.conftest import raises_sqlstate


def analyse(db):
    return {r["up_co_id"]: r for r in db.execute(
        "SELECT * FROM fn_root_cause(%s, %s)", (sc.DN_OFFERING, sc.WEAK)
    ).fetchall()}


@pytest.fixture
def dict_rows(empty_db):
    from psycopg.rows import dict_row
    empty_db.row_factory = dict_row
    return empty_db


def test_planted_cause_ranks_first_and_decoy_is_excluded(dict_rows):
    sc.build(dict_rows, n=60, effect=0.8, seed=11)
    result = analyse(dict_rows)
    assert result[sc.CAUSE]["passes"] and result[sc.CAUSE]["likely_cause_rank"] == 1
    assert result[sc.CAUSE]["correlation"] >= 0.6
    assert not result[sc.DECOY]["passes"] and result[sc.DECOY]["likely_cause_rank"] is None


def test_traversal_reaches_depth_two_with_decay(dict_rows):
    sc.build(dict_rows, n=60, effect=0.8, seed=11)
    deep = analyse(dict_rows)[sc.DEEP]
    assert deep["depth"] == 2
    assert float(deep["path_strength"]) == pytest.approx(0.8)     # (3/3) x (3/3) x decay 0.8


def test_random_data_yields_no_cause(dict_rows):
    sc.build(dict_rows, n=60, effect=0.0, seed=12)
    assert not any(r["passes"] for r in analyse(dict_rows).values())


def test_small_cohort_is_not_reported(dict_rows):
    sc.build(dict_rows, n=15, effect=0.8, seed=13)      # below rc_min_n = 20
    result = analyse(dict_rows)
    assert result[sc.CAUSE]["n"] == 15 and not result[sc.CAUSE]["passes"]


def edit_marks(conn, sql, params=()):
    """Change the scenario's (locked) marks directly, past the lock guard, as a data fixture."""
    conn.execute("ALTER TABLE student_question_mark DISABLE TRIGGER mark_guard")
    try:
        conn.execute(sql, params)
    finally:
        conn.execute("ALTER TABLE student_question_mark ENABLE TRIGGER mark_guard")


def action(conn, co=sc.WEAK):
    return conn.execute("SELECT fn_root_cause_action(%s, %s) AS id", (sc.DN_OFFERING, co)).fetchone()["id"]


def test_prefilled_improvement_action_once(dict_rows):
    sc.build(dict_rows, n=60, effect=0.8, seed=11)
    first = action(dict_rows)
    row = dict_rows.execute("SELECT source, description FROM improvement_action WHERE action_id = %s", (first,)).fetchone()
    assert row["source"] == "root_cause" and "UP101 CO2" in row["description"]
    assert action(dict_rows) == first                                   # a repeated request
    assert dict_rows.execute("SELECT count(*) AS n FROM improvement_action WHERE source = 'root_cause'").fetchone()["n"] == 1


def test_no_action_for_a_co_at_target(dict_rows):
    sc.build(dict_rows, n=60, effect=0.8, seed=11)
    met = dict_rows.execute("SELECT co_id FROM co_attainment WHERE offering_id = %s AND final_level >= 2.0 LIMIT 1",
                            (sc.DN_OFFERING,)).fetchone()["co_id"]
    with raises_sqlstate("CP016"):
        action(dict_rows, met)


def test_other_faculty_cannot_analyse(dict_rows, api_connect):
    sc.build(dict_rows, n=30, effect=0.8, seed=11)
    query = ("SELECT * FROM fn_root_cause(%s, %s)", (sc.DN_OFFERING, sc.WEAK))
    with raises_sqlstate("42501"):
        api_connect("faculty", faculty_id=2).execute(*query)
    for conn in (api_connect("faculty", faculty_id=1), api_connect("coordinator")):
        assert conn.execute(*query).fetchall()
    with raises_sqlstate("42501"):                                      # coordinators only read
        api_connect("coordinator").execute("SELECT fn_root_cause_action(%s, %s)", (sc.DN_OFFERING, sc.WEAK))
    with raises_sqlstate("42501"):                                      # app.role alone is not trusted
        api_connect("faculty", faculty_id=2, app_role="coordinator").execute(*query)


def test_direct_cause_outranks_a_deeper_one_with_the_same_evidence(dict_rows):
    sc.build(dict_rows, n=60, effect=0.8, seed=11)
    # give the deep CO the same marks as the planted cause: same r, longer path
    edit_marks(dict_rows, """
        UPDATE student_question_mark d SET marks_obtained = c.marks_obtained
        FROM student_question_mark c, enrollment ec, enrollment ed
        WHERE c.question_id = %s AND d.question_id = %s AND ec.enrollment_id = c.enrollment_id
          AND ed.enrollment_id = d.enrollment_id AND ec.usn = ed.usn""", (sc.CAUSE, sc.DEEP))
    result = analyse(dict_rows)
    assert result[sc.CAUSE]["correlation"] == result[sc.DEEP]["correlation"]
    assert (result[sc.CAUSE]["likely_cause_rank"], result[sc.DEEP]["likely_cause_rank"]) == (1, 2)


def test_depth_limit_and_decay_come_from_the_rule_version(dict_rows):
    sc.build(dict_rows, n=60, effect=0.8, seed=11)
    dict_rows.execute("UPDATE attainment_config SET rc_max_depth = 1, rc_depth_decay = 0.5")
    assert sc.DEEP not in analyse(dict_rows)
    dict_rows.execute("UPDATE attainment_config SET rc_max_depth = 2")
    assert float(analyse(dict_rows)[sc.DEEP]["path_strength"]) == pytest.approx(0.5)


def test_undefined_correlation_never_ranks(dict_rows):
    sc.build(dict_rows, n=60, effect=0.8, seed=11)
    dict_rows.execute("UPDATE attainment_config SET rc_min_r = 0")
    edit_marks(dict_rows, "UPDATE student_question_mark SET marks_obtained = 5 WHERE question_id = %s", (sc.DECOY,))
    decoy = analyse(dict_rows)[sc.DECOY]
    assert decoy["correlation"] is None and not decoy["passes"] and decoy["likely_cause_rank"] is None


def test_candidates_without_earlier_scores_are_listed_as_excluded(dict_rows):
    sc.build(dict_rows, n=60, effect=0.8, seed=11)
    edit_marks(dict_rows, "DELETE FROM student_question_mark WHERE question_id = %s", (sc.DECOY,))
    decoy = analyse(dict_rows)[sc.DECOY]
    assert (decoy["n"], decoy["passes"], decoy["up_final_level"], decoy["up_shortfall"]) == (0, False, None, None)


def test_unknown_upstream_level_has_no_shortfall_value(dict_rows):
    sc.build(dict_rows, n=60, effect=0.8, seed=11)
    dict_rows.execute("DELETE FROM po_attainment WHERE offering_id = 2; DELETE FROM improvement_action WHERE offering_id = 2; "
                      "DELETE FROM co_attainment WHERE offering_id = 2")   # UP101 not computed
    cause = analyse(dict_rows)[sc.CAUSE]
    assert cause["n"] == 60 and (cause["up_final_level"], cause["up_shortfall"]) == (None, None)


def test_judged_by_the_rule_version_of_the_results(dict_rows):
    """A version added later for the term must not change the analysis of computed results."""
    sc.build(dict_rows, n=60, effect=0.8, seed=11)
    before = analyse(dict_rows)
    dict_rows.execute("""
        UPDATE attainment_config SET valid_to = '2024-09-01';
        INSERT INTO attainment_config (config_id, program_id, target_pct, l3_pct, l2_pct, l1_pct, direct_weight,
            indirect_weight, co_target_level, po_target_level, rc_min_n, rc_min_r, valid_from)
        VALUES (2, 1, 60, 70, 60, 50, 80, 20, 2.5, 2.5, 100, 0.95, '2024-09-01');
        INSERT INTO config_component_weight VALUES (2, 'SEE', 100);
    """)
    assert analyse(dict_rows) == before


def test_missing_offering_co_or_config_is_an_error(dict_rows):
    sc.build(dict_rows, n=30, effect=0.8, seed=11)
    with raises_sqlstate("CP010"):
        dict_rows.execute("SELECT * FROM fn_root_cause(999, %s)", (sc.WEAK,))
    with raises_sqlstate("22023"):
        dict_rows.execute("SELECT * FROM fn_root_cause(%s, %s)", (sc.DN_OFFERING, sc.CAUSE))
    dict_rows.execute("DELETE FROM po_attainment; DELETE FROM improvement_action; DELETE FROM co_attainment; "
                      "UPDATE attainment_config SET valid_from = '2030-01-01'")
    with raises_sqlstate("CP011"):
        dict_rows.execute("SELECT * FROM fn_root_cause(%s, %s)", (sc.DN_OFFERING, sc.WEAK))


def test_serial_ids_continue_after_the_scenario(dict_rows):
    sc.build(dict_rows, n=20, effect=0.8, seed=11)
    dict_rows.execute("INSERT INTO course_offering (course_id, academic_year, term, faculty_id, section) "
                      "VALUES (1, '2025-26', 'odd', 1, 'B')")
    dict_rows.execute("INSERT INTO attainment_config (program_id, target_pct, l3_pct, l2_pct, l1_pct, direct_weight, "
                      "indirect_weight, co_target_level, po_target_level, valid_from, valid_to) "
                      "VALUES (1, 60, 70, 60, 50, 80, 20, 2.0, 2.0, '2010-01-01', '2015-01-01')")
