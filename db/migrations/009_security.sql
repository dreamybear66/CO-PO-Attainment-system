-- 009_security.sql
-- Role-based access and row-level security (PRD Section 3, FR-7.1, NFR-5).
--
-- The API logs in as copo_api (NOINHERIT) and, per request, runs
--   SET LOCAL ROLE copo_<role>;  set_config('app.role' | 'app.faculty_id' | 'app.usn' | 'app.user', ..., true)
-- copo_owner owns every object and bypasses RLS; it is used only by migrations and jobs.
--
--   copo_admin        everything
--   copo_faculty      own offerings: marks, assessments, actions, scenarios; COs/maps of courses taught
--   copo_coordinator  read-only everywhere
--   copo_student      own enrolments, marks and CO scores

-- ---------------------------------------------------------------- session helpers

CREATE FUNCTION fn_my_faculty() RETURNS int LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('app.faculty_id', true), '')::int
$$;

CREATE FUNCTION fn_my_usn() RETURNS text LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('app.usn', true), '')
$$;

-- The caller's own rows, as sets. Policies use them as `col IN (SELECT fn_my_x())`, which the
-- planner runs once per query as a hashed subplan; a per-row function call made a student's score
-- query check every mark in the database (seconds instead of milliseconds). They run as owner so a
-- policy never recurses through another table's policy. A faculty session has no usn and a student
-- session no faculty_id, so each union contributes one side only.
CREATE FUNCTION fn_my_offerings() RETURNS SETOF int
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT offering_id FROM course_offering WHERE faculty_id = fn_my_faculty()
    UNION
    SELECT offering_id FROM enrollment WHERE usn = fn_my_usn()
$$;

CREATE FUNCTION fn_my_enrollments() RETURNS SETOF int
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT e.enrollment_id FROM enrollment e JOIN course_offering o ON o.offering_id = e.offering_id
    WHERE o.faculty_id = fn_my_faculty()
    UNION
    SELECT enrollment_id FROM enrollment WHERE usn = fn_my_usn()
$$;

CREATE FUNCTION fn_my_assessments() RETURNS SETOF int
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT assessment_id FROM assessment WHERE offering_id IN (SELECT fn_my_offerings())
$$;

CREATE FUNCTION fn_my_questions() RETURNS SETOF int
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT question_id FROM assessment_question WHERE assessment_id IN (SELECT fn_my_assessments())
$$;

CREATE FUNCTION fn_my_courses() RETURNS SETOF int
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT DISTINCT course_id FROM course_offering WHERE faculty_id = fn_my_faculty()
$$;

CREATE FUNCTION fn_my_cos() RETURNS SETOF int
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT co_id FROM course_outcome WHERE course_id IN (SELECT fn_my_courses())
$$;

CREATE FUNCTION fn_my_scenarios() RETURNS SETOF int
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT scenario_id FROM whatif_scenario WHERE offering_id IN (SELECT fn_my_offerings())
$$;

-- Login: the only way to read password hashes, granted to the API login alone.
CREATE FUNCTION fn_login_lookup(p_username text)
RETURNS TABLE (user_id int, password_hash text, role text, faculty_id int, usn varchar)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT user_id, password_hash, role, faculty_id, usn FROM app_user WHERE username = p_username
$$;

-- Programme-wide figures (FR-4.5, FR-6.1). Staff see the same programme numbers whatever they teach,
-- so these run as owner, past row-level security, and return aggregates only. Each year is judged
-- against the targets of the rule versions its results used (averaged like the values).
CREATE FUNCTION fn_staff_only() RETURNS void LANGUAGE plpgsql STABLE AS $$
BEGIN
    IF coalesce(fn_app_role() NOT IN ('admin', 'faculty', 'coordinator', ''), true) THEN
        RAISE EXCEPTION 'Programme figures are for staff' USING ERRCODE = '42501';
    END IF;
END $$;

