-- 005_attainment.sql
-- The attainment engine (PRD FR-4.2 - FR-4.4, Section 5): sp_compute_attainment.
--   CP010 offering not found   CP011 no rule version   CP012 assessments missing or unlocked
--   CP013 CO not assessed      CP014 bad scenario      42501 not allowed

-- Who may compute an offering: admin, or the faculty member teaching it. The API sets
-- app.role / app.faculty_id per request; maintenance logins (owner, superuser) set no role.
CREATE FUNCTION fn_can_manage_offering(p_offering_id int) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT CASE coalesce(current_setting('app.role', true), '')
        WHEN 'admin'   THEN true
        WHEN 'faculty' THEN EXISTS (
            SELECT 1 FROM course_offering
            WHERE offering_id = p_offering_id
              AND faculty_id = nullif(current_setting('app.faculty_id', true), '')::int)
        WHEN ''        THEN session_user::text = 'copo_owner'
                            OR (SELECT rolsuper FROM pg_roles WHERE rolname = session_user)
        ELSE false
    END
$$;

-- CO rows for one offering under explicit rules (steps 3-6). pct_attained is NULL for a CO
-- that no question tests.
CREATE FUNCTION fn_co_attainment_calc(
    p_offering_id int, p_config_id int,
    p_target numeric, p_l3 numeric, p_l2 numeric, p_l1 numeric,
    p_direct_weight numeric, p_indirect_weight numeric)
RETURNS TABLE (co_id int, co_number smallint, students int, pct_attained numeric,
               direct_level smallint, indirect_level smallint, final_level numeric)
LANGUAGE sql STABLE AS $$
    WITH cos AS (
        SELECT co.co_id, co.co_number
        FROM course_outcome co
        JOIN course_offering o ON o.course_id = co.course_id
        WHERE o.offering_id = p_offering_id
    ),
    direct AS (
        SELECT s.co_id,
               count(*)::int AS students,
               100.0 * count(*) FILTER (WHERE s.pct >= p_target) / count(*) AS pct_attained
        FROM fn_student_co_score(p_offering_id, p_config_id) s
        GROUP BY s.co_id
    ),
    levels AS (
        SELECT c.co_id, c.co_number,
               coalesce(d.students, 0)                       AS students,
               round(d.pct_attained, 2)                      AS pct_attained,
               fn_level(d.pct_attained, p_l3, p_l2, p_l1)    AS direct_level,
               coalesce(ia.level, 0)::smallint               AS indirect_level
        FROM cos c
        LEFT JOIN direct d ON d.co_id = c.co_id
        LEFT JOIN indirect_attainment ia ON ia.offering_id = p_offering_id AND ia.co_id = c.co_id
    )
    SELECT co_id, co_number, students, pct_attained, direct_level, indirect_level,
           round((p_direct_weight * direct_level + p_indirect_weight * indirect_level) / 100.0, 2)
    FROM levels
$$;

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
    v_untested  text;
    v_target numeric; v_l3 numeric; v_l2 numeric; v_l1 numeric;
    v_dw numeric; v_iw numeric; v_co_target numeric;
