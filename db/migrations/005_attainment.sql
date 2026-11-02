-- 005_attainment.sql
-- The attainment engine (PRD FR-4.2 - FR-4.4, Section 5): sp_compute_attainment, sp_compute_all.
--   CP010 offering not found   CP011 no rule version   CP012 assessments missing or unlocked
--   CP013 CO not assessed      CP014 bad scenario      CP015 config is not the offering's rule version
--   42501 not allowed
--
-- Privileges: every routine here loses the default EXECUTE for PUBLIC (end of file). Faculty and
-- admin may call sp_compute_attainment, only admin sp_compute_all; the rest run inside them.

-- The caller's application role. The API runs SET LOCAL ROLE copo_<role> and sets app.role (and
-- app.faculty_id) per request. app.role is trusted only when the active role matches it, so a
-- session cannot become admin by setting app.role alone. Maintenance logins (owner, superuser) set
-- neither and get ''; any other mismatch gives NULL. current_setting('role') is the session's
-- SET ROLE, also inside SECURITY DEFINER routines.
CREATE FUNCTION fn_app_role() RETURNS text
LANGUAGE sql STABLE SET search_path = public, pg_temp AS $$
    SELECT CASE
        WHEN coalesce(current_setting('app.role', true), '') = '' THEN
            CASE WHEN current_setting('role') = 'none'
                  AND (session_user::text = 'copo_owner'
                       OR (SELECT rolsuper FROM pg_roles WHERE rolname = session_user))
                 THEN '' END
        WHEN current_setting('role') = 'copo_' || current_setting('app.role', true)
            THEN current_setting('app.role', true)
    END
$$;

-- Who may compute an offering: admin, a maintenance login, or the faculty member teaching it.
CREATE FUNCTION fn_can_manage_offering(p_offering_id int) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT CASE fn_app_role()
        WHEN 'admin'   THEN true
        WHEN ''        THEN true
        WHEN 'faculty' THEN EXISTS (
            SELECT 1 FROM course_offering
            WHERE offering_id = p_offering_id
              AND faculty_id = nullif(current_setting('app.faculty_id', true), '')::int)
        ELSE false
    END
$$;

-- The rules one computation applies to one offering: the config whose component weights score the
-- students, and the thresholds and weights (from that config, or from a what-if scenario).
CREATE TYPE attainment_rules AS (
    offering_id     int,
    config_id       int,
    target_pct      numeric,
    l3_pct          numeric,
    l2_pct          numeric,
    l1_pct          numeric,
    direct_weight   numeric,
    indirect_weight numeric,
    co_target_level numeric
);

-- CO rows (steps 3-6) for any number of offerings in one pass. pct_attained is NULL for a CO that
-- no question tests.
CREATE FUNCTION fn_co_attainment_calc(p_rules attainment_rules[])
RETURNS TABLE (offering_id int, co_id int, co_number smallint, students int, pct_attained numeric,
               direct_level smallint, indirect_level smallint, final_level numeric)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_column
DECLARE
    -- Plain array parameters, so both filters are pushed down into the score aggregation (a join
    -- with the rules alone would aggregate every offering, or every config, first).
    v_offerings int[] := ARRAY(SELECT r.offering_id FROM unnest(p_rules) r);
    v_configs   int[] := ARRAY(SELECT DISTINCT r.config_id FROM unnest(p_rules) r);
BEGIN
    RETURN QUERY
    WITH rules AS (
        SELECT * FROM unnest(p_rules)
    ),
    direct AS (
        SELECT s.offering_id, s.co_id,
               count(*)::int AS students,
               -- rounded here, as stored, so the level always agrees with the stored percentage
               round(100.0 * count(*) FILTER (WHERE s.pct >= r.target_pct) / count(*), 2) AS pct_attained
        FROM rules r
        JOIN student_co_score_by_config s ON s.offering_id = r.offering_id AND s.config_id = r.config_id
        WHERE s.offering_id = ANY (v_offerings) AND s.config_id = ANY (v_configs)
        GROUP BY s.offering_id, s.co_id
    ),
    levels AS (
        SELECT r.offering_id, co.co_id, co.co_number,
               coalesce(d.students, 0)                                AS students,
               d.pct_attained,
               fn_level(d.pct_attained, r.l3_pct, r.l2_pct, r.l1_pct) AS direct_level,
               -- from the survey % with this run's thresholds; no survey data counts as 0
               fn_level(ia.pct_favourable, r.l3_pct, r.l2_pct, r.l1_pct) AS indirect_level,
               r.direct_weight, r.indirect_weight
        FROM rules r
        JOIN course_offering o ON o.offering_id = r.offering_id
        JOIN course_outcome co ON co.course_id = o.course_id
        LEFT JOIN direct d ON d.offering_id = r.offering_id AND d.co_id = co.co_id
        LEFT JOIN indirect_attainment ia ON ia.offering_id = r.offering_id AND ia.co_id = co.co_id
    )
    SELECT l.offering_id, l.co_id, l.co_number, l.students, l.pct_attained, l.direct_level, l.indirect_level,
           round((l.direct_weight * l.direct_level + l.indirect_weight * l.indirect_level) / 100.0, 2)
    FROM levels l;
