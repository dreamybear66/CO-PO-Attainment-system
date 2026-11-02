"""What-if simulator (PRD FR-6.3, Section 11.3).

A scenario overrides the rule values of a base config; the same stored procedure runs with
p_persist = false, so results land only in whatif_result / whatif_po_result.

The base config is the one the offering's official results were computed with (so an empty
override reproduces the baseline), or the rule version valid for its term if it has none yet.
Queries use a tuple-row cursor, so callers may pass connections with any row factory.
"""

from decimal import Decimal, InvalidOperation

from psycopg.rows import tuple_row

RULE_FIELDS = ("target_pct", "l3_pct", "l2_pct", "l1_pct", "direct_weight", "indirect_weight",
               "co_target_level", "po_target_level")
PCT_FIELDS = RULE_FIELDS[:6]


class ScenarioError(ValueError):
    pass


def _number(field: str, value) -> Decimal:
    if isinstance(value, bool):
        raise ScenarioError(f"{field} must be a number")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ScenarioError(f"{field} must be a number") from None
    if not number.is_finite():
        raise ScenarioError(f"{field} must be a number")
    high = 100 if field in PCT_FIELDS else 3
    if not 0 <= number <= high:
        raise ScenarioError(f"{field} must be between 0 and {high}")
    return number


def scenario_rules(base: dict, overrides: dict) -> dict:
    """Base rule values with the overrides applied. Unknown fields are refused; a weight given
    alone gets its complement (they sum to 100); thresholds must stay l3 >= l2 >= l1."""
    unknown = sorted(set(overrides) - set(RULE_FIELDS))
    if unknown:
        raise ScenarioError(f"Unknown rule field(s): {', '.join(unknown)}; allowed: {', '.join(RULE_FIELDS)}")
    rules = dict(base)
    rules.update({f: _number(f, v) for f, v in overrides.items()})
    if "direct_weight" in overrides and "indirect_weight" not in overrides:
        rules["indirect_weight"] = 100 - rules["direct_weight"]
    elif "indirect_weight" in overrides and "direct_weight" not in overrides:
        rules["direct_weight"] = 100 - rules["indirect_weight"]
    if rules["direct_weight"] + rules["indirect_weight"] != 100:
        raise ScenarioError("direct_weight and indirect_weight must add up to 100")
    if not rules["l3_pct"] >= rules["l2_pct"] >= rules["l1_pct"]:
        raise ScenarioError(f"Thresholds must satisfy l3_pct >= l2_pct >= l1_pct "
                            f"(got {rules['l3_pct']}, {rules['l2_pct']}, {rules['l1_pct']})")
    return rules


def base_config(cur, offering_id: int) -> int | None:
    row = cur.execute(
        "SELECT coalesce((SELECT config_id FROM co_attainment WHERE offering_id = %s LIMIT 1), "
        "(SELECT config_id FROM v_offering_config WHERE offering_id = %s))", (offering_id, offering_id)
    ).fetchone()
    return row[0]


def create_and_run(conn, *, offering_id: int, created_by: int, name: str, rules: dict,
                   base_config_id: int | None = None) -> int:
    """Create a scenario and run it. Rules missing from `rules` come from the base config:
    `base_config_id`, or by default the config of the offering's official results."""
    cur = conn.cursor(row_factory=tuple_row)
    with conn.transaction():
        config_id = base_config_id or base_config(cur, offering_id)
        if config_id is None:
            raise ScenarioError(f"No attainment configuration applies to offering {offering_id}")
        row = cur.execute("SELECT " + ", ".join(RULE_FIELDS) + " FROM attainment_config WHERE config_id = %s",
                          (config_id,)).fetchone()
        if row is None:
            raise ScenarioError(f"Config {config_id} not found")
        values = scenario_rules(dict(zip(RULE_FIELDS, row)), rules)
        scenario_id = cur.execute(
            "INSERT INTO whatif_scenario (offering_id, base_config_id, created_by, name, "
            + ", ".join(RULE_FIELDS) + ") VALUES (%s, %s, %s, %s, " + ", ".join(["%s"] * len(RULE_FIELDS))
            + ") RETURNING scenario_id",
            (offering_id, config_id, created_by, name, *(values[f] for f in RULE_FIELDS)),
        ).fetchone()[0]
        cur.execute("CALL sp_compute_attainment(%s, NULL, false, %s)", (offering_id, scenario_id))
    return scenario_id


def compare(conn, scenario_id: int) -> dict:
    """Baseline (official) vs scenario, per CO and per PO, with each side's target."""
    cur = conn.cursor(row_factory=tuple_row)
    s = cur.execute(
        "SELECT offering_id, co_target_level, po_target_level FROM whatif_scenario WHERE scenario_id = %s",
        (scenario_id,),
    ).fetchone()
    if s is None:
        raise ScenarioError(f"Scenario {scenario_id} not found")
    offering_id, co_target, po_target = s
    base_targets = cur.execute(
        "SELECT c.co_target_level, c.po_target_level FROM co_attainment ca "
        "JOIN attainment_config c USING (config_id) WHERE ca.offering_id = %s LIMIT 1", (offering_id,)
    ).fetchone()
    cos = cur.execute("""
        SELECT co.co_id, co.co_number, b.final_level, w.final_level, b.direct_level, w.direct_level
        FROM whatif_result w
        JOIN course_outcome co USING (co_id)
        LEFT JOIN co_attainment b ON b.offering_id = %s AND b.co_id = w.co_id
        WHERE w.scenario_id = %s ORDER BY co.co_number""", (offering_id, scenario_id)).fetchall()
    pos = cur.execute("""
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
