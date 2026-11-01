-- 002_integrity.sql
-- Triggers that enforce rules a CHECK cannot express (PRD FR-2.3, FR-3.2, FR-3.3, FR-3.5, FR-3.6).
-- Errors use custom SQLSTATEs (class CP) so the API can map them to clear messages:
--   CP001 locked assessment      CP002 marks out of range     CP003 cross-offering reference
--   CP004 weight sum             CP005 dependency cycle/scope CP006 incomplete marks at lock
--   CP007 unlock not approved

-- ---------------------------------------------------------------- marks: mark_guard

-- The assessment behind a question, read with its row locked FOR SHARE. Every write to a mark,
-- question or CO tag goes through such a lock, so locking or unlocking the assessment (an UPDATE,
-- whose row lock conflicts with FOR SHARE) waits until in-flight writes commit, and a write that
-- starts after a lock waits for it and then sees locked = true. FOR SHARE locks do not conflict
-- with each other, so concurrent mark entry is not serialized.
CREATE FUNCTION fn_question_assessment(p_question_id int,
    OUT locked boolean, OUT max_marks numeric, OUT offering_id int)
LANGUAGE sql VOLATILE AS $$
    SELECT a.locked, aq.max_marks, a.offering_id
    FROM assessment_question aq JOIN assessment a USING (assessment_id)
    WHERE aq.question_id = p_question_id
    FOR SHARE OF a
$$;

CREATE FUNCTION trg_check_mark() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    q record;
    v_e_offering int;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT * INTO q FROM fn_question_assessment(OLD.question_id);
        IF q.locked THEN
            RAISE EXCEPTION 'Assessment is locked; marks cannot be changed'
                USING ERRCODE = 'CP001';
        END IF;
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
    END IF;

    SELECT * INTO q FROM fn_question_assessment(NEW.question_id);
    IF q.locked THEN
        RAISE EXCEPTION 'Assessment is locked; marks cannot be changed'
            USING ERRCODE = 'CP001';
    END IF;
    IF NEW.marks_obtained < 0 OR NEW.marks_obtained > q.max_marks THEN
        RAISE EXCEPTION 'Marks % are outside 0 to %', NEW.marks_obtained, q.max_marks
            USING ERRCODE = 'CP002';
    END IF;

    SELECT offering_id INTO v_e_offering FROM enrollment WHERE enrollment_id = NEW.enrollment_id;
    IF v_e_offering IS DISTINCT FROM q.offering_id THEN
        RAISE EXCEPTION 'Enrollment % does not belong to the offering of question %',
            NEW.enrollment_id, NEW.question_id USING ERRCODE = 'CP003';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER mark_guard BEFORE INSERT OR UPDATE OR DELETE ON student_question_mark
FOR EACH ROW EXECUTE FUNCTION trg_check_mark();

-- ---------------------------------------------------------------- questions and tags frozen by lock

CREATE FUNCTION trg_question_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_locked boolean;
BEGIN
    IF TG_TABLE_NAME = 'assessment_question' THEN
        SELECT locked INTO v_locked FROM assessment
        WHERE assessment_id = CASE WHEN TG_OP = 'DELETE' THEN OLD.assessment_id ELSE NEW.assessment_id END
        FOR SHARE;
        IF NOT v_locked AND TG_OP = 'UPDATE' THEN
            SELECT locked INTO v_locked FROM assessment WHERE assessment_id = OLD.assessment_id FOR SHARE;
        END IF;
    ELSE
        SELECT q.locked INTO v_locked FROM fn_question_assessment(
            CASE WHEN TG_OP = 'DELETE' THEN OLD.question_id ELSE NEW.question_id END) q;
        IF NOT v_locked AND TG_OP = 'UPDATE' THEN
            SELECT q.locked INTO v_locked FROM fn_question_assessment(OLD.question_id) q;
        END IF;
    END IF;
    IF v_locked THEN
        RAISE EXCEPTION 'Assessment is locked; questions and CO tags cannot be changed'
            USING ERRCODE = 'CP001';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

CREATE TRIGGER question_frozen BEFORE INSERT OR UPDATE OR DELETE ON assessment_question
FOR EACH ROW EXECUTE FUNCTION trg_question_frozen();
CREATE TRIGGER question_co_frozen BEFORE INSERT OR UPDATE OR DELETE ON question_co_map
FOR EACH ROW EXECUTE FUNCTION trg_question_frozen();

-- ---------------------------------------------------------------- question CO tags

