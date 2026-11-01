-- 001_schema.sql
-- Core tables for the CO-PO Attainment Management System (PRD Section 6).
-- 25 tables from the source design + the additions agreed in PRD Section 9/10:
-- config_component_weight, whatif_po_result, unlock_request, audit_outbox.

-- btree_gist backs the attainment_config EXCLUDE constraint. scripts/setup_db.py installs it as
-- superuser into its own schema, which `migrate --reset` (DROP SCHEMA public) does not touch.
-- These lines cover databases set up before that; btree_gist is a trusted extension.
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS btree_gist SCHEMA extensions;

-- ---------------------------------------------------------------- academic structure

CREATE TABLE department (
    dept_id   serial PRIMARY KEY,
    name      text NOT NULL UNIQUE
);

CREATE TABLE program (
    program_id serial PRIMARY KEY,
    dept_id    int  NOT NULL REFERENCES department,
    name       text NOT NULL,
    degree     text NOT NULL,
    UNIQUE (dept_id, name)
);

CREATE TABLE faculty (
    faculty_id serial PRIMARY KEY,
    dept_id    int  NOT NULL REFERENCES department,
    name       text NOT NULL,
    email      text NOT NULL UNIQUE
);

CREATE TABLE student (
    usn            varchar(12) PRIMARY KEY,
    name           text NOT NULL,
    program_id     int  NOT NULL REFERENCES program,
    admission_year int  NOT NULL CHECK (admission_year BETWEEN 2000 AND 2100),
    section        char(1) NOT NULL
);

CREATE TABLE course (
    course_id  serial PRIMARY KEY,
    code       text NOT NULL UNIQUE,
    title      text NOT NULL,
    credits    numeric(3,1) NOT NULL CHECK (credits > 0),
    semester   smallint NOT NULL CHECK (semester BETWEEN 1 AND 8),
    program_id int NOT NULL REFERENCES program
);

CREATE TABLE course_prerequisite (
    course_id        int NOT NULL REFERENCES course,
    prereq_course_id int NOT NULL REFERENCES course,
    PRIMARY KEY (course_id, prereq_course_id),
    CHECK (course_id <> prereq_course_id)
);

CREATE TABLE course_offering (
    offering_id   serial PRIMARY KEY,
    course_id     int  NOT NULL REFERENCES course,
    academic_year text NOT NULL CHECK (academic_year ~ '^\d{4}-\d{2}$'),
    term          text NOT NULL CHECK (term IN ('odd', 'even')),
    faculty_id    int  NOT NULL REFERENCES faculty,
    section       char(1) NOT NULL,
    UNIQUE (course_id, academic_year, term, section)
);

CREATE TABLE enrollment (
    enrollment_id serial PRIMARY KEY,
    offering_id   int NOT NULL REFERENCES course_offering,
    usn           varchar(12) NOT NULL REFERENCES student,
    UNIQUE (offering_id, usn)
);

-- ---------------------------------------------------------------- outcomes

CREATE TABLE program_outcome (
    po_id      serial PRIMARY KEY,
    program_id int  NOT NULL REFERENCES program,
    code       text NOT NULL,
    type       text NOT NULL CHECK (type IN ('PO', 'PSO')),
    statement  text NOT NULL,
    UNIQUE (program_id, code)
);

CREATE TABLE course_outcome (
    co_id       serial PRIMARY KEY,
    course_id   int  NOT NULL REFERENCES course,
    co_number   smallint NOT NULL CHECK (co_number > 0),
    statement   text NOT NULL,
    bloom_level smallint NOT NULL CHECK (bloom_level BETWEEN 1 AND 6),
    UNIQUE (course_id, co_number)
);

CREATE TABLE co_po_map (
    co_id    int NOT NULL REFERENCES course_outcome,
    po_id    int NOT NULL REFERENCES program_outcome,
    strength smallint NOT NULL CHECK (strength BETWEEN 1 AND 3),
    PRIMARY KEY (co_id, po_id)
);

-- ---------------------------------------------------------------- assessment and marks

-- The four components of the RVCE scheme: final = (CIE 100 + SEE 100) / 2,
-- CIE = theory 40 + quiz 20 + EL 40.
CREATE TYPE assessment_component AS ENUM ('CIE_THEORY', 'CIE_QUIZ', 'EL', 'SEE');

CREATE TABLE assessment (
    assessment_id serial PRIMARY KEY,
    offering_id   int  NOT NULL REFERENCES course_offering,
    type          assessment_component NOT NULL,
    name          text NOT NULL,
    max_marks     numeric(6,2) NOT NULL CHECK (max_marks > 0),
    locked        boolean NOT NULL DEFAULT false,
    locked_at     timestamptz,
    UNIQUE (offering_id, name),
    CHECK (locked = (locked_at IS NOT NULL))
);

CREATE TABLE assessment_question (
    question_id   serial PRIMARY KEY,
    assessment_id int  NOT NULL REFERENCES assessment,
    q_no          text NOT NULL,
    max_marks     numeric(6,2) NOT NULL CHECK (max_marks > 0),
    UNIQUE (assessment_id, q_no)
);

