-- 012_early_warning.sql
-- Early warning (phase 9, FR-6.5): after each locked CIE, the chance that a student misses each CO
-- by the end of the term, predicted from earlier offerings. Advisory only: nothing here feeds
-- sp_compute_attainment or the official result tables.
--
-- attainment_config.ew_flag_prob: a student is flagged for a CO when the predicted chance of
--   missing it is at least this (default 0.5, decided 23 Nov 2026). Data, like every threshold.
-- early_warning_run: the latest run per offering: which assessments it used (the "stage"), the
--   model's coefficients and fit, and the rule version whose target defines "missing a CO".
-- early_warning: one row per (offering, student, CO): probability, flag and the reasons behind it.
-- Teachers see their own offerings, the coordinator reads all, students see nothing.

ALTER TABLE attainment_config
    ADD COLUMN ew_flag_prob numeric(4,3) NOT NULL DEFAULT 0.5 CHECK (ew_flag_prob > 0 AND ew_flag_prob < 1);

CREATE TABLE early_warning_run (
    offering_id   int PRIMARY KEY REFERENCES course_offering,
    config_id     int NOT NULL REFERENCES attainment_config,
    stage         jsonb NOT NULL,          -- [{"type": "CIE_THEORY", "rank": 1, "name": "CIE Test 1"}, ...]
    model         jsonb NOT NULL,          -- features, coefficients, training rows and offerings, fit
    flag_prob     numeric(4,3) NOT NULL,
    computed_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE early_warning (
    offering_id  int NOT NULL REFERENCES early_warning_run ON DELETE CASCADE,
    usn          varchar NOT NULL REFERENCES student,
    co_id        int NOT NULL REFERENCES course_outcome,
    probability  numeric(4,3) NOT NULL CHECK (probability BETWEEN 0 AND 1),
    flagged      boolean NOT NULL,
    reasons      jsonb NOT NULL,           -- [{"feature", "value", "typical", "effect"}], strongest first
    PRIMARY KEY (offering_id, usn, co_id)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON early_warning_run, early_warning TO copo_admin, copo_faculty;
GRANT SELECT ON early_warning_run, early_warning TO copo_coordinator;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['early_warning_run', 'early_warning'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY admin_all ON %I TO copo_admin USING (true) WITH CHECK (true)', t);
        EXECUTE format('CREATE POLICY coordinator_read ON %I FOR SELECT TO copo_coordinator USING (true)', t);
        EXECUTE format('CREATE POLICY faculty_own ON %I TO copo_faculty '
                       'USING (offering_id IN (SELECT fn_my_offerings())) '
                       'WITH CHECK (offering_id IN (SELECT fn_my_offerings()))', t);
    END LOOP;
END $$;

-- The run is audited (who ran it, when, with what model); the per-student rows follow from it.
CREATE TRIGGER audit_row AFTER UPDATE OR DELETE ON early_warning_run
    FOR EACH ROW EXECUTE FUNCTION trg_audit_row('offering_id');
CREATE TRIGGER audit_insert AFTER INSERT ON early_warning_run REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION trg_audit_insert('offering_id');
CREATE TRIGGER audit_truncate AFTER TRUNCATE ON early_warning_run
    FOR EACH STATEMENT EXECUTE FUNCTION trg_audit_truncate();
