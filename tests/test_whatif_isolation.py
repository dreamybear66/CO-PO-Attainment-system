"""PRD Section 8 'Simulator isolation' (NFR-8) and FR-6.3 scenario results."""

from decimal import Decimal as D

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
    # CO2 65% -> 3, CO3 45% -> 1: PO2 = (3 x 3.00 + 2 x 1.20) / 5 = 2.28, up from 1.48
    assert (po2["baseline"], po2["scenario"], po2["change"]) == (D("1.48"), D("2.28"), "now meets")
    co3 = next(c for c in result["cos"] if c["co_number"] == 3)
    assert (co3["scenario_direct"], co3["scenario"]) == (1, D("1.20"))


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