CREATE TABLE question_co_map (
    question_id int NOT NULL REFERENCES assessment_question,
    co_id       int NOT NULL REFERENCES course_outcome,
    weight      numeric(4,3) NOT NULL CHECK (weight > 0 AND weight <= 1),
    PRIMARY KEY (question_id, co_id)
);

-- Absent students have is_absent = true and marks_obtained NULL; they score 0 (S6).
CREATE TABLE student_question_mark (
    enrollment_id  int NOT NULL REFERENCES enrollment,
    question_id    int NOT NULL REFERENCES assessment_question,
    marks_obtained numeric(6,2) CHECK (marks_obtained >= 0),
    is_absent      boolean NOT NULL DEFAULT false,
    PRIMARY KEY (enrollment_id, question_id),
    CHECK (is_absent = (marks_obtained IS NULL))
);

-- ---------------------------------------------------------------- results and configuration

-- Weights are percentages (S1). Validity ranges of one programme may not overlap.
CREATE TABLE attainment_config (
    config_id       serial PRIMARY KEY,
    program_id      int  NOT NULL REFERENCES program,
    target_pct      numeric(5,2) NOT NULL CHECK (target_pct BETWEEN 0 AND 100),
    l3_pct          numeric(5,2) NOT NULL CHECK (l3_pct BETWEEN 0 AND 100),
    l2_pct          numeric(5,2) NOT NULL CHECK (l2_pct BETWEEN 0 AND 100),
    l1_pct          numeric(5,2) NOT NULL CHECK (l1_pct BETWEEN 0 AND 100),
    direct_weight   numeric(5,2) NOT NULL CHECK (direct_weight BETWEEN 0 AND 100),
    indirect_weight numeric(5,2) NOT NULL CHECK (indirect_weight BETWEEN 0 AND 100),
    co_target_level numeric(3,2) NOT NULL CHECK (co_target_level BETWEEN 0 AND 3),
    po_target_level numeric(3,2) NOT NULL CHECK (po_target_level BETWEEN 0 AND 3),
    rc_min_n        int          NOT NULL DEFAULT 20  CHECK (rc_min_n >= 3),
    rc_min_r        numeric(3,2) NOT NULL DEFAULT 0.40 CHECK (rc_min_r BETWEEN 0 AND 1),
    valid_from      date NOT NULL,
    valid_to        date,
    CHECK (l3_pct >= l2_pct AND l2_pct >= l1_pct),
    CHECK (direct_weight + indirect_weight = 100),
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    EXCLUDE USING gist (program_id WITH =, daterange(valid_from, valid_to) WITH &&)
);

CREATE TABLE config_component_weight (
    config_id  int NOT NULL REFERENCES attainment_config,
    component  assessment_component NOT NULL,
    weight_pct numeric(5,2) NOT NULL CHECK (weight_pct > 0 AND weight_pct <= 100),
    PRIMARY KEY (config_id, component)
);

CREATE TABLE co_attainment (
    offering_id    int NOT NULL REFERENCES course_offering,
    co_id          int NOT NULL REFERENCES course_outcome,
    config_id      int NOT NULL REFERENCES attainment_config,
    students       int NOT NULL,
    pct_attained   numeric(5,2) NOT NULL,
    direct_level   smallint NOT NULL CHECK (direct_level BETWEEN 0 AND 3),
    indirect_level smallint NOT NULL CHECK (indirect_level BETWEEN 0 AND 3),
    final_level    numeric(4,2) NOT NULL CHECK (final_level BETWEEN 0 AND 3),
    computed_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (offering_id, co_id)
);

CREATE TABLE indirect_attainment (
    offering_id    int NOT NULL REFERENCES course_offering,
    co_id          int NOT NULL REFERENCES course_outcome,
    respondents    int NOT NULL CHECK (respondents >= 0),
    pct_favourable numeric(5,2) NOT NULL CHECK (pct_favourable BETWEEN 0 AND 100),
    level          smallint NOT NULL CHECK (level BETWEEN 0 AND 3),
    loaded_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (offering_id, co_id)
);

CREATE TABLE po_attainment (
    offering_id int NOT NULL REFERENCES course_offering,
    po_id       int NOT NULL REFERENCES program_outcome,
    config_id   int NOT NULL REFERENCES attainment_config,
    attainment  numeric(4,2) NOT NULL CHECK (attainment BETWEEN 0 AND 3),
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (offering_id, po_id)
);

CREATE TABLE improvement_action (
    action_id             serial PRIMARY KEY,
    co_id                 int  NOT NULL REFERENCES course_outcome,
    offering_id           int  NOT NULL REFERENCES course_offering,
    description           text NOT NULL,
    owner                 int  NOT NULL REFERENCES faculty,
    status                text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'done')),
    source                text NOT NULL DEFAULT 'manual' CHECK (source IN ('auto', 'root_cause', 'manual')),
    follow_up_offering_id int REFERENCES course_offering,
    created_at            timestamptz NOT NULL DEFAULT now()
);
-- Recomputing an offering must not duplicate its automatic actions.
CREATE UNIQUE INDEX improvement_action_auto_uq
    ON improvement_action (offering_id, co_id) WHERE source = 'auto';

