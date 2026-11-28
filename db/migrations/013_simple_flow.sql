-- 013_simple_flow.sql
-- The simple flow (feat/simple-flow): three CIEs of which each student keeps the best two,
-- experiential learning (EL) as one final mark outside CO attainment, and a final total per student.
--   CP017 EL question tagged to a CO
--
-- assessment.cie_no     The CIE (1-3) a quiz or CIE test belongs to: 'Quiz n' + 'CIE Test n' make up
--                       CIE n. Set when the assessment is created (scan confirm, data generator); a quiz
--                       or test without one stands alone and is never dropped.
-- attainment_config     cie_best_of: how many CIEs count per student (default 2). total_*_weight: the
--                       final total out of 100 (CIE 30, EL 20, SEE 50). Rules are data, like the others.
-- EL                    One mark per student (one question Q1 = the EL maximum). It is never tagged to a
--                       CO (CP017), needs no CO tag to lock, and the score views leave it out, so no CO
--                       gets EL weight. It counts only in the final total.
-- Best of the CIEs      Per student, CIE n's percentage = (quiz n + test n marks) / (quiz n + test n
--                       maximum) over the questions with a mark (AB = 0). The CIEs are ranked by that
--                       percentage, ties to the earlier CIE, and the best cie_best_of are kept. Marks of a
--                       dropped CIE are left out of that student's CO scores (student_component_co_pct)
--                       and of the final total; everything that reads the score views (attainment, root
--                       cause, weak-student lists, early-warning labels, course file) follows.

-- ---------------------------------------------------------------- assessment.cie_no

ALTER TABLE assessment
    ADD COLUMN cie_no smallint CHECK (cie_no BETWEEN 1 AND 3),
    ADD CONSTRAINT assessment_cie_no_type CHECK (cie_no IS NULL OR type IN ('CIE_THEORY', 'CIE_QUIZ')),
    ADD CONSTRAINT assessment_one_part_per_cie UNIQUE (offering_id, type, cie_no);

-- Existing quizzes and tests: the number in 'Quiz n' / 'CIE Test n'. Done before the lock trigger
-- below starts guarding cie_no, so locked assessments are filled too.
UPDATE assessment
SET cie_no = substring(name FROM '([1-3])$')::smallint
WHERE cie_no IS NULL
  AND ((type = 'CIE_QUIZ' AND name ~ '^Quiz [1-3]$') OR (type = 'CIE_THEORY' AND name ~ '^CIE Test [1-3]$'));

-- ---------------------------------------------------------------- rules

ALTER TABLE attainment_config
    ADD COLUMN cie_best_of      smallint  NOT NULL DEFAULT 2  CHECK (cie_best_of BETWEEN 1 AND 3),
    ADD COLUMN total_cie_weight pct_0_100 NOT NULL DEFAULT 30,
    ADD COLUMN total_el_weight  pct_0_100 NOT NULL DEFAULT 20,
    ADD COLUMN total_see_weight pct_0_100 NOT NULL DEFAULT 50,
    ADD CONSTRAINT attainment_config_total_weights
        CHECK (total_cie_weight + total_el_weight + total_see_weight = 100);

-- CO scores: test 30, quiz 20, SEE 50, and no EL weight. Applied to the rule version in force (a
-- database built before this migration); the data generator writes the same weights.
DELETE FROM config_component_weight w USING attainment_config c
WHERE w.config_id = c.config_id AND c.valid_to IS NULL AND w.component = 'EL';
UPDATE config_component_weight w
SET weight_pct = CASE w.component WHEN 'CIE_THEORY' THEN 30 WHEN 'CIE_QUIZ' THEN 20 WHEN 'SEE' THEN 50 END
FROM attainment_config c
WHERE w.config_id = c.config_id AND c.valid_to IS NULL AND w.component IN ('CIE_THEORY', 'CIE_QUIZ', 'SEE');

-- ---------------------------------------------------------------- EL is not tagged to COs