-- A question may only be tagged with COs of its own course.
CREATE FUNCTION trg_question_co_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM assessment_question aq
        JOIN assessment a       USING (assessment_id)
        JOIN course_offering o  USING (offering_id)
        JOIN course_outcome co  ON co.course_id = o.course_id
        WHERE aq.question_id = NEW.question_id AND co.co_id = NEW.co_id
    ) THEN
        RAISE EXCEPTION 'CO % does not belong to the course of question %', NEW.co_id, NEW.question_id
            USING ERRCODE = 'CP003';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER question_co_scope BEFORE INSERT OR UPDATE ON question_co_map
FOR EACH ROW EXECUTE FUNCTION trg_question_co_scope();

-- The CO weights of one question sum to 1 (checked at commit, so rows can be added one by one).
CREATE FUNCTION trg_question_weight_sum() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_question int := CASE WHEN TG_OP = 'DELETE' THEN OLD.question_id ELSE NEW.question_id END;
    v_sum numeric;
BEGIN
    SELECT sum(weight) INTO v_sum FROM question_co_map WHERE question_id = v_question;
    IF v_sum IS NOT NULL AND v_sum <> 1 THEN
        RAISE EXCEPTION 'CO weights of question % sum to %, not 1', v_question, v_sum
            USING ERRCODE = 'CP004';
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER question_weight_sum AFTER INSERT OR UPDATE OR DELETE ON question_co_map
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_question_weight_sum();

-- ---------------------------------------------------------------- component weights

CREATE FUNCTION trg_component_weight_sum() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_config int := CASE WHEN TG_OP = 'DELETE' THEN OLD.config_id ELSE NEW.config_id END;
    v_sum numeric;
BEGIN
    SELECT sum(weight_pct) INTO v_sum FROM config_component_weight WHERE config_id = v_config;
    IF v_sum IS NOT NULL AND v_sum <> 100 THEN
        RAISE EXCEPTION 'Component weights of config % sum to %, not 100', v_config, v_sum
            USING ERRCODE = 'CP004';
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER component_weight_sum AFTER INSERT OR UPDATE OR DELETE ON config_component_weight
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_component_weight_sum();

-- ---------------------------------------------------------------- CO-PO map scope

CREATE FUNCTION trg_co_po_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM course_outcome co
        JOIN course c ON c.course_id = co.course_id
        JOIN program_outcome po ON po.program_id = c.program_id
        WHERE co.co_id = NEW.co_id AND po.po_id = NEW.po_id
    ) THEN
        RAISE EXCEPTION 'PO % is not an outcome of the programme of CO %', NEW.po_id, NEW.co_id
            USING ERRCODE = 'CP003';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER co_po_scope BEFORE INSERT OR UPDATE ON co_po_map
FOR EACH ROW EXECUTE FUNCTION trg_co_po_scope();

-- ---------------------------------------------------------------- course prerequisites

-- The prerequisite graph must stay acyclic.
CREATE FUNCTION trg_course_prerequisite_acyclic() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        WITH RECURSIVE up AS (
            SELECT cp.prereq_course_id AS course_id FROM course_prerequisite cp
            WHERE cp.course_id = NEW.prereq_course_id
            UNION
            SELECT cp.prereq_course_id FROM up JOIN course_prerequisite cp ON cp.course_id = up.course_id
        )
        SELECT 1 FROM up WHERE course_id = NEW.course_id
    ) THEN
        RAISE EXCEPTION 'Prerequisite % -> % would create a cycle', NEW.course_id, NEW.prereq_course_id
            USING ERRCODE = 'CP005';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER course_prerequisite_acyclic BEFORE INSERT OR UPDATE ON course_prerequisite
FOR EACH ROW EXECUTE FUNCTION trg_course_prerequisite_acyclic();

-- ---------------------------------------------------------------- CO dependencies (S9)

