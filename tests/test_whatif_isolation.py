"""PRD Section 8 'Simulator isolation' (NFR-8) and FR-6.3 scenario results."""

from decimal import Decimal as D

import pytest
from psycopg.rows import dict_row

from api.services import whatif
from tests.conftest import raises_sqlstate

OFFICIAL = ["co_attainment", "po_attainment", "improvement_action", "indirect_attainment"]


def fingerprint(db) -> dict:
    return {t: db.execute(f"SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) FROM {t} t").fetchone()[0]
            for t in OFFICIAL}


def add_user(db):
    db.execute("INSERT INTO app_user (user_id, username, password_hash, role, faculty_id) VALUES (1, 'fac', 'x', 'faculty', 1)")


def test_whatif_leaves_official_tables_unchanged(db):
    add_user(db)
    db.execute("CALL sp_compute_attainment(1)")
    before = fingerprint(db)
    whatif.create_and_run(db, offering_id=1, created_by=1, name="looser", rules={"target_pct": 40})
    assert fingerprint(db) == before


def test_scenario_shows_which_pos_cross_the_target(db):
    add_user(db)
    db.execute("CALL sp_compute_attainment(1)")
    sid = whatif.create_and_run(db, offering_id=1, created_by=1, name="lower thresholds",
                                rules={"l3_pct": 60, "l2_pct": 50, "l1_pct": 40})
    result = whatif.compare(db, sid)
    po2 = next(p for p in result["pos"] if p["code"] == "PO2")
    # The thresholds apply to the survey % too. CO2 direct 65% -> 3, survey 74% -> 3: 3.00.
    # CO3 direct 45% -> 1, survey 62% -> 3: 1.40. PO2 = (3 x 3.00 + 2 x 1.40) / 5 = 2.36, up from 1.48
    assert (po2["baseline"], po2["scenario"], po2["change"]) == (D("1.48"), D("2.36"), "now meets")
    co3 = next(c for c in result["cos"] if c["co_number"] == 3)
    assert (co3["scenario_direct"], co3["scenario"]) == (1, D("1.40"))


def test_scenario_weights(db):
    add_user(db)
    db.execute("CALL sp_compute_attainment(1)")
    sid = whatif.create_and_run(db, offering_id=1, created_by=1, name="70/30",
                                rules={"direct_weight": 70, "indirect_weight": 30})
    finals = [c["scenario"] for c in whatif.compare(db, sid)["cos"]]
    assert finals == [D("3.00"), D("2.30"), D("0.60")]


def test_scenario_cannot_be_persisted(db):
    add_user(db)
    sid = whatif.create_and_run(db, offering_id=1, created_by=1, name="x", rules={})
    with raises_sqlstate("CP014"):
        db.execute("CALL sp_compute_attainment(1, NULL, true, %s)", (sid,))


def test_empty_scenario_reproduces_the_official_results_of_their_rule_version(db):
    """A rule version added later for the term must not become the baseline of a scenario."""
    add_user(db)
    db.execute("CALL sp_compute_attainment(1)")
    db.execute("UPDATE attainment_config SET valid_to = '2025-12-01' WHERE config_id = 1")
    db.execute("""
        INSERT INTO attainment_config (config_id, program_id, target_pct, l3_pct, l2_pct, l1_pct,
            direct_weight, indirect_weight, co_target_level, po_target_level, valid_from)
        VALUES (2, 1, 80, 70, 60, 50, 80, 20, 2.0, 2.0, '2025-12-01');
        INSERT INTO config_component_weight SELECT 2, component, weight_pct FROM config_component_weight WHERE config_id = 1;
    """)
    result = whatif.compare(db, whatif.create_and_run(db, offering_id=1, created_by=1, name="same", rules={}))
    assert all(c["scenario"] == c["baseline"] and c["change"] is None for c in result["cos"])


@pytest.mark.parametrize("rules, message", [
    ({"target": 40}, "Unknown rule field"),
    ({"l3_pct": 55}, "l3_pct >= l2_pct"),
    ({"direct_weight": 70, "indirect_weight": 40}, "add up to 100"),
    ({"target_pct": 140}, "between 0 and 100"),
    ({"co_target_level": True}, "must be a number"),
    ({"target_pct": "NaN"}, "must be a number"),
])
def test_bad_overrides_are_refused(db, rules, message):
    add_user(db)
    with pytest.raises(whatif.ScenarioError, match=message):
        whatif.create_and_run(db, offering_id=1, created_by=1, name="bad", rules=rules)
    assert db.execute("SELECT count(*) FROM whatif_scenario").fetchone()[0] == 0


def test_a_weight_given_alone_gets_its_complement(db, connect):
    add_user(db)
    conn = connect()
    conn.row_factory = dict_row                         # as the API's sessions
    sid = whatif.create_and_run(conn, offering_id=1, created_by=1, name="70/30", rules={"direct_weight": 70})
    assert db.execute("SELECT direct_weight, indirect_weight FROM whatif_scenario WHERE scenario_id = %s",
                      (sid,)).fetchone() == (D("70"), D("30"))
    assert [c["scenario"] for c in whatif.compare(conn, sid)["cos"]] == [D("3.00"), D("2.30"), D("0.60")]

