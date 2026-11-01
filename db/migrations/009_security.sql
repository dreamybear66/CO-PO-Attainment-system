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

-- Ownership lookups run as owner so policies do not recurse through other policies.
CREATE FUNCTION fn_teaches_offering(p_offering_id int) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT EXISTS (SELECT 1 FROM course_offering WHERE offering_id = p_offering_id AND faculty_id = fn_my_faculty())
$$;

CREATE FUNCTION fn_teaches_course(p_course_id int) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT EXISTS (SELECT 1 FROM course_offering WHERE course_id = p_course_id AND faculty_id = fn_my_faculty())
$$;

CREATE FUNCTION fn_enrolled_in(p_offering_id int) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT EXISTS (SELECT 1 FROM enrollment WHERE offering_id = p_offering_id AND usn = fn_my_usn())
$$;

CREATE FUNCTION fn_enrollment_offering(p_enrollment_id int) RETURNS int
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT offering_id FROM enrollment WHERE enrollment_id = p_enrollment_id
$$;

CREATE FUNCTION fn_enrollment_is_mine(p_enrollment_id int) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT EXISTS (SELECT 1 FROM enrollment WHERE enrollment_id = p_enrollment_id AND usn = fn_my_usn())
$$;

CREATE FUNCTION fn_assessment_offering(p_assessment_id int) RETURNS int
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT offering_id FROM assessment WHERE assessment_id = p_assessment_id
$$;

CREATE FUNCTION fn_question_offering(p_question_id int) RETURNS int
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT a.offering_id FROM assessment_question q JOIN assessment a USING (assessment_id)
    WHERE q.question_id = p_question_id
$$;

CREATE FUNCTION fn_co_course(p_co_id int) RETURNS int
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT course_id FROM course_outcome WHERE co_id = p_co_id
$$;

CREATE FUNCTION fn_scenario_offering(p_scenario_id int) RETURNS int
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT offering_id FROM whatif_scenario WHERE scenario_id = p_scenario_id
$$;

-- Login: the only way to read password hashes, granted to the API login alone.
CREATE FUNCTION fn_login_lookup(p_username text)
RETURNS TABLE (user_id int, password_hash text, role text, faculty_id int, usn varchar)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT user_id, password_hash, role, faculty_id, usn FROM app_user WHERE username = p_username
$$;

-- ---------------------------------------------------------------- privileges

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
REVOKE EXECUTE ON ALL PROCEDURES IN SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO copo_admin, copo_faculty, copo_coordinator, copo_student, copo_api;

GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO copo_admin, copo_faculty, copo_coordinator, copo_student;
REVOKE EXECUTE ON FUNCTION fn_login_lookup(text) FROM copo_admin, copo_faculty, copo_coordinator, copo_student;
GRANT EXECUTE ON FUNCTION fn_login_lookup(text) TO copo_api;
REVOKE EXECUTE ON FUNCTION fn_refresh_dashboards() FROM copo_faculty, copo_coordinator, copo_student;
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

-- views and materialized views (views are security_invoker, so RLS still applies)
GRANT SELECT ON v_offering_config, student_component_co_pct, student_co_score
    TO copo_admin, copo_faculty, copo_coordinator, copo_student;
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
CREATE POLICY faculty_own ON enrollment FOR SELECT TO copo_faculty USING (fn_teaches_offering(offering_id));
CREATE POLICY student_own ON enrollment FOR SELECT TO copo_student USING (usn = fn_my_usn());

-- assessments, questions, tags: faculty manage their offerings; students read their offerings'
CREATE POLICY faculty_own ON assessment TO copo_faculty
    USING (fn_teaches_offering(offering_id)) WITH CHECK (fn_teaches_offering(offering_id));
CREATE POLICY student_enrolled ON assessment FOR SELECT TO copo_student USING (fn_enrolled_in(offering_id));

CREATE POLICY faculty_own ON assessment_question TO copo_faculty
    USING (fn_teaches_offering(fn_assessment_offering(assessment_id)))
    WITH CHECK (fn_teaches_offering(fn_assessment_offering(assessment_id)));
CREATE POLICY student_enrolled ON assessment_question FOR SELECT TO copo_student
    USING (fn_enrolled_in(fn_assessment_offering(assessment_id)));