-- The prerequisite CO must belong to a course reachable through course_prerequisite,
-- and the new edge must not close a cycle.
CREATE FUNCTION trg_co_dependency_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        WITH RECURSIVE reach AS (
            SELECT cp.prereq_course_id AS course_id
            FROM course_outcome co JOIN course_prerequisite cp ON cp.course_id = co.course_id
            WHERE co.co_id = NEW.co_id
            UNION
            SELECT cp.prereq_course_id
            FROM reach r JOIN course_prerequisite cp ON cp.course_id = r.course_id
        )
        SELECT 1 FROM reach r JOIN course_outcome p ON p.course_id = r.course_id
        WHERE p.co_id = NEW.prereq_co_id
    ) THEN
        RAISE EXCEPTION 'CO % is not in a prerequisite course of CO %', NEW.prereq_co_id, NEW.co_id
            USING ERRCODE = 'CP005';
    END IF;

    IF EXISTS (
        WITH RECURSIVE up AS (
            SELECT d.prereq_co_id AS co_id FROM co_dependency d WHERE d.co_id = NEW.prereq_co_id
            UNION
            SELECT d.prereq_co_id FROM up JOIN co_dependency d ON d.co_id = up.co_id
        )
        SELECT 1 FROM up WHERE co_id = NEW.co_id
    ) THEN
        RAISE EXCEPTION 'Dependency % -> % would create a cycle', NEW.co_id, NEW.prereq_co_id
            USING ERRCODE = 'CP005';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER co_dependency_check BEFORE INSERT OR UPDATE ON co_dependency
FOR EACH ROW EXECUTE FUNCTION trg_co_dependency_check();

-- ---------------------------------------------------------------- assessment lock / unlock

-- An assessment is created unlocked; locking stamps locked_at and requires a mark (or absence) for
-- every enrolled student on every question, each question tagged to at least one CO. Unlocking
-- needs an approved unlock_request, which is then marked used (S7). A locked assessment cannot be
-- edited or deleted.
-- Runs as owner: it counts every mark and consumes the unlock request, whoever locks.
CREATE FUNCTION trg_assessment_lock() RETURNS trigger
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
        -- Inserted locked, it would skip every check below (and questions could never be added).
        IF NEW.locked THEN
            RAISE EXCEPTION 'An assessment is created unlocked and locked once its marks are in'
                USING ERRCODE = 'CP006';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.locked AND NOT OLD.locked THEN
        SELECT count(*) INTO v_untagged FROM assessment_question aq
        WHERE aq.assessment_id = NEW.assessment_id
          AND NOT EXISTS (SELECT 1 FROM question_co_map m WHERE m.question_id = aq.question_id);
        IF v_untagged > 0 THEN
            RAISE EXCEPTION '% question(s) have no CO tag', v_untagged USING ERRCODE = 'CP006';
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
        IF (NEW.offering_id, NEW.type, NEW.name, NEW.max_marks, NEW.locked_at)
           IS DISTINCT FROM (OLD.offering_id, OLD.type, OLD.name, OLD.max_marks, OLD.locked_at) THEN
            RAISE EXCEPTION 'Assessment is locked; it cannot be edited' USING ERRCODE = 'CP001';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER assessment_lock BEFORE INSERT OR UPDATE OR DELETE ON assessment
FOR EACH ROW EXECUTE FUNCTION trg_assessment_lock();

-- A locked assessment keeps a mark (or absence) for every enrolled student, so nobody can be
-- enrolled into, or moved into, an offering with a locked assessment; unlock it first. FOR SHARE on
-- the offering's assessments orders this against a concurrent lock: either the lock waits and then
-- counts the new enrollment (and fails CP006), or this waits and then sees the lock.
CREATE FUNCTION trg_enrollment_open() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM assessment WHERE offering_id = NEW.offering_id FOR SHARE;
    IF EXISTS (SELECT 1 FROM assessment WHERE offering_id = NEW.offering_id AND locked) THEN
        RAISE EXCEPTION 'Offering % has a locked assessment; unlock it before enrolling students',
            NEW.offering_id USING ERRCODE = 'CP001';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER enrollment_open BEFORE INSERT OR UPDATE OF offering_id ON enrollment
FOR EACH ROW EXECUTE FUNCTION trg_enrollment_open();

-- An assessment's question maxima must add up to its max_marks; checked when locking.
CREATE FUNCTION trg_assessment_max_matches() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_sum numeric;
BEGIN
    IF NEW.locked AND NOT OLD.locked THEN
        SELECT sum(max_marks) INTO v_sum FROM assessment_question WHERE assessment_id = NEW.assessment_id;
        IF v_sum IS DISTINCT FROM NEW.max_marks THEN
            RAISE EXCEPTION 'Question maxima sum to %, assessment maximum is %', v_sum, NEW.max_marks
                USING ERRCODE = 'CP006';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER assessment_max_matches BEFORE UPDATE ON assessment
FOR EACH ROW EXECUTE FUNCTION trg_assessment_max_matches();
