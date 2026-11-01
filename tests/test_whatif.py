"""What-if runs (PRD FR-6.3, NFR-8): p_persist = false writes only the scenario's results."""

from decimal import Decimal as D


def scenario(db, base_config: int = 1, target: int = 80) -> int:
    db.execute("INSERT INTO app_user (user_id, username, password_hash, role, faculty_id) "
               "VALUES (1, 'fac', 'x', 'faculty', 1) ON CONFLICT DO NOTHING")
    return db.execute("""
        INSERT INTO whatif_scenario (offering_id, base_config_id, created_by, name, target_pct,
            l3_pct, l2_pct, l1_pct, direct_weight, indirect_weight, co_target_level, po_target_level)
        VALUES (1, %s, 1, 'what if', %s, 70, 60, 50, 80, 20, 2.0, 2.0) RETURNING scenario_id
    """, (base_config, target)).fetchone()[0]


def finals(db, scenario_id):
    return [r[0] for r in db.execute(
        "SELECT final_level FROM whatif_result WHERE scenario_id = %s ORDER BY co_id", (scenario_id,))]


def test_what_if_writes_only_the_scenario_results(db):
    sid = scenario(db, target=80)
    db.execute("CALL sp_compute_attainment(1, NULL, false, %s)", (sid,))
    # target 80%: only CO1's 48 students (8/10) reach it -> CO1 level 3, CO2 and CO3 level 0
    assert finals(db, sid) == [D("3.00"), D("0.60"), D("0.40")]
    assert db.execute("SELECT count(*) FROM whatif_po_result WHERE scenario_id = %s", (sid,)).fetchone()[0] == 2
    for table in ("co_attainment", "po_attainment", "improvement_action"):
        assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_what_if_on_another_rule_version(db):
    db.execute("""
        INSERT INTO attainment_config (config_id, program_id, target_pct, l3_pct, l2_pct, l1_pct,
            direct_weight, indirect_weight, co_target_level, po_target_level, valid_from, valid_to)
        VALUES (2, 1, 60, 70, 60, 50, 80, 20, 2.0, 2.0, '2010-08-01', '2020-08-01');
        INSERT INTO config_component_weight VALUES (2, 'SEE', 100);
    """)
    sid = scenario(db, base_config=2, target=60)        # not the offering's own version
    db.execute("CALL sp_compute_attainment(1, NULL, false, %s)", (sid,))
    assert finals(db, sid) == [D("3.00"), D("2.20"), D("0.40")]   # only the SEE tests the COs