CREATE FUNCTION fn_program_po_attainment()
RETURNS TABLE (po_id int, po_code text, type text, statement text, academic_year text,
               offerings int, attainment numeric, target numeric)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    PERFORM fn_staff_only();
    RETURN QUERY
    SELECT po.po_id, po.code::text, po.type::text, po.statement::text, o.academic_year::text,
           count(*)::int, round(avg(pa.attainment), 2), round(avg(cfg.po_target_level), 2)
    FROM po_attainment pa
    JOIN course_offering o     ON o.offering_id = pa.offering_id
    JOIN program_outcome po    ON po.po_id = pa.po_id
    JOIN attainment_config cfg ON cfg.config_id = pa.config_id
    GROUP BY po.po_id, po.code, po.type, po.statement, o.academic_year
    ORDER BY o.academic_year, po.po_id;
END $$;

CREATE FUNCTION fn_weakest_cos(p_academic_year text, p_limit int)
RETURNS TABLE (course_id int, code text, title text, co_id int, co_number smallint, statement text,
               final_level numeric, sections int, target numeric, weakest_rank int)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    PERFORM fn_staff_only();
    RETURN QUERY
    WITH yearly AS (
        SELECT c.course_id, c.code::text AS code, c.title::text AS title, co.co_id, co.co_number,
               co.statement::text AS statement, round(avg(ca.final_level), 2) AS final_level,
               count(*)::int AS sections, round(avg(cfg.co_target_level), 2) AS target
        FROM co_attainment ca
        JOIN course_offering o     ON o.offering_id = ca.offering_id
        JOIN course c              ON c.course_id = o.course_id
        JOIN course_outcome co     ON co.co_id = ca.co_id
        JOIN attainment_config cfg ON cfg.config_id = ca.config_id
        WHERE o.academic_year = p_academic_year
        GROUP BY c.course_id, c.code, c.title, co.co_id, co.co_number, co.statement
    )
    SELECT r.* FROM (SELECT y.*, (rank() OVER (ORDER BY y.final_level))::int AS weakest_rank FROM yearly y) r
    WHERE r.weakest_rank <= p_limit
    ORDER BY r.weakest_rank, r.code, r.co_number;
END $$;

CREATE FUNCTION fn_result_years() RETURNS SETOF text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    PERFORM fn_staff_only();
    RETURN QUERY SELECT DISTINCT o.academic_year::text FROM co_attainment ca
                 JOIN course_offering o ON o.offering_id = ca.offering_id ORDER BY 1 DESC;
END $$;

-- ---------------------------------------------------------------- privileges

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
REVOKE EXECUTE ON ALL PROCEDURES IN SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO copo_admin, copo_faculty, copo_coordinator, copo_student, copo_api;

-- Helpers (policies, triggers, views) run as the caller, so the application roles get every
-- function; the routines earlier migrations restricted keep their own grants, re-applied below.
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO copo_admin, copo_faculty, copo_coordinator, copo_student;
REVOKE EXECUTE ON FUNCTION fn_login_lookup(text) FROM copo_admin, copo_faculty, copo_coordinator, copo_student;
GRANT EXECUTE ON FUNCTION fn_login_lookup(text) TO copo_api;
REVOKE EXECUTE ON FUNCTION fn_refresh_dashboards() FROM copo_faculty, copo_coordinator, copo_student;
REVOKE EXECUTE ON FUNCTION fn_co_attainment_calc(attainment_rules[])
    FROM copo_admin, copo_faculty, copo_coordinator, copo_student;
REVOKE EXECUTE ON FUNCTION fn_audit_denied(text, jsonb, jsonb) FROM copo_coordinator, copo_student;
REVOKE EXECUTE ON FUNCTION fn_root_cause(int, int) FROM copo_student;
REVOKE EXECUTE ON FUNCTION fn_root_cause_action(int, int) FROM copo_coordinator, copo_student;
REVOKE EXECUTE ON FUNCTION fn_program_po_attainment(), fn_weakest_cos(text, int), fn_result_years()
    FROM copo_student;
GRANT EXECUTE ON PROCEDURE sp_compute_attainment(int, int, boolean, int, boolean) TO copo_admin, copo_faculty;
GRANT EXECUTE ON PROCEDURE sp_compute_all() TO copo_admin;

-- admin: everything except the audit internals and the migration ledger
GRANT ALL ON ALL TABLES IN SCHEMA public TO copo_admin;
REVOKE ALL ON audit_outbox, schema_migrations FROM copo_admin;
GRANT SELECT ON audit_outbox TO copo_admin;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO copo_admin, copo_faculty;

