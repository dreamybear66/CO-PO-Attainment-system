# ER diagram

29 tables: the 25 from the source design plus `config_component_weight`, `whatif_po_result`,
`unlock_request` and `audit_outbox` (PRD Section 9 changes). DDL: `db/migrations/001_schema.sql`. Rendered images: [PNG](er-diagram.png), [SVG](er-diagram.svg)
(the images show those 29).

The rescope adds four tables, 33 in all. `011_survey_forms.sql`: `google_account` (a teacher's
encrypted Google refresh token, visible to that user only and not audited) and `survey_form` (the
Google Form of an offering and its question ids). `012_early_warning.sql`: `early_warning_run` (the
latest early-warning run of an offering: assessments used, model, flag cut-off) and `early_warning`
(each student's chance of missing each CO, with reasons); it also adds
`attainment_config.ew_flag_prob` (default 0.5). Migration 010 adds `assessment_question.bloom_level`.

```mermaid
erDiagram
    department ||--o{ program : has
    department ||--o{ faculty : employs
    program ||--o{ student : enrols
    program ||--o{ course : offers
    program ||--o{ program_outcome : defines
    program ||--o{ attainment_config : "is governed by"

    course ||--o{ course_prerequisite : "needs"
    course ||--o{ course_outcome : has
    course ||--o{ course_offering : "is taught as"
    faculty ||--o{ course_offering : teaches
    course_offering ||--o{ enrollment : has
    student ||--o{ enrollment : takes

    course_outcome ||--o{ co_po_map : "maps to"
    program_outcome ||--o{ co_po_map : "is mapped from"
    course_outcome ||--o{ co_dependency : "builds on"

    course_offering ||--o{ assessment : has
    assessment ||--o{ assessment_question : contains
    assessment_question ||--o{ question_co_map : "is tagged"
    course_outcome ||--o{ question_co_map : "is tested by"
    enrollment ||--o{ student_question_mark : scores
    assessment_question ||--o{ student_question_mark : "is marked in"

    attainment_config ||--o{ config_component_weight : weights
    course_offering ||--o{ co_attainment : "results in"
    course_outcome ||--o{ co_attainment : ""
    attainment_config ||--o{ co_attainment : "computed with"
    course_offering ||--o{ po_attainment : "results in"
    program_outcome ||--o{ po_attainment : ""
    course_offering ||--o{ indirect_attainment : "surveyed in"
    course_outcome ||--o{ improvement_action : "needs"
    course_offering ||--o{ improvement_action : ""

    course_offering ||--o{ whatif_scenario : "is simulated by"
    app_user ||--o{ whatif_scenario : creates
    whatif_scenario ||--o{ whatif_result : produces
    whatif_scenario ||--o{ whatif_po_result : produces

    faculty |o--o| app_user : "logs in as"
    student |o--o| app_user : "logs in as"
    assessment ||--o{ unlock_request : "unlock asked for"
    app_user ||--o{ unlock_request : "requests / decides"
    app_user |o--o| google_account : "connects"
    course_offering |o--o| survey_form : "is surveyed by"
    app_user ||--o{ survey_form : owns
    course_offering |o--o| early_warning_run : "is forecast by"
    early_warning_run ||--o{ early_warning : predicts
    course_outcome ||--o{ early_warning : ""
```

`audit_outbox` and `audit_anchor` stand alone: the outbox is filled by audit triggers on the audited
tables and records where each row landed in the MongoDB audit chain (`chain_seq`, `chain_hash`), and
the anchor stores the daily head hash of the chain.

## Key rules

| Rule | Where |
| --- | --- |
| CO-PO and dependency strength 1–3 | CHECK on `co_po_map`, `co_dependency` |
| 0 ≤ marks ≤ question maximum | CHECK (≥ 0) here; upper bound in the `mark_guard` trigger (Phase 3, `002_integrity.sql`) |
| Component weights of a config sum to 100 | deferred trigger (Phase 3, `002_integrity.sql`) |
| Absent ⇔ marks NULL; scored as 0 | CHECK on `student_question_mark` |
| direct_weight + indirect_weight = 100 | CHECK on `attainment_config`, `whatif_scenario` |
| l3 ≥ l2 ≥ l1 | CHECK on `attainment_config`, `whatif_scenario` |
| One config per programme per date | EXCLUDE (gist) on `attainment_config`, checked at commit |
| Percentages 0–100, levels 0–3 | domains `pct_0_100`, `level_0_3`, `attainment_0_3` on rule and result tables (official and what-if) |
| One student per offering once | UNIQUE `enrollment (offering_id, usn)` |
| One automatic action per (offering, CO) | partial unique index on `improvement_action` |
| Role needs its link (faculty_id / usn) | CHECKs on `app_user` |
| At most one login per faculty member / student | UNIQUE `app_user (faculty_id)`, `app_user (usn)` |
| Unlock decision has who and when; no self-approval | CHECKs on `unlock_request` |