CREATE FUNCTION trg_question_co_not_el() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM assessment_question aq JOIN assessment a USING (assessment_id)
               WHERE aq.question_id = NEW.question_id AND a.type = 'EL') THEN
        RAISE EXCEPTION 'Experiential learning is one final mark; it is not tagged to COs'
            USING ERRCODE = 'CP017';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER question_co_not_el BEFORE INSERT OR UPDATE ON question_co_map
FOR EACH ROW EXECUTE FUNCTION trg_question_co_not_el();

-- The lock trigger of 002, with two changes: an EL question needs no CO tag, and a locked
-- assessment's cie_no is frozen like its other columns (it decides which marks count).
CREATE OR REPLACE FUNCTION trg_assessment_lock() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_expected bigint;
    v_actual bigint;
    v_untagged int;
    v_request int;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.locked THEN
            RAISE EXCEPTION 'Assessment is locked; it cannot be deleted' USING ERRCODE = 'CP001';
        END IF;
        RETURN OLD;
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.locked THEN
            RAISE EXCEPTION 'An assessment is created unlocked and locked once its marks are in'
                USING ERRCODE = 'CP006';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.locked AND NOT OLD.locked THEN
        IF NEW.type <> 'EL' THEN
            SELECT count(*) INTO v_untagged FROM assessment_question aq
            WHERE aq.assessment_id = NEW.assessment_id
              AND NOT EXISTS (SELECT 1 FROM question_co_map m WHERE m.question_id = aq.question_id);
            IF v_untagged > 0 THEN
                RAISE EXCEPTION '% question(s) have no CO tag', v_untagged USING ERRCODE = 'CP006';
            END IF;
        END IF;
        SELECT (SELECT count(*) FROM enrollment WHERE offering_id = NEW.offering_id)
             * (SELECT count(*) FROM assessment_question WHERE assessment_id = NEW.assessment_id)
          INTO v_expected;
        SELECT count(*) INTO v_actual
        FROM student_question_mark m JOIN assessment_question aq USING (question_id)
        WHERE aq.assessment_id = NEW.assessment_id;
        IF v_expected = 0 OR v_actual <> v_expected THEN
            RAISE EXCEPTION 'Cannot lock: % of % marks entered', v_actual, v_expected
                USING ERRCODE = 'CP006';
        END IF;
        NEW.locked_at := now();
    ELSIF OLD.locked AND NOT NEW.locked THEN
        SELECT request_id INTO v_request FROM unlock_request
        WHERE assessment_id = NEW.assessment_id AND status = 'approved'
        ORDER BY decided_at DESC LIMIT 1;
        IF v_request IS NULL THEN
            RAISE EXCEPTION 'Unlocking needs an approved unlock request' USING ERRCODE = 'CP007';
        END IF;
        UPDATE unlock_request SET status = 'used' WHERE request_id = v_request;
        NEW.locked_at := NULL;
    ELSIF OLD.locked AND NEW.locked THEN
        IF (NEW.offering_id, NEW.type, NEW.name, NEW.max_marks, NEW.locked_at, NEW.cie_no)
           IS DISTINCT FROM (OLD.offering_id, OLD.type, OLD.name, OLD.max_marks, OLD.locked_at, OLD.cie_no) THEN
            RAISE EXCEPTION 'Assessment is locked; it cannot be edited' USING ERRCODE = 'CP001';
        END IF;
    END IF;
    RETURN NEW;
END $$;

-- ---------------------------------------------------------------- scores with the best CIEs

-- Per student, CO, component and CIE: CO-weighted marks and maximum, EL left out. A question's CO
-- weights add up to 1, so summing a CIE's rows over its COs gives its plain marks and maximum.
CREATE VIEW student_co_marks WITH (security_invoker = true) AS
SELECT e.usn,
       e.offering_id,
       qcm.co_id,
       a.type AS component,
       a.cie_no,
       sum(coalesce(sqm.marks_obtained, 0) * qcm.weight) AS got,
       sum(aq.max_marks * qcm.weight)                     AS max