END $$;

-- Computes and stores attainment for the given rules (steps 2-7): official results, automatic
-- improvement actions and follow-up links, or, with p_scenario_id, what-if results only.
-- The public procedures below check permissions and take the locks first; this one is not granted.
CREATE PROCEDURE sp_store_attainment(p_rules attainment_rules[], p_scenario_id int DEFAULT NULL)
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    v_offerings int[] := ARRAY(SELECT r.offering_id FROM unnest(p_rules) r);
    v_untested  text;
BEGIN
    -- 2-4. CO levels
    DROP TABLE IF EXISTS _co_rows;
    CREATE TEMP TABLE _co_rows ON COMMIT DROP AS
    SELECT c.*, r.config_id, r.co_target_level
    FROM fn_co_attainment_calc(p_rules) c
    JOIN unnest(p_rules) r ON r.offering_id = c.offering_id;

    SELECT string_agg(format('CO%s of offering %s', co_number, offering_id), ', '
                      ORDER BY offering_id, co_number)
    INTO v_untested FROM _co_rows WHERE pct_attained IS NULL;
    IF v_untested IS NOT NULL THEN
        RAISE EXCEPTION 'No question tests %', v_untested USING ERRCODE = 'CP013';
    END IF;

    -- 5. PO per offering = sum(strength x final CO level) / sum(strength)
    DROP TABLE IF EXISTS _po_rows;
    CREATE TEMP TABLE _po_rows ON COMMIT DROP AS
    SELECT c.offering_id, m.po_id, c.config_id,
           round(sum(m.strength * c.final_level) / sum(m.strength), 2) AS attainment
    FROM _co_rows c JOIN co_po_map m ON m.co_id = c.co_id
    GROUP BY c.offering_id, m.po_id, c.config_id;

    -- 6. what-if: results for the scenario only
    IF p_scenario_id IS NOT NULL THEN
        DELETE FROM whatif_result WHERE scenario_id = p_scenario_id;
        INSERT INTO whatif_result (scenario_id, co_id, pct_attained, direct_level, indirect_level, final_level)
        SELECT p_scenario_id, co_id, pct_attained, direct_level, indirect_level, final_level FROM _co_rows;

        DELETE FROM whatif_po_result WHERE scenario_id = p_scenario_id;
        INSERT INTO whatif_po_result (scenario_id, po_id, attainment)
        SELECT p_scenario_id, po_id, attainment FROM _po_rows;
        RETURN;
    END IF;

    -- 6. official results
    DELETE FROM co_attainment WHERE offering_id = ANY (v_offerings);
    INSERT INTO co_attainment (offering_id, co_id, config_id, students, pct_attained,
                               direct_level, indirect_level, final_level)
    SELECT offering_id, co_id, config_id, students, pct_attained, direct_level, indirect_level, final_level
    FROM _co_rows;

    DELETE FROM po_attainment WHERE offering_id = ANY (v_offerings);
    INSERT INTO po_attainment (offering_id, po_id, config_id, attainment)
    SELECT offering_id, po_id, config_id, attainment FROM _po_rows;

    -- 7. Automatic improvement actions follow the latest computation (FR-4.4): one per CO below
    -- target, with its text kept current. When a recompute (after a corrected unlock) puts the CO at
    -- target, its action is closed. Otherwise status is left to people.
    INSERT INTO improvement_action (co_id, offering_id, description, owner, source)
    SELECT c.co_id, c.offering_id,
           format('CO%s final level %s is below the target %s', c.co_number, c.final_level, c.co_target_level),
           o.faculty_id, 'auto'
    FROM _co_rows c JOIN course_offering o ON o.offering_id = c.offering_id
    WHERE c.final_level < c.co_target_level
    ON CONFLICT (offering_id, co_id) WHERE source = 'auto'
    DO UPDATE SET description = EXCLUDED.description
    WHERE improvement_action.description IS DISTINCT FROM EXCLUDED.description;   -- no no-op writes

    UPDATE improvement_action ia
    SET status = 'done',
        description = format('CO%s final level %s meets the target %s after a recompute',
                             c.co_number, c.final_level, c.co_target_level)
    FROM _co_rows c
    WHERE ia.source = 'auto' AND ia.offering_id = c.offering_id AND ia.co_id = c.co_id
      AND c.final_level >= c.co_target_level AND ia.status <> 'done';

    -- Close the loop: an action's follow-up is the next computed offering of the same course and
    -- section within 18 months. Linked from whichever of the two is computed second, so the order
    -- in which offerings are computed (or recomputed after an unlock) does not matter.
    UPDATE improvement_action ia
    SET follow_up_offering_id = link.next_offering
    FROM (
        SELECT DISTINCT ON (a.action_id) a.action_id, nxt.offering_id AS next_offering
        FROM improvement_action a
        JOIN course_offering prev ON prev.offering_id = a.offering_id
        JOIN course_offering nxt  ON nxt.course_id = prev.course_id AND nxt.section = prev.section
        WHERE a.follow_up_offering_id IS NULL
          AND (prev.offering_id = ANY (v_offerings) OR nxt.offering_id = ANY (v_offerings))
          AND fn_term_start(nxt.academic_year, nxt.term) > fn_term_start(prev.academic_year, prev.term)
          AND fn_term_start(nxt.academic_year, nxt.term)
              <= fn_term_start(prev.academic_year, prev.term) + interval '18 months'
          AND EXISTS (SELECT 1 FROM co_attainment ca WHERE ca.offering_id = nxt.offering_id)
        ORDER BY a.action_id, fn_term_start(nxt.academic_year, nxt.term)
    ) link
    WHERE ia.action_id = link.action_id;