BEGIN
    -- 0. one run per offering at a time
    SELECT * INTO v_off FROM course_offering WHERE offering_id = p_offering_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Offering % not found', p_offering_id USING ERRCODE = 'CP010';
    END IF;
    IF NOT fn_can_manage_offering(p_offering_id) THEN
        RAISE EXCEPTION 'Not allowed to compute offering %', p_offering_id USING ERRCODE = '42501';
    END IF;
    SELECT program_id INTO v_program FROM course WHERE course_id = v_off.course_id;

    -- rules: the official config, or a what-if scenario on top of its base config
    IF p_persist THEN
        IF p_scenario_id IS NOT NULL THEN
            RAISE EXCEPTION 'A what-if scenario cannot be persisted' USING ERRCODE = 'CP014';
        END IF;
        IF p_config_id IS NULL THEN
            SELECT config_id INTO p_config_id FROM v_offering_config WHERE offering_id = p_offering_id;
        END IF;
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
        v_target := v_cfg.target_pct; v_l3 := v_cfg.l3_pct; v_l2 := v_cfg.l2_pct; v_l1 := v_cfg.l1_pct;
        v_dw := v_cfg.direct_weight; v_iw := v_cfg.indirect_weight; v_co_target := v_cfg.co_target_level;
    ELSE
        v_target := v_scn.target_pct; v_l3 := v_scn.l3_pct; v_l2 := v_scn.l2_pct; v_l1 := v_scn.l1_pct;
        v_dw := v_scn.direct_weight; v_iw := v_scn.indirect_weight; v_co_target := v_scn.co_target_level;
    END IF;

    -- 1. every assessment of the offering must be locked
    SELECT count(*), count(*) FILTER (WHERE NOT locked) INTO v_total, v_unlocked
    FROM assessment WHERE offering_id = p_offering_id;
    IF v_total = 0 THEN
        RAISE EXCEPTION 'Offering % has no assessments', p_offering_id USING ERRCODE = 'CP012';
    END IF;
    IF v_unlocked > 0 THEN
        RAISE EXCEPTION '% of % assessments of offering % are not locked', v_unlocked, v_total, p_offering_id
            USING ERRCODE = 'CP012';
    END IF;

    -- 2-4. CO levels
    DROP TABLE IF EXISTS _co_rows;
    CREATE TEMP TABLE _co_rows ON COMMIT DROP AS
    SELECT * FROM fn_co_attainment_calc(p_offering_id, p_config_id, v_target, v_l3, v_l2, v_l1, v_dw, v_iw);

    SELECT string_agg('CO' || co_number, ', ' ORDER BY co_number) INTO v_untested
    FROM _co_rows WHERE pct_attained IS NULL;
    IF v_untested IS NOT NULL THEN
        RAISE EXCEPTION 'No question tests % of offering %', v_untested, p_offering_id
            USING ERRCODE = 'CP013';
    END IF;

    -- 5. PO per offering = sum(strength x final CO level) / sum(strength)
    DROP TABLE IF EXISTS _po_rows;
    CREATE TEMP TABLE _po_rows ON COMMIT DROP AS
    SELECT m.po_id, round(sum(m.strength * c.final_level) / sum(m.strength), 2) AS attainment
    FROM _co_rows c JOIN co_po_map m ON m.co_id = c.co_id
    GROUP BY m.po_id;

    -- 6. official results, or what-if results only
    IF p_persist THEN
        DELETE FROM co_attainment WHERE offering_id = p_offering_id;
        INSERT INTO co_attainment (offering_id, co_id, config_id, students, pct_attained,
                                   direct_level, indirect_level, final_level)
        SELECT p_offering_id, co_id, p_config_id, students, pct_attained,
               direct_level, indirect_level, final_level
        FROM _co_rows;

        DELETE FROM po_attainment WHERE offering_id = p_offering_id;
        INSERT INTO po_attainment (offering_id, po_id, config_id, attainment)
        SELECT p_offering_id, po_id, p_config_id, attainment FROM _po_rows;

        -- 7. an improvement action for every CO below target
        INSERT INTO improvement_action (co_id, offering_id, description, owner, source)
        SELECT co_id, p_offering_id,
               format('CO%s final level %s is below the target %s', co_number, final_level, v_co_target),
               v_off.faculty_id, 'auto'
        FROM _co_rows WHERE final_level < v_co_target
        ON CONFLICT (offering_id, co_id) WHERE source = 'auto' DO NOTHING;

        -- close the loop: this offering is the follow-up for last year's actions on the same
        -- course and section
        UPDATE improvement_action ia
        SET follow_up_offering_id = p_offering_id
        FROM course_offering prev
        WHERE ia.offering_id = prev.offering_id
          AND ia.follow_up_offering_id IS NULL
          AND prev.course_id = v_off.course_id
          AND prev.section = v_off.section
          AND fn_term_start(prev.academic_year, prev.term) < fn_term_start(v_off.academic_year, v_off.term)
          AND fn_term_start(prev.academic_year, prev.term) >= fn_term_start(v_off.academic_year, v_off.term) - interval '18 months';

        IF p_refresh THEN
            PERFORM fn_refresh_dashboards();
        END IF;
    ELSE
        DELETE FROM whatif_result WHERE scenario_id = p_scenario_id;
        INSERT INTO whatif_result (scenario_id, co_id, pct_attained, direct_level, indirect_level, final_level)
        SELECT p_scenario_id, co_id, pct_attained, direct_level, indirect_level, final_level FROM _co_rows;

        DELETE FROM whatif_po_result WHERE scenario_id = p_scenario_id;
        INSERT INTO whatif_po_result (scenario_id, po_id, attainment)
        SELECT p_scenario_id, po_id, attainment FROM _po_rows;
    END IF;
END $$;

-- Compute every offering whose assessments are all locked, refreshing dashboards once.
CREATE PROCEDURE sp_compute_all()
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_id int;
BEGIN
    FOR v_id IN
        SELECT o.offering_id FROM course_offering o
        WHERE EXISTS (SELECT 1 FROM assessment a WHERE a.offering_id = o.offering_id)
          AND NOT EXISTS (SELECT 1 FROM assessment a WHERE a.offering_id = o.offering_id AND NOT a.locked)
        ORDER BY fn_term_start(o.academic_year, o.term), o.offering_id
    LOOP
        CALL sp_compute_attainment(v_id, p_refresh => false);
    END LOOP;
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
