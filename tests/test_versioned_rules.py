"""PRD Section 8 'Reproducibility' (NFR-4, FR-4.1): results keep the rule version they used."""

from decimal import Decimal as D

from tests.conftest import raises_sqlstate


def finals(db):
    return [r[0] for r in db.execute("SELECT final_level FROM co_attainment ORDER BY co_id")]


def new_version(db, valid_from, target):
    """Close config 1 at valid_from and add config 2 with a different target_pct."""
    db.execute("UPDATE attainment_config SET valid_to = %s WHERE config_id = 1", (valid_from,))
    db.execute("""
        INSERT INTO attainment_config (config_id, program_id, target_pct, l3_pct, l2_pct, l1_pct,
            direct_weight, indirect_weight, co_target_level, po_target_level, valid_from)
        VALUES (2, 1, %s, 70, 60, 50, 80, 20, 2.0, 2.0, %s)""", (target, valid_from))
    db.execute("INSERT INTO config_component_weight SELECT 2, component, weight_pct FROM config_component_weight WHERE config_id = 1")


def test_future_rule_change_does_not_alter_past_results(db):
    db.execute("CALL sp_compute_attainment(1)")
    before = finals(db)
    new_version(db, "2026-08-01", target=80)        # the offering's term starts 2026-01-01
    db.execute("CALL sp_compute_attainment(1)")
    assert finals(db) == before
    assert db.execute("SELECT DISTINCT config_id FROM co_attainment").fetchall() == [(1,)]


def test_offering_uses_the_version_valid_at_its_term(db):
    new_version(db, "2025-12-01", target=80)
    assert db.execute("SELECT config_id FROM v_offering_config WHERE offering_id = 1").fetchone() == (2,)
    db.execute("CALL sp_compute_attainment(1)")
    # target 80%: only CO1's 48 students (8/10) reach it -> 80% attained -> level 3
    assert finals(db) == [D("3.00"), D("0.60"), D("0.40")]


def test_rerun_with_old_version_reproduces_old_numbers(db):
    db.execute("CALL sp_compute_attainment(1)")
    original = finals(db)
    new_version(db, "2025-12-01", target=80)
    db.execute("CALL sp_compute_attainment(1)")
    assert finals(db) != original
    db.execute("CALL sp_compute_attainment(1, 1)")  # explicitly with last year's config
    assert finals(db) == original


def test_versions_cannot_overlap(db):
    with raises_sqlstate("23P01"):
        db.execute("""
            INSERT INTO attainment_config (program_id, target_pct, l3_pct, l2_pct, l1_pct, direct_weight,
                indirect_weight, co_target_level, po_target_level, valid_from)
            VALUES (1, 60, 70, 60, 50, 80, 20, 2.0, 2.0, '2025-01-01')""")
