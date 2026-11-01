# Implementation Plan

How the CO-PO Attainment Management System gets built. Requirement IDs (FR-x, NFR-x) and suggested
changes (S1–S13) refer to the [PRD](https://claude.ai/artifact/G8HdvxVTjQ47XZ6AeEhard).

## Stack

| Layer | Choice |
| --- | --- |
| Relational DB | PostgreSQL 16 (PL/pgSQL, RLS, materialized views, recursive CTEs) |
| NoSQL DB | MongoDB (survey responses, hash-chained audit log) |
| Backend | Python, FastAPI, psycopg, pymongo |
| Frontend | React + a charting library |
| Jobs | APScheduler (nightly ETL, audit verifier, daily anchor) |
| Test data | Python generator (Faker + NumPy) |
| Tests | pytest (API + SQL), SQL fixtures for the worked example |

## Repository layout (target)

```
db/
  migrations/        numbered DDL files (001_schema.sql, 002_constraints.sql, ...)
  functions/         triggers, sp_compute_attainment, root-cause queries
  views/             student_co_score, materialized dashboard views
  seed/              worked-example fixture (Section 5 of PRD)
api/                 FastAPI app (routers, services, mongo, jobs)
web/                 React app
datagen/             synthetic data generator
tests/               pytest suites, grouped by PRD test
docs/                ER diagram, EXPLAIN ANALYZE reports
```

## Decisions (2 Nov 2026)

Settled in PRD Section 10; the phases below already apply them.

| # | Decision |
| --- | --- |
| S1 | Weights stored as percentages: `direct_weight + indirect_weight = 100`; final = `(dw × direct + iw × indirect) / 100` |
| S5 | CIE/SEE by weighted marks, one direct level per CO. Final mark = (CIE 100 + SEE 100) / 2, so component weights are CIE theory 20, CIE quiz 10, EL 20, SEE 50 |
| S5 | Same scheme for every course in v1; per-course schemes later (keep the weights in data so this is a data change, not a code change) |
| S6 | Absent student scores 0 |
| S10 | Programme-level PO = plain average of offering-level PO values |
| S11 | Student role included, limited to own rows by RLS |

## Phase 1 — Schema and constraints (week 1) · Member A

Output: approved ER diagram and DDL.

1. ER diagram in `docs/` covering the 25 PRD tables plus the additions below.
2. `db/migrations/001_schema.sql` — all tables with PKs and FKs (FR-1.x, FR-2.x, FR-3.1, FR-4.1).
3. `002_constraints.sql` — CHECKs: CO-PO and dependency strength 1–3; marks between 0 and max;
   `direct_weight + indirect_weight = 100` (NFR-1, S1).
4. Schema additions from the PRD:
   - `attainment_config`: `co_target_level`, `po_target_level` (S2).
   - `config_component_weight (config_id FK, component, weight_pct)` with a deferred trigger that the
     weights of one config sum to 100. v1 seed: `CIE_THEORY` 20, `CIE_QUIZ` 10, `EL` 20, `SEE` 50 (S5).
     A nullable `course_id` can be added later for per-course schemes.
   - `assessment.type` restricted to those four components; several assessments of one type (e.g. two
     CIE theory tests) are pooled within the component.
   - `student_question_mark`: `is_absent` flag, `marks_obtained` nullable when absent; scored as 0 (S6).
   - `app_user`: nullable `usn` FK for student logins; CHECK that faculty users have `faculty_id` and
     student users have `usn` (S11).
   - `whatif_scenario`: split `direct_weight` / `indirect_weight`, add `co_target_level` (S4).
   - `whatif_po_result (scenario_id, po_id, attainment)` (S3).
   - `unlock_request (request_id, assessment_id, requested_by, approved_by, reason, ts)` (S7).
   - `audit_outbox` (S8).
5. Unique constraints: `enrollment (offering_id, usn)`; `co_po_map (co_id, po_id)`.

## Phase 2 — Synthetic data (week 2) · Member B

Output: database with 500k+ mark rows.

1. `datagen/` produces departments → programmes → courses (with prerequisites) → offerings over
   3+ academic years → students, enrolments, assessments, questions, marks. Each offering gets CIE
   theory tests, quizzes, an EL assessment and a SEE; a small share of absences.
2. Planted weakness: one upstream CO lowered for a cohort, the dependent CO lowered for the same
   students, plus an unrelated decoy CO (for the FR-6.2 tests).
3. Survey documents into MongoDB with `respondent_hash`, one per (respondent, offering, survey_type) (S12).
4. Deterministic seed so test runs are reproducible.
5. `db/seed/worked_example.sql` — the exact 60-student, 3-CO case from PRD Section 5.

## Phase 3 — Attainment engine (weeks 3–4) · Member A

Output: engine that matches the worked example to two decimals.

1. Trigger `mark_guard` (`trg_check_mark`): reject marks outside 0..max and any write to a locked
   assessment; emit an audit row (FR-3.3, FR-3.5).
2. Deferred constraint trigger: per-question CO weights sum to 1 (FR-3.2).
3. Trigger on `co_dependency`: reject cycles and prereq COs outside the course-prerequisite graph (FR-2.3, S9).
4. Views for the student CO score (PRD Section 5, steps 1–2):
   - `student_component_co_pct` — per (usn, offering, CO, component): weighted marks ÷ weighted max
     × 100, absent marks counted as 0.
   - `student_co_score` — Σ(weight_pct × component %) ÷ Σ weight_pct over the components that test the
     CO, weights from `config_component_weight`.
5. `sp_compute_attainment(p_offering_id, p_config_id, p_persist)`:
   1. `SELECT ... FOR UPDATE` on the offering (NFR-3).
   2. Raise if any assessment is unlocked (FR-4.3).
   3. Direct level per CO from config thresholds.
   4. Indirect level from `indirect_attainment` (0 if no survey).
   5. Final level = `(direct_weight × direct + indirect_weight × indirect) / 100`.
   6. PO per offering from `co_po_map` strengths.
   7. `p_persist` → write `co_attainment` / `po_attainment` and refresh views; else write
      `whatif_result` / `whatif_po_result` only (NFR-8).
   8. Insert `improvement_action` for each CO below `co_target_level` (FR-4.4).
6. Programme-level PO = plain average of offering-level PO values (FR-4.5).
7. Indexes: `student_question_mark(question_id)`, `enrollment(offering_id)`,
   `question_co_map(co_id)`; record EXPLAIN ANALYZE before/after in `docs/` (NFR-7).
8. Tests: worked example → CO 3.00 / 2.20 / 0.40, PO1 2.30, PO2 1.48; component weighting → a student
   at 70 / 80 / 90 / 60 % (theory / quiz / EL / SEE) scores 70.0%, and 68.9% when no quiz question
   tests the CO.

## Phase 4 — MongoDB, ETL and audit chain (week 5) · Member B

Output: integrated NoSQL layer.

1. Collections `survey_responses` (unique index per S12) and `audit_log`.
2. API reference checks: `offering_id`, `co_id` must exist in PostgreSQL before a survey insert (FR-5.1).
3. Nightly ETL: % rating ≥ 4 per (offering, CO) → level via config thresholds → upsert
   `indirect_attainment` (FR-5.2).
4. Audit: DB triggers write to `audit_outbox` in the same transaction; a worker moves rows to
   `audit_log` with `hash = SHA256(prev_hash + canonical JSON)` and marks them sent (S8).
5. Daily job copies the chain head into `audit_anchor`; verifier recomputes the chain and reports the
   first broken `seq` (FR-7.2, NFR-6).

## Phase 5 — Innovation features (week 6) · Member A (SQL), Member B (API)

Output: root-cause report, what-if simulator, versioned rules.

1. Root-cause query: recursive CTE over `co_dependency` to depth 3, `corr()` on `student_co_score`
   for the same students, rank by `path_strength × r`; `n` and `r` thresholds from config (FR-6.2).
2. Pre-fill an `improvement_action` from the top-ranked cause; UI labels output as correlational.
3. What-if API: create `whatif_scenario`, call the procedure with `p_persist = false`, return CO and
   PO baseline vs scenario (FR-6.3).
4. Versioned rules: lookup of the config valid for an offering's academic year; re-run test (NFR-4).

## Phase 6 — API, UI, security, demo (week 7) · Member B (UI), both (tests)

Output: demo-ready system.

1. Auth: bcrypt hashes in `app_user`; each request sets `app.faculty_id` (faculty) or `app.usn`
   (student) (FR-7.1).
2. PostgreSQL roles (admin, faculty, coordinator, student) with GRANTs; RLS policies on marks,
   attainment and survey-derived tables (NFR-5). Student policy: own `enrollment` rows only, read-only;
   student screen shows own CO-wise scores.
3. Screens: CSV marks upload with row errors, lock/unlock request, compute, CO-PO heatmap, CO trend,
   weakest-CO ranking, root-cause report, what-if side-by-side, audit verification.
4. Run the full PRD Section 8 test suite; record results in `docs/test-report.md`.
5. Demo script and final report.

## Test map

| PRD test | Location |
| --- | --- |
| Correctness | `tests/test_worked_example.py`, `tests/test_component_weights.py` |
| Constraints | `tests/test_constraints.py` |
| Access control | `tests/test_rls.py` (faculty A vs B; student sees only own rows) |
| Audit tamper | `tests/test_audit_chain.py` |
| Performance | `docs/explain/` reports |
| Root cause | `tests/test_root_cause.py` |
| Simulator isolation | `tests/test_whatif_isolation.py` |
| Concurrency | `tests/test_concurrency.py` |
| Reproducibility | `tests/test_versioned_rules.py` |