-- ---------------------------------------------------------------- innovation

CREATE TABLE co_dependency (
    co_id        int NOT NULL REFERENCES course_outcome,
    prereq_co_id int NOT NULL REFERENCES course_outcome,
    strength     smallint NOT NULL CHECK (strength BETWEEN 1 AND 3),
    PRIMARY KEY (co_id, prereq_co_id),
    CHECK (co_id <> prereq_co_id)
);

-- ---------------------------------------------------------------- access and integrity
-- app_user comes before whatif_scenario, which references it.

CREATE TABLE app_user (
    user_id       serial PRIMARY KEY,
    username      text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    role          text NOT NULL CHECK (role IN ('admin', 'faculty', 'coordinator', 'student')),
    faculty_id    int REFERENCES faculty,
    usn           varchar(12) REFERENCES student,
    UNIQUE (faculty_id),                -- one login per faculty member and per student
    UNIQUE (usn),                       -- (docs/er-diagram.md: |o--o|); NULLs allowed
    CHECK (role <> 'faculty' OR faculty_id IS NOT NULL),
    CHECK (role <> 'student' OR usn IS NOT NULL),
    CHECK (role IN ('faculty', 'admin') OR faculty_id IS NULL),
    CHECK (role = 'student' OR usn IS NULL)
);

-- Scenario rules override the base config; component weights come from the base config.
CREATE TABLE whatif_scenario (
    scenario_id     serial PRIMARY KEY,
    offering_id     int NOT NULL REFERENCES course_offering,
    base_config_id  int NOT NULL REFERENCES attainment_config,
    created_by      int NOT NULL REFERENCES app_user,
    name            text NOT NULL,
    target_pct      numeric(5,2) NOT NULL CHECK (target_pct BETWEEN 0 AND 100),
    l3_pct          numeric(5,2) NOT NULL CHECK (l3_pct BETWEEN 0 AND 100),
    l2_pct          numeric(5,2) NOT NULL CHECK (l2_pct BETWEEN 0 AND 100),
    l1_pct          numeric(5,2) NOT NULL CHECK (l1_pct BETWEEN 0 AND 100),
    direct_weight   numeric(5,2) NOT NULL CHECK (direct_weight BETWEEN 0 AND 100),
    indirect_weight numeric(5,2) NOT NULL CHECK (indirect_weight BETWEEN 0 AND 100),
    co_target_level numeric(3,2) NOT NULL CHECK (co_target_level BETWEEN 0 AND 3),
    po_target_level numeric(3,2) NOT NULL CHECK (po_target_level BETWEEN 0 AND 3),
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (l3_pct >= l2_pct AND l2_pct >= l1_pct),
    CHECK (direct_weight + indirect_weight = 100)
);

CREATE TABLE whatif_result (
    scenario_id    int NOT NULL REFERENCES whatif_scenario ON DELETE CASCADE,
    co_id          int NOT NULL REFERENCES course_outcome,
    pct_attained   numeric(5,2) NOT NULL,
    direct_level   smallint NOT NULL,
    indirect_level smallint NOT NULL,
    final_level    numeric(4,2) NOT NULL,
    PRIMARY KEY (scenario_id, co_id)
);

CREATE TABLE whatif_po_result (
    scenario_id int NOT NULL REFERENCES whatif_scenario ON DELETE CASCADE,
    po_id       int NOT NULL REFERENCES program_outcome,
    attainment  numeric(4,2) NOT NULL,
    PRIMARY KEY (scenario_id, po_id)
);

-- Unlocking a locked assessment needs an HoD-approved request (S7).
CREATE TABLE unlock_request (
    request_id    serial PRIMARY KEY,
    assessment_id int  NOT NULL REFERENCES assessment,
    requested_by  int  NOT NULL REFERENCES app_user,
    reason        text NOT NULL CHECK (length(trim(reason)) > 0),
    status        text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'used')),
    decided_by    int REFERENCES app_user,
    requested_at  timestamptz NOT NULL DEFAULT now(),
    decided_at    timestamptz,
    CHECK ((status = 'pending') = (decided_by IS NULL))
);

-- Daily copy of the MongoDB audit-chain head.
CREATE TABLE audit_anchor (
    anchor_id   serial PRIMARY KEY,
    seq         bigint NOT NULL,
    head_hash   text   NOT NULL,
    anchored_at timestamptz NOT NULL DEFAULT now()
);

-- Written in the same transaction as the audited change; a worker moves rows
-- to the MongoDB hash chain and stamps sent_at (S8).
CREATE TABLE audit_outbox (
    outbox_id  bigserial PRIMARY KEY,
    ts         timestamptz NOT NULL DEFAULT clock_timestamp(),
    app_user   text,
    table_name text NOT NULL,
    op         text NOT NULL CHECK (op IN ('INSERT', 'UPDATE', 'DELETE', 'DENIED')),
    key        jsonb NOT NULL,
    before     jsonb,
    after      jsonb,
    sent_at    timestamptz
);
