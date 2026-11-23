-- 011_survey_forms.sql
-- Google Forms course-exit surveys (phase 8, FR-5.1, FR-5.3 to FR-5.5).
--
-- google_account: one teacher's connection to their own Google account. Only the refresh token is
--   kept, encrypted by the API (Fernet, key GOOGLE_TOKEN_KEY); a row is visible to its own user
--   only, not even to the HoD, and it is not audited so tokens never reach the audit chain.
-- survey_form: the Google Form created for an offering (one course-exit form per offering) and the
--   Forms question ids of each field, so responses can be read back. Responses themselves go to
--   MongoDB survey_responses through the usual checks; names and phone numbers are never stored.

-- The caller's app_user id, from the username the API sets for each request.
CREATE FUNCTION fn_my_user_id() RETURNS int
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT user_id FROM app_user WHERE username = nullif(current_setting('app.user', true), '')
$$;
GRANT EXECUTE ON FUNCTION fn_my_user_id() TO copo_admin, copo_faculty;

CREATE TABLE google_account (
    user_id           int PRIMARY KEY REFERENCES app_user ON DELETE CASCADE,
    google_email      text NOT NULL,
    refresh_token_enc text NOT NULL,
    connected_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE survey_form (
    offering_id    int PRIMARY KEY REFERENCES course_offering,
    form_id        text NOT NULL UNIQUE,
    responder_uri  text NOT NULL,
    edit_uri       text NOT NULL,
    owner_user_id  int NOT NULL REFERENCES app_user,
    question_ids   jsonb NOT NULL,          -- {"email", "usn", "name", "phone": id, "cos": {co_id: id}}
    created_at     timestamptz NOT NULL DEFAULT now(),
    last_synced_at timestamptz,
    last_sync      jsonb                    -- counts only: read, accepted, already in, rejected by reason
);

GRANT SELECT, INSERT, UPDATE, DELETE ON google_account TO copo_admin, copo_faculty;
GRANT SELECT, INSERT, UPDATE, DELETE ON survey_form TO copo_admin, copo_faculty;
GRANT SELECT ON survey_form TO copo_coordinator;

ALTER TABLE google_account ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_account ON google_account TO copo_admin, copo_faculty
    USING (user_id = fn_my_user_id()) WITH CHECK (user_id = fn_my_user_id());

ALTER TABLE survey_form ENABLE ROW LEVEL SECURITY;
CREATE POLICY admin_all ON survey_form TO copo_admin USING (true) WITH CHECK (true);
CREATE POLICY coordinator_read ON survey_form FOR SELECT TO copo_coordinator USING (true);
CREATE POLICY faculty_own ON survey_form TO copo_faculty
    USING (offering_id IN (SELECT fn_my_offerings()))
    WITH CHECK (offering_id IN (SELECT fn_my_offerings()) AND owner_user_id = fn_my_user_id());

-- Audit survey forms like the other workflow tables (google_account deliberately not).
CREATE TRIGGER audit_row AFTER UPDATE OR DELETE ON survey_form
    FOR EACH ROW EXECUTE FUNCTION trg_audit_row('offering_id');
CREATE TRIGGER audit_insert AFTER INSERT ON survey_form REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION trg_audit_insert('offering_id');
CREATE TRIGGER audit_truncate AFTER TRUNCATE ON survey_form
    FOR EACH STATEMENT EXECUTE FUNCTION trg_audit_truncate();