FROM student_question_mark sqm
JOIN enrollment e           ON e.enrollment_id = sqm.enrollment_id
JOIN assessment_question aq ON aq.question_id  = sqm.question_id
JOIN assessment a           ON a.assessment_id = aq.assessment_id
JOIN question_co_map qcm    ON qcm.question_id = sqm.question_id
WHERE a.type <> 'EL'
GROUP BY e.usn, e.offering_id, qcm.co_id, a.type, a.cie_no;

-- Step 1 (replaces 003): per student, CO and component, weighted marks / weighted maximum x 100,
-- over the student's kept CIEs only. The ranking is done with window functions partitioned by
-- offering and student, so a filter on offering_id (= or = ANY) still reaches the base tables.
-- Ranking rows: a CIE's percentage over all its COs (cie_got / cie_max); rows without a CIE (SEE,
-- an unnumbered quiz) sort last and are always kept.
CREATE OR REPLACE VIEW student_component_co_pct WITH (security_invoker = true) AS
SELECT k.usn,
       k.offering_id,
       k.co_id,
       k.component,
       100.0 * sum(k.got) / nullif(sum(k.max), 0) AS pct
FROM (
    SELECT c.*,
           dense_rank() OVER (PARTITION BY c.offering_id, c.usn
                              ORDER BY c.cie_no IS NULL, c.cie_got / c.cie_max DESC, c.cie_no) AS cie_place
    FROM (
        SELECT m.*,
               sum(m.got) OVER (PARTITION BY m.offering_id, m.usn, m.cie_no) AS cie_got,
               sum(m.max) OVER (PARTITION BY m.offering_id, m.usn, m.cie_no) AS cie_max
        FROM student_co_marks m
    ) c
) k
LEFT JOIN v_offering_config oc ON oc.offering_id = k.offering_id
LEFT JOIN attainment_config ac ON ac.config_id = oc.config_id
WHERE k.cie_no IS NULL OR k.cie_place <= coalesce(ac.cie_best_of, k.cie_place)
GROUP BY k.usn, k.offering_id, k.co_id, k.component;

-- Per student and CIE: its marks, percentage, place among the student's CIEs and whether it is
-- kept. Same ranking as student_component_co_pct (tested to agree); used for the final total.
CREATE VIEW student_cie_result WITH (security_invoker = true) AS
SELECT r.offering_id,
       r.usn,
       r.cie_no,
       r.got,
       r.max,
       100.0 * r.got / r.max AS pct,
       r.place::int AS place,
       r.place <= coalesce(ac.cie_best_of, r.place) AS kept
FROM (
    SELECT m.offering_id, m.usn, m.cie_no, sum(m.got) AS got, sum(m.max) AS max,
           row_number() OVER (PARTITION BY m.offering_id, m.usn
                              ORDER BY sum(m.got) / sum(m.max) DESC, m.cie_no) AS place
    FROM student_co_marks m
    WHERE m.cie_no IS NOT NULL
    GROUP BY m.offering_id, m.usn, m.cie_no
) r
LEFT JOIN v_offering_config oc ON oc.offering_id = r.offering_id
LEFT JOIN attainment_config ac ON ac.config_id = oc.config_id;

-- Final total per enrolled student, out of 100: (average % of the kept CIEs) x total_cie_weight
-- + EL marks / EL maximum x total_el_weight + SEE marks / SEE maximum x total_see_weight, with the
-- weights of the offering's rule version. While the term runs, only the parts with marks count:
-- out_of is the sum of their weights. AB counts as 0.
CREATE VIEW student_final_marks WITH (security_invoker = true) AS
SELECT e.offering_id,
       e.usn,
       c.cie1_pct, c.cie2_pct, c.cie3_pct,
       coalesce(c.cies, 0) AS cies,
       coalesce(c.dropped_cies, '{}') AS dropped_cies,
       c.cie_pct,
       x.el_got, x.el_max, x.see_got, x.see_max,
       ac.total_cie_weight, ac.total_el_weight, ac.total_see_weight,
       round(coalesce(c.cie_pct / 100.0 * ac.total_cie_weight, 0)
             + coalesce(x.el_got / x.el_max * ac.total_el_weight, 0)
             + coalesce(x.see_got / x.see_max * ac.total_see_weight, 0), 2) AS total,
       (CASE WHEN c.cie_pct IS NOT NULL THEN ac.total_cie_weight ELSE 0 END
        + CASE WHEN x.el_max IS NOT NULL THEN ac.total_el_weight ELSE 0 END
        + CASE WHEN x.see_max IS NOT NULL THEN ac.total_see_weight ELSE 0 END)::numeric AS out_of
