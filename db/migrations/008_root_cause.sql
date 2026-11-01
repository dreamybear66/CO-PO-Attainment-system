-- 008_root_cause.sql
-- Prerequisite-aware root-cause analysis (PRD FR-6.2, Section 11.2).
-- For a CO that missed its target, walk co_dependency upstream (up to 3 levels), and score each
-- upstream CO by path strength x the Pearson correlation between the same students' scores on
-- the upstream CO and on the weak CO. Candidates need n >= rc_min_n and r >= rc_min_r from the
-- offering's rule version. The output is correlational evidence, not proof of cause.
--
-- Runs as owner because the evidence spans other faculty's offerings; it returns only
-- aggregates, and only to callers who may view the weak offering.

CREATE FUNCTION fn_can_view_offering(p_offering_id int) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT CASE coalesce(current_setting('app.role', true), '')
        WHEN 'admin'       THEN true
        WHEN 'coordinator' THEN true
        WHEN 'faculty'     THEN EXISTS (
            SELECT 1 FROM course_offering
            WHERE offering_id = p_offering_id
              AND faculty_id = nullif(current_setting('app.faculty_id', true), '')::int)
        WHEN ''            THEN session_user::text = 'copo_owner'
                                OR (SELECT rolsuper FROM pg_roles WHERE rolname = session_user)
        ELSE false
    END
$$;

CREATE FUNCTION fn_root_cause(p_offering_id int, p_co_id int)
RETURNS TABLE (
    up_co_id          int,
    up_course_code    text,
    up_co_number      smallint,
    up_statement      text,
    depth             int,
    path_strength     numeric,
    correlation       numeric,
    n                 int,
    up_final_level    numeric,
    up_shortfall      numeric,
    passes            boolean,
    likely_cause_rank int)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_start  date;
    v_cfg    attainment_config%ROWTYPE;
BEGIN
    IF NOT fn_can_view_offering(p_offering_id) THEN
        RAISE EXCEPTION 'Not allowed to analyse offering %', p_offering_id USING ERRCODE = '42501';
    END IF;
    SELECT fn_term_start(o.academic_year, o.term) INTO v_start
    FROM course_offering o WHERE o.offering_id = p_offering_id;
    SELECT c.* INTO v_cfg FROM attainment_config c
    JOIN v_offering_config oc ON oc.config_id = c.config_id
    WHERE oc.offering_id = p_offering_id;

    RETURN QUERY
    WITH RECURSIVE upstream AS (
        SELECT d.prereq_co_id AS up_co, 1 AS depth, d.strength / 3.0 AS path_strength,
               ARRAY[d.co_id, d.prereq_co_id] AS path
        FROM co_dependency d
        WHERE d.co_id = p_co_id
        UNION ALL
        SELECT d.prereq_co_id, u.depth + 1, u.path_strength * d.strength / 3.0, u.path || d.prereq_co_id
        FROM upstream u
        JOIN co_dependency d ON d.co_id = u.up_co
        WHERE u.depth < 3                       -- depth limit
          AND d.prereq_co_id <> ALL (u.path)    -- and no revisits
    ),
    best AS (                                   -- strongest path to each upstream CO
        SELECT DISTINCT ON (u.up_co) u.up_co, u.depth, u.path_strength
        FROM upstream u
        ORDER BY u.up_co, u.path_strength DESC
    ),
    weak AS (
        SELECT s.usn, s.pct FROM student_co_score s
        WHERE s.offering_id = p_offering_id AND s.co_id = p_co_id
    ),
    up_scores AS (                              -- each student's latest earlier score on the upstream CO
        SELECT DISTINCT ON (s.usn, s.co_id) s.usn, s.co_id, s.offering_id, s.pct
        FROM student_co_score s
        JOIN course_offering o ON o.offering_id = s.offering_id
        WHERE s.co_id IN (SELECT b.up_co FROM best b)
          AND s.usn IN (SELECT w.usn FROM weak w)
          AND fn_term_start(o.academic_year, o.term) < v_start
        ORDER BY s.usn, s.co_id, fn_term_start(o.academic_year, o.term) DESC
    ),
    evidence AS (
        SELECT b.up_co, b.depth, b.path_strength,
               corr(u.pct, w.pct)::numeric AS r,
               count(*)::int AS n
        FROM best b
        JOIN up_scores u ON u.co_id = b.up_co
        JOIN weak w      ON w.usn = u.usn
        GROUP BY b.up_co, b.depth, b.path_strength
    ),
    up_level AS (                               -- upstream CO's own attainment in those offerings
        SELECT u.co_id, round(avg(ca.final_level), 2) AS final_level
        FROM (SELECT DISTINCT co_id, offering_id FROM up_scores) u
        JOIN co_attainment ca ON ca.offering_id = u.offering_id AND ca.co_id = u.co_id
        GROUP BY u.co_id
    ),
    scored AS (
        SELECT e.*, l.final_level,
               (e.n >= v_cfg.rc_min_n AND coalesce(e.r, 0) >= v_cfg.rc_min_r) AS ok
        FROM evidence e
        LEFT JOIN up_level l ON l.co_id = e.up_co
    )
    SELECT s.up_co, c.code, co.co_number, co.statement, s.depth,
           round(s.path_strength, 3), round(s.r, 2), s.n, s.final_level,
           round(greatest(0, v_cfg.co_target_level - s.final_level), 2),
           s.ok,
           CASE WHEN s.ok THEN (rank() OVER (PARTITION BY s.ok ORDER BY s.path_strength * s.r DESC))::int END
    FROM scored s
    JOIN course_outcome co ON co.co_id = s.up_co
    JOIN course c          ON c.course_id = co.course_id
    ORDER BY s.ok DESC, s.path_strength * coalesce(s.r, 0) DESC;
END $$;

-- Pre-fill an improvement action from the top-ranked cause (FR-6.2). Returns the action id,
-- or NULL when no candidate passes the thresholds.
CREATE FUNCTION fn_root_cause_action(p_offering_id int, p_co_id int) RETURNS int
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_top record;
    v_owner int;
    v_id int;
BEGIN
    IF NOT fn_can_manage_offering(p_offering_id) THEN
        RAISE EXCEPTION 'Not allowed to add actions to offering %', p_offering_id USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_top FROM fn_root_cause(p_offering_id, p_co_id) WHERE likely_cause_rank = 1 LIMIT 1;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    SELECT faculty_id INTO v_owner FROM course_offering WHERE offering_id = p_offering_id;
    INSERT INTO improvement_action (co_id, offering_id, description, owner, source)
    VALUES (p_co_id, p_offering_id,
            format('Review bridge content for %s CO%s (likely upstream cause, r = %s, n = %s)',
                   v_top.up_course_code, v_top.up_co_number, v_top.correlation, v_top.n),
            v_owner, 'root_cause')
    RETURNING action_id INTO v_id;
    RETURN v_id;
END $$;
