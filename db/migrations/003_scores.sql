-- 003_scores.sql
-- Which rule version applies to an offering, and student-level CO scores (PRD Section 5, steps 1-2).
-- Views are security_invoker so row-level security of the caller still applies.

-- Rule versions are matched on the first day of the offering's term:
-- odd term of 'YYYY-YY' starts 1 Aug YYYY, even term starts 1 Jan YYYY+1.
CREATE FUNCTION fn_term_start(p_academic_year text, p_term text) RETURNS date
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE p_term
        WHEN 'odd'  THEN make_date(left(p_academic_year, 4)::int, 8, 1)
        ELSE             make_date(left(p_academic_year, 4)::int + 1, 1, 1)
    END
$$;

-- LATERAL ... LIMIT 1 rather than a plain join: the planner cannot estimate the range
-- containment and would assume ~1% of offerings have a config, choosing nested loops that made
-- student_co_score ~30x slower. The EXCLUDE constraint guarantees at most one match anyway.
CREATE VIEW v_offering_config WITH (security_invoker = true) AS
SELECT o.offering_id, c.config_id
FROM course_offering o
JOIN course cr ON cr.course_id = o.course_id
CROSS JOIN LATERAL (
    SELECT ac.config_id
    FROM attainment_config ac
    WHERE ac.program_id = cr.program_id
      AND daterange(ac.valid_from, ac.valid_to) @> fn_term_start(o.academic_year, o.term)
    LIMIT 1
) c;

-- Step 1: per student, CO and component, weighted marks / weighted maximum x 100.
-- Absent marks are NULL and count as 0 (S6).
CREATE VIEW student_component_co_pct WITH (security_invoker = true) AS
SELECT e.usn,
       e.offering_id,
       qcm.co_id,
       a.type AS component,
       100.0 * sum(coalesce(sqm.marks_obtained, 0) * qcm.weight)
             / nullif(sum(aq.max_marks * qcm.weight), 0) AS pct
FROM student_question_mark sqm
JOIN enrollment e           ON e.enrollment_id = sqm.enrollment_id
JOIN assessment_question aq ON aq.question_id  = sqm.question_id
JOIN assessment a           ON a.assessment_id = aq.assessment_id
JOIN question_co_map qcm    ON qcm.question_id = sqm.question_id
GROUP BY e.usn, e.offering_id, qcm.co_id, a.type;

-- The rule versions an offering is scored under: its own (v_offering_config), the base config of
-- any what-if scenario on it, and the one its official results were computed with (which differs
-- when a version is added for its term later). Scoring only these, rather than every config,
-- keeps the shared view below as fast as a formula written for the offering's own config.
CREATE VIEW v_scoring_config WITH (security_invoker = true) AS
SELECT offering_id, config_id FROM v_offering_config
UNION
SELECT offering_id, base_config_id FROM whatif_scenario
UNION
SELECT DISTINCT offering_id, config_id FROM co_attainment;

-- Step 2: sum(weight x component %) / sum(weight) over the components that test the CO, per
-- applicable rule version. This is the only copy of the formula: the engine reads it for the
-- offering's (or a what-if scenario's) config, student_co_score for each offering's own config.
-- Filters on offering_id, co_id or config_id are pushed down into the aggregation.
CREATE VIEW student_co_score_by_config WITH (security_invoker = true) AS
SELECT s.usn,
       s.offering_id,
       s.co_id,
       w.config_id,
       sum(w.weight_pct * s.pct) / sum(w.weight_pct) AS pct
FROM student_component_co_pct s
JOIN v_scoring_config k        ON k.offering_id = s.offering_id
JOIN config_component_weight w ON w.config_id = k.config_id AND w.component = s.component
GROUP BY s.usn, s.offering_id, s.co_id, w.config_id;

-- Step 2 for an explicit rule version (the offering's own, or a scenario's base config).
CREATE FUNCTION fn_student_co_score(p_offering_id int, p_config_id int)
RETURNS TABLE (usn varchar, co_id int, pct numeric)
LANGUAGE sql STABLE AS $$
    SELECT s.usn, s.co_id, s.pct
    FROM student_co_score_by_config s
    WHERE s.offering_id = p_offering_id AND s.config_id = p_config_id
$$;

-- Step 2 with each offering's own rule version; reused by analytics and root-cause queries.
CREATE VIEW student_co_score WITH (security_invoker = true) AS
SELECT s.usn, s.offering_id, s.co_id, s.pct
FROM student_co_score_by_config s
JOIN v_offering_config oc ON oc.offering_id = s.offering_id AND oc.config_id = s.config_id;

-- Step 3 threshold mapping, shared by direct and indirect attainment.
CREATE FUNCTION fn_level(p_pct numeric, p_l3 numeric, p_l2 numeric, p_l1 numeric) RETURNS smallint
LANGUAGE sql IMMUTABLE AS $$
    SELECT (CASE WHEN p_pct >= p_l3 THEN 3
                 WHEN p_pct >= p_l2 THEN 2
                 WHEN p_pct >= p_l1 THEN 1
                 ELSE 0 END)::smallint
$$;