FROM enrollment e
LEFT JOIN v_offering_config oc ON oc.offering_id = e.offering_id
LEFT JOIN attainment_config ac ON ac.config_id = oc.config_id
LEFT JOIN (
    SELECT r.offering_id, r.usn,
           max(r.pct) FILTER (WHERE r.cie_no = 1) AS cie1_pct,
           max(r.pct) FILTER (WHERE r.cie_no = 2) AS cie2_pct,
           max(r.pct) FILTER (WHERE r.cie_no = 3) AS cie3_pct,
           count(*)::int AS cies,
           array_agg(r.cie_no ORDER BY r.cie_no) FILTER (WHERE NOT r.kept) AS dropped_cies,
           avg(r.pct) FILTER (WHERE r.kept) AS cie_pct
    FROM student_cie_result r
    GROUP BY r.offering_id, r.usn
) c ON c.offering_id = e.offering_id AND c.usn = e.usn
LEFT JOIN (
    SELECT e2.offering_id, e2.usn,
           sum(coalesce(m.marks_obtained, 0)) FILTER (WHERE a.type = 'EL')  AS el_got,
           sum(aq.max_marks)                  FILTER (WHERE a.type = 'EL')  AS el_max,
           sum(coalesce(m.marks_obtained, 0)) FILTER (WHERE a.type = 'SEE') AS see_got,
           sum(aq.max_marks)                  FILTER (WHERE a.type = 'SEE') AS see_max
    FROM student_question_mark m
    JOIN enrollment e2          ON e2.enrollment_id = m.enrollment_id
    JOIN assessment_question aq ON aq.question_id = m.question_id
    JOIN assessment a           ON a.assessment_id = aq.assessment_id
    WHERE a.type IN ('EL', 'SEE')
    GROUP BY e2.offering_id, e2.usn
) x ON x.offering_id = e.offering_id AND x.usn = e.usn;

-- ---------------------------------------------------------------- per-student root cause