END $$;

CREATE PROCEDURE sp_compute_attainment(
    p_offering_id int,
    p_config_id   int     DEFAULT NULL,
    p_persist     boolean DEFAULT true,
    p_scenario_id int     DEFAULT NULL,
    p_refresh     boolean DEFAULT true)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_off       course_offering%ROWTYPE;
    v_cfg       attainment_config%ROWTYPE;
    v_scn       whatif_scenario%ROWTYPE;
    v_program   int;
    v_total     int;
    v_unlocked  int;
    v_rules     attainment_rules;
    v_official  int;
BEGIN
    -- 0. permission first, so a caller who may not compute never holds the offering's lock
    IF NOT EXISTS (SELECT 1 FROM course_offering WHERE offering_id = p_offering_id) THEN
        RAISE EXCEPTION 'Offering % not found', p_offering_id USING ERRCODE = 'CP010';
    END IF;
    IF NOT fn_can_manage_offering(p_offering_id) THEN
        RAISE EXCEPTION 'Not allowed to compute offering %', p_offering_id USING ERRCODE = '42501';
    END IF;
    -- One run per offering at a time. NO KEY UPDATE conflicts with itself but not with the
    -- FOR KEY SHARE taken by foreign-key checks, so inserts that reference the offering do not wait.
    SELECT * INTO v_off FROM course_offering WHERE offering_id = p_offering_id FOR NO KEY UPDATE;
    SELECT program_id INTO v_program FROM course WHERE course_id = v_off.course_id;

    -- rules: the official config, or a what-if scenario on top of its base config
    IF p_persist THEN
        IF p_scenario_id IS NOT NULL THEN
            RAISE EXCEPTION 'A what-if scenario cannot be persisted' USING ERRCODE = 'CP014';
        END IF;
        -- Official results always use the rule version valid at the offering's term; other rules
        -- can be tried as a what-if scenario.
        SELECT config_id INTO v_official FROM v_offering_config WHERE offering_id = p_offering_id;
        IF p_config_id IS NOT NULL AND p_config_id IS DISTINCT FROM v_official THEN
            RAISE EXCEPTION 'Config % is not the rule version of offering %; try other rules as a what-if scenario',
                p_config_id, p_offering_id USING ERRCODE = 'CP015';
        END IF;
        p_config_id := v_official;
    ELSE
        SELECT * INTO v_scn FROM whatif_scenario
        WHERE scenario_id = p_scenario_id AND offering_id = p_offering_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Scenario % does not belong to offering %', p_scenario_id, p_offering_id
                USING ERRCODE = 'CP014';
        END IF;
        p_config_id := v_scn.base_config_id;
    END IF;
    SELECT * INTO v_cfg FROM attainment_config WHERE config_id = p_config_id AND program_id = v_program;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No attainment configuration applies to offering %', p_offering_id
            USING ERRCODE = 'CP011';
    END IF;
    IF p_persist THEN
        v_rules := ROW(p_offering_id, p_config_id, v_cfg.target_pct, v_cfg.l3_pct, v_cfg.l2_pct, v_cfg.l1_pct,
                       v_cfg.direct_weight, v_cfg.indirect_weight, v_cfg.co_target_level);
    ELSE
        v_rules := ROW(p_offering_id, p_config_id, v_scn.target_pct, v_scn.l3_pct, v_scn.l2_pct, v_scn.l1_pct,
                       v_scn.direct_weight, v_scn.indirect_weight, v_scn.co_target_level);
    END IF;

    -- 1. every assessment of the offering must be locked. FOR SHARE keeps them so until commit: an
    -- unlock (an UPDATE) waits for this run instead of slipping in before the scores are read.
    SELECT count(*), count(*) FILTER (WHERE NOT a.locked) INTO v_total, v_unlocked
    FROM (SELECT locked FROM assessment WHERE offering_id = p_offering_id FOR SHARE) a;
    IF v_total = 0 THEN
        RAISE EXCEPTION 'Offering % has no assessments', p_offering_id USING ERRCODE = 'CP012';
    END IF;
    IF v_unlocked > 0 THEN
        RAISE EXCEPTION '% of % assessments of offering % are not locked', v_unlocked, v_total, p_offering_id
            USING ERRCODE = 'CP012';
    END IF;

    CALL sp_store_attainment(ARRAY[v_rules], CASE WHEN p_persist THEN NULL ELSE p_scenario_id END);
    IF p_persist AND p_refresh THEN
        PERFORM fn_refresh_dashboards();
    END IF;