-- coordinator: read-only
GRANT SELECT ON ALL TABLES IN SCHEMA public TO copo_coordinator;
REVOKE SELECT ON app_user, audit_outbox, schema_migrations FROM copo_coordinator;

-- faculty
GRANT SELECT ON department, program, faculty, student, course, course_prerequisite, course_offering,
    enrollment, program_outcome, course_outcome, co_po_map, co_dependency, attainment_config,
    config_component_weight, assessment, assessment_question, question_co_map, student_question_mark,
    co_attainment, po_attainment, indirect_attainment, improvement_action, whatif_scenario,
    whatif_result, whatif_po_result, unlock_request
    TO copo_faculty;
GRANT INSERT, UPDATE, DELETE ON course_outcome, co_po_map, co_dependency, assessment,
    assessment_question, question_co_map, student_question_mark, whatif_scenario TO copo_faculty;
GRANT INSERT, UPDATE ON improvement_action TO copo_faculty;
GRANT INSERT ON unlock_request TO copo_faculty;

-- student
GRANT SELECT ON department, program, course, course_offering, program_outcome, course_outcome,
    attainment_config, config_component_weight, student, enrollment, assessment, assessment_question,
    question_co_map, student_question_mark
    TO copo_student;

-- views and materialized views (views are security_invoker, so RLS still applies). The score views
-- also read the configs of official results and scenarios: students may read those tables, and
-- with no student policy on them see none of their rows.
GRANT SELECT ON v_offering_config, v_scoring_config, student_component_co_pct, student_co_score_by_config,
    student_co_score TO copo_admin, copo_faculty, copo_coordinator, copo_student;
GRANT SELECT ON co_attainment, whatif_scenario TO copo_student;
GRANT SELECT ON v_program_po_attainment, v_improvement_followup TO copo_admin, copo_faculty, copo_coordinator;
-- materialized views cannot carry RLS: admin and coordinator only
GRANT SELECT ON mv_co_po_heatmap, mv_co_trend TO copo_admin, copo_coordinator;

-- ---------------------------------------------------------------- row-level security

-- Every RLS table: admin all, coordinator read all.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'student', 'enrollment', 'assessment', 'assessment_question', 'question_co_map',
        'student_question_mark', 'course_outcome', 'co_po_map', 'co_dependency',
        'co_attainment', 'po_attainment', 'indirect_attainment', 'improvement_action',
        'whatif_scenario', 'whatif_result', 'whatif_po_result', 'unlock_request']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY admin_all ON %I TO copo_admin USING (true) WITH CHECK (true)', t);
        EXECUTE format('CREATE POLICY coordinator_read ON %I FOR SELECT TO copo_coordinator USING (true)', t);
    END LOOP;
END $$;

-- students: faculty see the directory; a student sees only themself
CREATE POLICY faculty_read ON student FOR SELECT TO copo_faculty USING (true);
CREATE POLICY student_self ON student FOR SELECT TO copo_student USING (usn = fn_my_usn());

-- enrolments
CREATE POLICY faculty_own ON enrollment FOR SELECT TO copo_faculty USING (offering_id IN (SELECT fn_my_offerings()));
CREATE POLICY student_own ON enrollment FOR SELECT TO copo_student USING (usn = fn_my_usn());

-- assessments, questions, tags: faculty manage their offerings; students read their offerings'
CREATE POLICY faculty_own ON assessment TO copo_faculty
    USING (offering_id IN (SELECT fn_my_offerings())) WITH CHECK (offering_id IN (SELECT fn_my_offerings()));
CREATE POLICY student_enrolled ON assessment FOR SELECT TO copo_student USING (offering_id IN (SELECT fn_my_offerings()));

CREATE POLICY faculty_own ON assessment_question TO copo_faculty
    USING (assessment_id IN (SELECT fn_my_assessments())) WITH CHECK (assessment_id IN (SELECT fn_my_assessments()));
CREATE POLICY student_enrolled ON assessment_question FOR SELECT TO copo_student
    USING (assessment_id IN (SELECT fn_my_assessments()));

CREATE POLICY faculty_own ON question_co_map TO copo_faculty
    USING (question_id IN (SELECT fn_my_questions())) WITH CHECK (question_id IN (SELECT fn_my_questions()));