-- For every student of the offering below the CO target (its rule version's target_pct) in a CO:
-- the upstream COs of that CO, walked through co_dependency as fn_root_cause does (strongest path,
-- up to rc_max_depth, rc_depth_decay per extra level), with the student's latest earlier score on
-- each and whether it was below that earlier offering's own target. Runs as owner because the
-- earlier scores are in other faculty's offerings; it returns only the offering's own students.
CREATE FUNCTION fn_student_root_cause(p_offering_id int)
RETURNS TABLE (
    usn               varchar,
    co_id             int,
    pct               numeric,
    target_pct        numeric,
    up_co_id          int,
    up_course_code    text,
    up_co_number      smallint,
    up_statement      text,
    depth             int,
    path_strength     numeric,
    up_offering_id    int,
    up_academic_year  text,
    up_pct            numeric,
    up_target_pct     numeric,
    up_below          boolean)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
#variable_conflict use_column
DECLARE
    v_start date;
    v_cfg   attainment_config%ROWTYPE;
BEGIN
    SELECT fn_term_start(o.academic_year, o.term) INTO v_start
    FROM course_offering o WHERE o.offering_id = p_offering_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Offering % not found', p_offering_id USING ERRCODE = 'CP010';
    END IF;
    IF NOT fn_can_view_offering(p_offering_id) THEN
        RAISE EXCEPTION 'Not allowed to analyse offering %', p_offering_id USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_cfg FROM attainment_config WHERE config_id = fn_result_config(p_offering_id);
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No attainment configuration applies to offering %', p_offering_id
            USING ERRCODE = 'CP011';
    END IF;

    RETURN QUERY
    WITH RECURSIVE weak AS (
        SELECT s.usn, s.co_id, s.pct
        FROM student_co_score_by_config s
        WHERE s.offering_id = p_offering_id AND s.config_id = v_cfg.config_id AND s.pct < v_cfg.target_pct
    ),
    upstream AS (
        SELECT d.co_id AS root, d.prereq_co_id AS up_co, 1 AS depth, d.strength / 3.0 AS path_strength,
               ARRAY[d.co_id, d.prereq_co_id] AS path
        FROM co_dependency d
        WHERE d.co_id IN (SELECT w.co_id FROM weak w)
        UNION ALL
        SELECT u.root, d.prereq_co_id, u.depth + 1, u.path_strength * d.strength / 3.0 * v_cfg.rc_depth_decay,
               u.path || d.prereq_co_id
        FROM upstream u
        JOIN co_dependency d ON d.co_id = u.up_co
        WHERE u.depth < v_cfg.rc_max_depth
          AND d.prereq_co_id <> ALL (u.path)
    ),
    best AS (
        SELECT DISTINCT ON (u.root, u.up_co) u.root, u.up_co, u.depth, u.path_strength
        FROM upstream u
        ORDER BY u.root, u.up_co, u.path_strength DESC, u.depth, u.path
    ),
    up_offering AS (                            -- earlier offerings of the upstream courses
        SELECT o.offering_id, o.academic_year, fn_term_start(o.academic_year, o.term) AS term_start,
               fn_result_config(o.offering_id) AS config_id
        FROM course_offering o
        WHERE o.course_id IN (SELECT co.course_id FROM course_outcome co WHERE co.co_id IN (SELECT b.up_co FROM best b))
          AND fn_term_start(o.academic_year, o.term) < v_start
    ),
    up_scores AS (                              -- each weak student's latest earlier score on an upstream CO
        SELECT DISTINCT ON (s.usn, s.co_id) s.usn, s.co_id, s.offering_id, s.pct, uo.academic_year, uo.config_id
        FROM student_co_score_by_config s
        JOIN up_offering uo ON uo.offering_id = s.offering_id AND uo.config_id = s.config_id
        WHERE s.co_id = ANY (ARRAY(SELECT DISTINCT b.up_co FROM best b))
          AND s.usn = ANY (ARRAY(SELECT DISTINCT w.usn FROM weak w))
          AND s.offering_id = ANY (ARRAY(SELECT offering_id FROM up_offering))
          AND s.config_id = ANY (ARRAY(SELECT DISTINCT config_id FROM up_offering))
        ORDER BY s.usn, s.co_id, uo.term_start DESC, s.offering_id
    )
    SELECT w.usn, w.co_id, round(w.pct, 1), v_cfg.target_pct::numeric,
           b.up_co, c.code::text, co.co_number, co.statement, b.depth, round(b.path_strength, 3),
           us.offering_id, us.academic_year, round(us.pct, 1), cfg.target_pct::numeric, us.pct < cfg.target_pct
    FROM weak w
    JOIN best b            ON b.root = w.co_id
    JOIN course_outcome co ON co.co_id = b.up_co
    JOIN course c          ON c.course_id = co.course_id
    LEFT JOIN up_scores us ON us.usn = w.usn AND us.co_id = b.up_co
    LEFT JOIN attainment_config cfg ON cfg.config_id = us.config_id
    ORDER BY w.usn, w.co_id, b.depth, b.path_strength DESC, b.up_co;
END $$;

-- ---------------------------------------------------------------- privileges

GRANT SELECT ON student_co_marks, student_cie_result, student_final_marks
    TO copo_admin, copo_faculty, copo_coordinator, copo_student;
REVOKE EXECUTE ON FUNCTION fn_student_root_cause(int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fn_student_root_cause(int) TO copo_admin, copo_faculty, copo_coordinator;