CREATE POLICY faculty_own ON question_co_map TO copo_faculty
    USING (fn_teaches_offering(fn_question_offering(question_id)))
    WITH CHECK (fn_teaches_offering(fn_question_offering(question_id)));
CREATE POLICY student_enrolled ON question_co_map FOR SELECT TO copo_student
    USING (fn_enrolled_in(fn_question_offering(question_id)));

-- marks (PRD Section 10: faculty see only their own offerings)
CREATE POLICY faculty_own_offerings ON student_question_mark TO copo_faculty
    USING (fn_teaches_offering(fn_enrollment_offering(enrollment_id)))
    WITH CHECK (fn_teaches_offering(fn_enrollment_offering(enrollment_id)));
CREATE POLICY student_own ON student_question_mark FOR SELECT TO copo_student
    USING (fn_enrollment_is_mine(enrollment_id));

-- outcome definitions: everyone reads; faculty edit those of courses they teach
CREATE POLICY everyone_reads ON course_outcome FOR SELECT TO copo_faculty, copo_student USING (true);
CREATE POLICY faculty_insert ON course_outcome FOR INSERT TO copo_faculty WITH CHECK (fn_teaches_course(course_id));
CREATE POLICY faculty_update ON course_outcome FOR UPDATE TO copo_faculty
    USING (fn_teaches_course(course_id)) WITH CHECK (fn_teaches_course(course_id));
CREATE POLICY faculty_delete ON course_outcome FOR DELETE TO copo_faculty USING (fn_teaches_course(course_id));

CREATE POLICY everyone_reads ON co_po_map FOR SELECT TO copo_faculty, copo_student USING (true);
CREATE POLICY faculty_insert ON co_po_map FOR INSERT TO copo_faculty WITH CHECK (fn_teaches_course(fn_co_course(co_id)));
CREATE POLICY faculty_update ON co_po_map FOR UPDATE TO copo_faculty
    USING (fn_teaches_course(fn_co_course(co_id))) WITH CHECK (fn_teaches_course(fn_co_course(co_id)));
CREATE POLICY faculty_delete ON co_po_map FOR DELETE TO copo_faculty USING (fn_teaches_course(fn_co_course(co_id)));

CREATE POLICY everyone_reads ON co_dependency FOR SELECT TO copo_faculty USING (true);
CREATE POLICY faculty_insert ON co_dependency FOR INSERT TO copo_faculty WITH CHECK (fn_teaches_course(fn_co_course(co_id)));
CREATE POLICY faculty_update ON co_dependency FOR UPDATE TO copo_faculty
    USING (fn_teaches_course(fn_co_course(co_id))) WITH CHECK (fn_teaches_course(fn_co_course(co_id)));
CREATE POLICY faculty_delete ON co_dependency FOR DELETE TO copo_faculty USING (fn_teaches_course(fn_co_course(co_id)));

-- results: faculty read their offerings (written only by the definer procedure)
CREATE POLICY faculty_own ON co_attainment FOR SELECT TO copo_faculty USING (fn_teaches_offering(offering_id));
CREATE POLICY faculty_own ON po_attainment FOR SELECT TO copo_faculty USING (fn_teaches_offering(offering_id));
CREATE POLICY faculty_own ON indirect_attainment FOR SELECT TO copo_faculty USING (fn_teaches_offering(offering_id));

CREATE POLICY faculty_own ON improvement_action TO copo_faculty
    USING (fn_teaches_offering(offering_id)) WITH CHECK (fn_teaches_offering(offering_id));

CREATE POLICY faculty_own ON whatif_scenario TO copo_faculty
    USING (fn_teaches_offering(offering_id)) WITH CHECK (fn_teaches_offering(offering_id));
CREATE POLICY faculty_own ON whatif_result FOR SELECT TO copo_faculty
    USING (fn_teaches_offering(fn_scenario_offering(scenario_id)));
CREATE POLICY faculty_own ON whatif_po_result FOR SELECT TO copo_faculty
    USING (fn_teaches_offering(fn_scenario_offering(scenario_id)));

CREATE POLICY faculty_own ON unlock_request TO copo_faculty
    USING (fn_teaches_offering(fn_assessment_offering(assessment_id)))
    WITH CHECK (fn_teaches_offering(fn_assessment_offering(assessment_id)));
