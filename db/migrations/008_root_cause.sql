-- 008_root_cause.sql
-- Prerequisite-aware root-cause analysis (PRD FR-6.2, Section 11.2).
-- For a CO that missed its target, walk co_dependency upstream (up to rc_max_depth levels), and
-- score each upstream CO by path strength x the Pearson correlation between the same students'
-- scores on the upstream CO and on the weak CO. Path strength is the product of strength/3 along
-- the path, times rc_depth_decay for every level beyond the first, so a direct prerequisite
-- outranks an indirect one with the same evidence. Candidates need n >= rc_min_n and a defined
-- r >= rc_min_r. All of these come from the rule version of the weak offering's official results
-- (or the version valid for its term, before it is computed). The output is correlational
-- evidence, not proof of cause.
--   CP010 offering not found   CP011 no rule version   CP016 CO has no shortfall to explain
--   22023 CO not of the offering's course              42501 not allowed
--
-- Runs as owner because the evidence spans other faculty's offerings; it returns only
-- aggregates, and only to callers who may view the weak offering.

-- Who may view an offering's analysis: whoever may manage it, and coordinators (read-only).
CREATE FUNCTION fn_can_view_offering(p_offering_id int) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT fn_can_manage_offering(p_offering_id) OR coalesce(fn_app_role() = 'coordinator', false)
$$;

-- The rule version an offering's results are judged by: the one its official results were computed
-- with, else the one valid for its term.
CREATE FUNCTION fn_result_config(p_offering_id int) RETURNS int
LANGUAGE sql STABLE SET search_path = public, pg_temp AS $$
    SELECT coalesce((SELECT config_id FROM co_attainment WHERE offering_id = p_offering_id LIMIT 1),
                    (SELECT config_id FROM v_offering_config WHERE offering_id = p_offering_id))
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
#variable_conflict use_column
DECLARE
    v_start    date;
    v_cfg      attainment_config%ROWTYPE;
    v_up       int[];
    v_depth    int[];
    v_strength numeric[];
    v_usns     text[];
    v_pcts     numeric[];
BEGIN
    SELECT fn_term_start(o.academic_year, o.term) INTO v_start
    FROM course_offering o WHERE o.offering_id = p_offering_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Offering % not found', p_offering_id USING ERRCODE = 'CP010';
    END IF;
    IF NOT fn_can_view_offering(p_offering_id) THEN
        RAISE EXCEPTION 'Not allowed to analyse offering %', p_offering_id USING ERRCODE = '42501';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM course_outcome co JOIN course_offering o ON o.course_id = co.course_id
                   WHERE o.offering_id = p_offering_id AND co.co_id = p_co_id) THEN
        RAISE EXCEPTION 'CO % is not an outcome of offering %', p_co_id, p_offering_id USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_cfg FROM attainment_config WHERE config_id = fn_result_config(p_offering_id);
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No attainment configuration applies to offering %', p_offering_id
            USING ERRCODE = 'CP011';
    END IF;

    -- Strongest path to each upstream CO; ties go to the shallower path, then the lower CO ids.
    WITH RECURSIVE upstream AS (
        SELECT d.prereq_co_id AS up_co, 1 AS depth, d.strength / 3.0 AS path_strength,
               ARRAY[d.co_id, d.prereq_co_id] AS path
        FROM co_dependency d
        WHERE d.co_id = p_co_id
        UNION ALL
        SELECT d.prereq_co_id, u.depth + 1, u.path_strength * d.strength / 3.0 * v_cfg.rc_depth_decay,
               u.path || d.prereq_co_id
        FROM upstream u
        JOIN co_dependency d ON d.co_id = u.up_co
        WHERE u.depth < v_cfg.rc_max_depth
          AND d.prereq_co_id <> ALL (u.path)    -- no revisits
    ),
    best AS (
        SELECT DISTINCT ON (u.up_co) u.up_co, u.depth, u.path_strength
        FROM upstream u
        ORDER BY u.up_co, u.path_strength DESC, u.depth, u.path
    )
    SELECT array_agg(b.up_co ORDER BY b.up_co), array_agg(b.depth ORDER BY b.up_co),
           array_agg(b.path_strength ORDER BY b.up_co)
    INTO v_up, v_depth, v_strength
    FROM best b;

    -- The weak offering's students, scored under the rule version of its results. Collected into
    -- arrays first so the filters below reach the indexes instead of scoring every mark.
    SELECT array_agg(s.usn ORDER BY s.usn), array_agg(s.pct ORDER BY s.usn) INTO v_usns, v_pcts
    FROM student_co_score_by_config s
    WHERE s.offering_id = p_offering_id AND s.co_id = p_co_id AND s.config_id = v_cfg.config_id;

    RETURN QUERY
    WITH cand AS (
        SELECT * FROM unnest(v_up, v_depth, v_strength) AS c(up_co, depth, path_strength)
    ),
    weak AS (
        SELECT * FROM unnest(v_usns, v_pcts) AS w(usn, pct)
    ),
    up_offering AS (                            -- earlier offerings of the upstream courses
        SELECT o.offering_id, fn_term_start(o.academic_year, o.term) AS term_start,
               fn_result_config(o.offering_id) AS config_id
        FROM course_offering o
        WHERE o.course_id IN (SELECT co.course_id FROM course_outcome co WHERE co.co_id = ANY (v_up))
          AND fn_term_start(o.academic_year, o.term) < v_start
    ),
    up_scores AS (                              -- each weak student's latest earlier score on the upstream CO
        SELECT DISTINCT ON (s.usn, s.co_id) s.usn, s.co_id, s.offering_id, s.pct
        FROM student_co_score_by_config s
        JOIN up_offering uo ON uo.offering_id = s.offering_id AND uo.config_id = s.config_id
        WHERE s.co_id = ANY (v_up)
          AND s.usn = ANY (v_usns)
          AND s.offering_id = ANY (ARRAY(SELECT offering_id FROM up_offering))
          AND s.config_id = ANY (ARRAY(SELECT DISTINCT config_id FROM up_offering))
        ORDER BY s.usn, s.co_id, uo.term_start DESC, s.offering_id
    ),
    evidence AS (                               -- every candidate, also those with no earlier scores
        SELECT c.up_co, c.depth, c.path_strength,
               corr(u.pct, w.pct)::numeric AS r,
               count(w.usn)::int AS n
        FROM cand c
        LEFT JOIN up_scores u ON u.co_id = c.up_co
        LEFT JOIN weak w      ON w.usn = u.usn
        GROUP BY c.up_co, c.depth, c.path_strength
    ),
    up_level AS (                               -- upstream CO's own results, against its own targets
        SELECT u.co_id, round(avg(ca.final_level), 2) AS final_level,
               round(avg(greatest(0, cfg.co_target_level - ca.final_level)), 2) AS shortfall
        FROM (SELECT DISTINCT co_id, offering_id FROM up_scores) u
        JOIN co_attainment ca      ON ca.offering_id = u.offering_id AND ca.co_id = u.co_id
        JOIN attainment_config cfg ON cfg.config_id = ca.config_id
        GROUP BY u.co_id
    ),
    scored AS (
        SELECT e.*, l.final_level, l.shortfall,
               (e.n >= v_cfg.rc_min_n AND e.r IS NOT NULL AND e.r >= v_cfg.rc_min_r) AS ok
        FROM evidence e
        LEFT JOIN up_level l ON l.co_id = e.up_co
    )
    SELECT s.up_co, c.code::text, co.co_number, co.statement, s.depth,
           round(s.path_strength, 3), round(s.r, 2), s.n, s.final_level, s.shortfall,
           s.ok,
           CASE WHEN s.ok THEN (rank() OVER (PARTITION BY s.ok ORDER BY s.path_strength * s.r DESC))::int END
    FROM scored s
    JOIN course_outcome co ON co.co_id = s.up_co
    JOIN course c          ON c.course_id = co.course_id
    ORDER BY s.ok DESC, s.path_strength * s.r DESC NULLS LAST, s.depth, s.up_co;
