"""What-if simulator (PRD FR-6.3, Section 11.3).

A scenario overrides the rule values of an offering's base config; the same stored procedure runs
with p_persist = false, so results land only in whatif_result / whatif_po_result.
"""

from psycopg.rows import tuple_row

RULE_FIELDS =("target_pct", "l3_pct", "l2_pct", "l1_pct", "direct_weight", "indirect_weight",
               "co_target_level", "po_target_level")


def create_and_run(conn, *, offering_id: int, created_by: int, name: str, rules: dict) -> int:
    """Create a scenario (missing rule values default to the base config) and run it."""
    conn = conn.cursor(row_factory=tuple_row)     # positional rows whatever the connection's factory
    with conn.connection.transaction():
        base = conn.execute(
            "SELECT c.config_id, " + ", ".join(f"c.{f}" for f in RULE_FIELDS) +
            " FROM v_offering_config oc JOIN attainment_config c USING (config_id) WHERE oc.offering_id = %s",
            (offering_id,),
        ).fetchone()
        if base is None:
            raise ValueError(f"No attainment configuration applies to offering {offering_id}")
        values = {f: rules.get(f, base[i + 1]) for i, f in enumerate(RULE_FIELDS)}
        scenario_id = conn.execute(
            "INSERT INTO whatif_scenario (offering_id, base_config_id, created_by, name, "
            + ", ".join(RULE_FIELDS) + ") VALUES (%s, %s, %s, %s, " + ", ".join(["%s"] * len(RULE_FIELDS))
            + ") RETURNING scenario_id",
            (offering_id, base[0], created_by, name, *values.values()),
        ).fetchone()[0]
        conn.execute("CALL sp_compute_attainment(%s, NULL, false, %s)", (offering_id, scenario_id))
    return scenario_id


def compare(conn, scenario_id: int) -> dict:
    """Baseline (official) vs scenario, per CO and per PO, with each side's target."""
    conn = conn.cursor(row_factory=tuple_row)
    s = conn.execute(
        "SELECT offering_id, co_target_level, po_target_level FROM whatif_scenario WHERE scenario_id = %s",
        (scenario_id,),
    ).fetchone()
    if s is None:
        raise ValueError(f"Scenario {scenario_id} not found")
    offering_id, co_target, po_target = s
    base_targets = conn.execute(
        "SELECT c.co_target_level, c.po_target_level FROM co_attainment ca "
        "JOIN attainment_config c USING (config_id) WHERE ca.offering_id = %s LIMIT 1", (offering_id,)
    ).fetchone()
    cos = conn.execute("""
        SELECT co.co_id, co.co_number, b.final_level, w.final_level, b.direct_level, w.direct_level
        FROM whatif_result w
        JOIN course_outcome co USING (co_id)
        LEFT JOIN co_attainment b ON b.offering_id = %s AND b.co_id = w.co_id
        WHERE w.scenario_id = %s ORDER BY co.co_number""", (offering_id, scenario_id)).fetchall()
    pos = conn.execute("""
        SELECT po.po_id, po.code, b.attainment, w.attainment
        FROM whatif_po_result w
        JOIN program_outcome po USING (po_id)
        LEFT JOIN po_attainment b ON b.offering_id = %s AND b.po_id = w.po_id
        WHERE w.scenario_id = %s ORDER BY po.po_id""", (offering_id, scenario_id)).fetchall()
    base_co_target, base_po_target = base_targets or (None, None)

    def crossed(before, after, t_before, t_after):
        if before is None or t_before is None:
            return None
        was, now = before >= t_before, after >= t_after
        return "now meets" if now and not was else "now misses" if was and not now else None

    return {
        "scenario_id": scenario_id,
        "offering_id": offering_id,
        "targets": {"baseline": {"co": base_co_target, "po": base_po_target},
                    "scenario": {"co": co_target, "po": po_target}},
        "cos": [{"co_id": r[0], "co_number": r[1], "baseline": r[2], "scenario": r[3],
                 "baseline_direct": r[4], "scenario_direct": r[5],
                 "change": crossed(r[2], r[3], base_co_target, co_target)} for r in cos],
        "pos": [{"po_id": r[0], "code": r[1], "baseline": r[2], "scenario": r[3],
                 "change": crossed(r[2], r[3], base_po_target, po_target)} for r in pos],
    }
