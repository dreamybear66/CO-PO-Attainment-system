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


def test_traversal_reaches_depth_two(dict_rows):
    sc.build(dict_rows, n=60, effect=0.8, seed=11)
    deep = analyse(dict_rows)[sc.DEEP]
    assert deep["depth"] == 2
    assert float(deep["path_strength"]) == pytest.approx(1.0)     # (3/3) x (3/3)


def test_random_data_yields_no_cause(dict_rows):
    sc.build(dict_rows, n=60, effect=0.0, seed=12)
    assert not any(r["passes"] for r in analyse(dict_rows).values())


def test_small_cohort_is_not_reported(dict_rows):
    sc.build(dict_rows, n=15, effect=0.8, seed=13)      # below rc_min_n = 20
    result = analyse(dict_rows)
    assert result[sc.CAUSE]["n"] == 15 and not result[sc.CAUSE]["passes"]


def test_prefilled_improvement_action(dict_rows):
    sc.build(dict_rows, n=60, effect=0.8, seed=11)
    action = dict_rows.execute("SELECT fn_root_cause_action(%s, %s) AS id", (sc.DN_OFFERING, sc.WEAK)).fetchone()["id"]
    row = dict_rows.execute("SELECT source, description FROM improvement_action WHERE action_id = %s", (action,)).fetchone()
    assert row["source"] == "root_cause" and "UP101 CO2" in row["description"]


def test_other_faculty_cannot_analyse(dict_rows):
    sc.build(dict_rows, n=30, effect=0.8, seed=11)
    dict_rows.execute("SELECT set_config('app.role', 'faculty', false), set_config('app.faculty_id', '2', false)")
    with raises_sqlstate("42501"):
        analyse(dict_rows)
    dict_rows.execute("SELECT set_config('app.faculty_id', '1', false)")
    assert analyse(dict_rows)