CREATE POLICY student_enrolled ON question_co_map FOR SELECT TO copo_student
    USING (question_id IN (SELECT fn_my_questions()));

-- marks (PRD Section 10: faculty see only their own offerings; a student only their own marks)
CREATE POLICY faculty_own_offerings ON student_question_mark TO copo_faculty
    USING (enrollment_id IN (SELECT fn_my_enrollments())) WITH CHECK (enrollment_id IN (SELECT fn_my_enrollments()));
CREATE POLICY student_own ON student_question_mark FOR SELECT TO copo_student
    USING (enrollment_id IN (SELECT fn_my_enrollments()));

-- outcome definitions: everyone reads; faculty edit those of courses they teach
CREATE POLICY everyone_reads ON course_outcome FOR SELECT TO copo_faculty, copo_student USING (true);
CREATE POLICY faculty_insert ON course_outcome FOR INSERT TO copo_faculty WITH CHECK (course_id IN (SELECT fn_my_courses()));
CREATE POLICY faculty_update ON course_outcome FOR UPDATE TO copo_faculty
    USING (course_id IN (SELECT fn_my_courses())) WITH CHECK (course_id IN (SELECT fn_my_courses()));
CREATE POLICY faculty_delete ON course_outcome FOR DELETE TO copo_faculty USING (course_id IN (SELECT fn_my_courses()));

CREATE POLICY everyone_reads ON co_po_map FOR SELECT TO copo_faculty, copo_student USING (true);
CREATE POLICY faculty_insert ON co_po_map FOR INSERT TO copo_faculty WITH CHECK (co_id IN (SELECT fn_my_cos()));
CREATE POLICY faculty_update ON co_po_map FOR UPDATE TO copo_faculty
    USING (co_id IN (SELECT fn_my_cos())) WITH CHECK (co_id IN (SELECT fn_my_cos()));
CREATE POLICY faculty_delete ON co_po_map FOR DELETE TO copo_faculty USING (co_id IN (SELECT fn_my_cos()));

CREATE POLICY everyone_reads ON co_dependency FOR SELECT TO copo_faculty USING (true);
CREATE POLICY faculty_insert ON co_dependency FOR INSERT TO copo_faculty WITH CHECK (co_id IN (SELECT fn_my_cos()));
CREATE POLICY faculty_update ON co_dependency FOR UPDATE TO copo_faculty
    USING (co_id IN (SELECT fn_my_cos())) WITH CHECK (co_id IN (SELECT fn_my_cos()));
CREATE POLICY faculty_delete ON co_dependency FOR DELETE TO copo_faculty USING (co_id IN (SELECT fn_my_cos()));

-- results: faculty read their offerings (written only by the definer procedure)
CREATE POLICY faculty_own ON co_attainment FOR SELECT TO copo_faculty USING (offering_id IN (SELECT fn_my_offerings()));
CREATE POLICY faculty_own ON po_attainment FOR SELECT TO copo_faculty USING (offering_id IN (SELECT fn_my_offerings()));
CREATE POLICY faculty_own ON indirect_attainment FOR SELECT TO copo_faculty USING (offering_id IN (SELECT fn_my_offerings()));

CREATE POLICY faculty_own ON improvement_action TO copo_faculty
    USING (offering_id IN (SELECT fn_my_offerings())) WITH CHECK (offering_id IN (SELECT fn_my_offerings()));

CREATE POLICY faculty_own ON whatif_scenario TO copo_faculty
    USING (offering_id IN (SELECT fn_my_offerings())) WITH CHECK (offering_id IN (SELECT fn_my_offerings()));
CREATE POLICY faculty_own ON whatif_result FOR SELECT TO copo_faculty USING (scenario_id IN (SELECT fn_my_scenarios()));
CREATE POLICY faculty_own ON whatif_po_result FOR SELECT TO copo_faculty USING (scenario_id IN (SELECT fn_my_scenarios()));

CREATE POLICY faculty_own ON unlock_request TO copo_faculty
    USING (assessment_id IN (SELECT fn_my_assessments())) WITH CHECK (assessment_id IN (SELECT fn_my_assessments()));