END $$;

-- Compute every offering whose assessments are all locked, in one set-based pass, and refresh the
-- dashboards once. Admin and maintenance logins only.
CREATE PROCEDURE sp_compute_all()
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_rules    attainment_rules[];
    v_missing  text;
BEGIN
    IF fn_app_role() IS DISTINCT FROM 'admin' AND fn_app_role() IS DISTINCT FROM '' THEN
        RAISE EXCEPTION 'Only an admin can compute every offering' USING ERRCODE = '42501';
    END IF;
    -- Hold every assessment FOR SHARE so none is locked or unlocked during the run. Eligibility is
    -- read in the next statement, which sees any change that committed while this one waited.
    PERFORM 1 FROM assessment ORDER BY assessment_id FOR SHARE;

    SELECT array_agg(ROW(o.offering_id, c.config_id, c.target_pct, c.l3_pct, c.l2_pct, c.l1_pct,
                         c.direct_weight, c.indirect_weight, c.co_target_level)::attainment_rules
                     ORDER BY o.offering_id) FILTER (WHERE c.config_id IS NOT NULL),
           string_agg(o.offering_id::text, ', ' ORDER BY o.offering_id) FILTER (WHERE c.config_id IS NULL)
    INTO v_rules, v_missing
    FROM course_offering o
    LEFT JOIN v_offering_config oc ON oc.offering_id = o.offering_id
    LEFT JOIN attainment_config c  ON c.config_id = oc.config_id
    WHERE EXISTS (SELECT 1 FROM assessment a WHERE a.offering_id = o.offering_id)
      AND NOT EXISTS (SELECT 1 FROM assessment a WHERE a.offering_id = o.offering_id AND NOT a.locked);
    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION 'No attainment configuration applies to offering(s) %', v_missing USING ERRCODE = 'CP011';
    END IF;

    -- one run per offering at a time; id order so concurrent runs cannot deadlock
    PERFORM 1 FROM course_offering
    WHERE offering_id IN (SELECT r.offering_id FROM unnest(v_rules) r)
    ORDER BY offering_id FOR NO KEY UPDATE;

    IF v_rules IS NOT NULL THEN
        CALL sp_store_attainment(v_rules);
    END IF;
    PERFORM fn_refresh_dashboards();
END $$;

-- Closed loop (FR-4.4): each action beside the CO's level then and in the follow-up offering.
CREATE VIEW v_improvement_followup WITH (security_invoker = true) AS
SELECT ia.action_id, ia.co_id, ia.offering_id, ia.status, ia.source, ia.description,
       before.final_level AS level_before,
       ia.follow_up_offering_id,
       after.final_level  AS level_after,
       after.final_level - before.final_level AS change
FROM improvement_action ia
LEFT JOIN co_attainment before ON before.offering_id = ia.offering_id AND before.co_id = ia.co_id
LEFT JOIN co_attainment after  ON after.offering_id = ia.follow_up_offering_id AND after.co_id = ia.co_id;

-- ---------------------------------------------------------------- privileges

REVOKE EXECUTE ON FUNCTION fn_app_role(), fn_can_manage_offering(int),
    fn_co_attainment_calc(attainment_rules[]) FROM PUBLIC;
REVOKE EXECUTE ON PROCEDURE sp_store_attainment(attainment_rules[], int),
    sp_compute_attainment(int, int, boolean, int, boolean), sp_compute_all() FROM PUBLIC;
GRANT EXECUTE ON PROCEDURE sp_compute_attainment(int, int, boolean, int, boolean) TO copo_admin, copo_faculty;
GRANT EXECUTE ON PROCEDURE sp_compute_all() TO copo_admin;
