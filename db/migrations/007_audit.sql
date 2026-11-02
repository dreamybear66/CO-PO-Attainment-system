-- 007_audit.sql
-- Audit capture (PRD FR-7.2, S8). Audited changes are written to audit_outbox in the same
-- transaction as the change itself, so nothing is lost if the MongoDB writer is down. The writer
-- (api/jobs/audit.py) polls the outbox and moves its rows into the hash-chained MongoDB
-- audit_log. No NOTIFY: nothing listens, and it would serialise committing transactions on the
-- notification queue lock.

-- Who made the change. The API sets app.user per request to the signed-in user; it is trusted only
-- on the API's own login (copo_api), so no other session can put someone else's name on a change
-- by setting it. Every other session is recorded under its login.
CREATE FUNCTION fn_audit_user() RETURNS text LANGUAGE sql STABLE AS $$
    SELECT CASE WHEN session_user::text = 'copo_api'
                THEN coalesce(nullif(current_setting('app.user', true), ''), 'copo_api')
                ELSE session_user::text
           END
$$;

CREATE FUNCTION fn_audit_key(p_row jsonb, p_cols text[]) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
    SELECT jsonb_object_agg(c, p_row -> c) FROM unnest(p_cols) AS c
$$;

-- Row-level, for UPDATE and DELETE. Trigger arguments name the key columns.
CREATE FUNCTION trg_audit_row() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_old jsonb := CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END;
    v_new jsonb := CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END;
BEGIN
    IF TG_OP = 'UPDATE' AND v_old = v_new THEN
        RETURN NULL;
    END IF;
    INSERT INTO audit_outbox (app_user, table_name, op, key, before, after)
    VALUES (fn_audit_user(), TG_TABLE_NAME, TG_OP, fn_audit_key(coalesce(v_new, v_old), TG_ARGV), v_old, v_new);
    RETURN NULL;
END $$;

-- Statement-level with a transition table, for INSERT: bulk loads write the outbox in one statement.
CREATE FUNCTION trg_audit_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    INSERT INTO audit_outbox (app_user, table_name, op, key, before, after)
    SELECT fn_audit_user(), TG_TABLE_NAME, 'INSERT', fn_audit_key(to_jsonb(n), TG_ARGV), NULL, to_jsonb(n)
    FROM new_rows n;
    RETURN NULL;
END $$;

-- Attach both triggers to every audited table.
DO $$
DECLARE
    t record;
BEGIN
    FOR t IN SELECT * FROM (VALUES
        ('student_question_mark',   'enrollment_id, question_id'),
        ('question_co_map',         'question_id, co_id'),
        ('co_po_map',               'co_id, po_id'),
        ('co_dependency',           'co_id, prereq_co_id'),
        ('assessment',              'assessment_id'),
        ('attainment_config',       'config_id'),
        ('config_component_weight', 'config_id, component'),
        ('co_attainment',           'offering_id, co_id'),
        ('po_attainment',           'offering_id, po_id'),
        ('improvement_action',      'action_id'),
        ('unlock_request',          'request_id')
    ) AS v(tbl, keys)
    LOOP
        EXECUTE format(
            'CREATE TRIGGER audit_row AFTER UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION trg_audit_row(%s)',
            t.tbl, (SELECT string_agg(quote_literal(trim(k)), ', ') FROM unnest(string_to_array(t.keys, ',')) k));
        EXECUTE format(
            'CREATE TRIGGER audit_insert AFTER INSERT ON %I REFERENCING NEW TABLE AS new_rows '
            'FOR EACH STATEMENT EXECUTE FUNCTION trg_audit_insert(%s)',
            t.tbl, (SELECT string_agg(quote_literal(trim(k)), ', ') FROM unnest(string_to_array(t.keys, ',')) k));
    END LOOP;
END $$;

-- Rejected writes roll back with their transaction, so the API records each attempt
-- separately through this function (PRD: "later edits are rejected and every attempt is logged").
-- Only the roles that edit audited data (through the API) and maintenance logins may call it,
-- and only for an audited table.
CREATE FUNCTION fn_audit_denied(p_table text, p_key jsonb, p_detail jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF coalesce(fn_app_role() NOT IN ('admin', 'faculty', ''), true) THEN
        RAISE EXCEPTION 'Not allowed to record denied writes' USING ERRCODE = '42501';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgrelid = to_regclass('public.' || quote_ident(p_table)) AND tgname = 'audit_row') THEN
        RAISE EXCEPTION '% is not an audited table', p_table USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_key) IS DISTINCT FROM 'object' OR jsonb_typeof(p_detail) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'Key and detail must be JSON objects' USING ERRCODE = '22023';
    END IF;
    INSERT INTO audit_outbox (app_user, table_name, op, key, after)
    VALUES (fn_audit_user(), p_table, 'DENIED', p_key, p_detail);
END $$;

REVOKE EXECUTE ON FUNCTION fn_audit_denied(text, jsonb, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fn_audit_denied(text, jsonb, jsonb) TO copo_admin, copo_faculty;

CREATE INDEX audit_outbox_pending_idx ON audit_outbox (outbox_id) WHERE sent_at IS NULL;