END $$;

-- An open root-cause action per (offering, CO) at most: repeated requests return the same one.
CREATE UNIQUE INDEX improvement_action_root_cause_uq ON improvement_action (offering_id, co_id)
    WHERE source = 'root_cause' AND status <> 'done';

-- Pre-fill an improvement action from the top-ranked cause (FR-6.2) for a CO whose official result
-- is below its target. Returns the action id (an existing open one if there is one), or NULL
-- when no candidate passes the thresholds.
CREATE FUNCTION fn_root_cause_action(p_offering_id int, p_co_id int) RETURNS int
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_top   record;
    v_id    int;
    v_below boolean;
BEGIN
    IF NOT fn_can_manage_offering(p_offering_id) THEN
        RAISE EXCEPTION 'Not allowed to add actions to offering %', p_offering_id USING ERRCODE = '42501';
    END IF;
    SELECT ca.final_level < cfg.co_target_level INTO v_below
    FROM co_attainment ca JOIN attainment_config cfg ON cfg.config_id = ca.config_id
    WHERE ca.offering_id = p_offering_id AND ca.co_id = p_co_id;
    IF v_below IS NULL THEN
        RAISE EXCEPTION 'CO % of offering % has no official result yet', p_co_id, p_offering_id
            USING ERRCODE = 'CP016';
    ELSIF NOT v_below THEN
        RAISE EXCEPTION 'CO % of offering % meets its target', p_co_id, p_offering_id USING ERRCODE = 'CP016';
    END IF;

    SELECT action_id INTO v_id FROM improvement_action
    WHERE offering_id = p_offering_id AND co_id = p_co_id AND source = 'root_cause' AND status <> 'done';
    IF FOUND THEN
        RETURN v_id;
    END IF;

    SELECT * INTO v_top FROM fn_root_cause(p_offering_id, p_co_id) r
    WHERE r.likely_cause_rank = 1 ORDER BY r.depth, r.up_co_id LIMIT 1;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    INSERT INTO improvement_action (co_id, offering_id, description, owner, source)
    SELECT p_co_id, p_offering_id,
           format('Review bridge content for %s CO%s (likely upstream cause, r = %s, n = %s)',
                  v_top.up_course_code, v_top.up_co_number, v_top.correlation, v_top.n),
           o.faculty_id, 'root_cause'
    FROM course_offering o WHERE o.offering_id = p_offering_id
    ON CONFLICT (offering_id, co_id) WHERE source = 'root_cause' AND status <> 'done' DO NOTHING
    RETURNING action_id INTO v_id;
    IF v_id IS NULL THEN                       -- a concurrent call added it first
        SELECT action_id INTO v_id FROM improvement_action
        WHERE offering_id = p_offering_id AND co_id = p_co_id AND source = 'root_cause' AND status <> 'done';
    END IF;
    RETURN v_id;
END $$;

REVOKE EXECUTE ON FUNCTION fn_can_view_offering(int), fn_result_config(int), fn_root_cause(int, int),
    fn_root_cause_action(int, int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fn_root_cause(int, int) TO copo_admin, copo_faculty, copo_coordinator;
GRANT EXECUTE ON FUNCTION fn_root_cause_action(int, int) TO copo_admin, copo_faculty;
