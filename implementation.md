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

## Decisions needed before Phase 3

These come from PRD Section 10 and change the schema, so they must be settled first.

- [ ] S1 — weights stored as fractions (sum = 1.0) or percentages (sum = 100)?
- [ ] S5 — separate CIE / SEE weights? If yes, the split.
- [ ] S6 — absent students: exclude or count as zero?
- [ ] S10 — programme-level PO: plain average or credit-weighted?
- [ ] S11 — keep the student role in v1?

## Phase 1 — Schema and constraints (week 1) · Member A

Output: approved ER diagram and DDL.

1. ER diagram in `docs/` covering the 25 PRD tables plus the additions below.
2. `db/migrations/001_schema.sql` — all tables with PKs and FKs (FR-1.x, FR-2.x, FR-3.1, FR-4.1).
3. `002_constraints.sql` — CHECKs: CO-PO and dependency strength 1–3; marks between 0 and max;
   weight sum per S1 decision (NFR-1).
4. Schema additions from the PRD:
   - `attainment_config`: `co_target_level`, `po_target_level` (S2); CIE/SEE weights if S5 = yes;
     absent-handling flag (S6); PO aggregation mode (S10).
   - `student_question_mark`: nullable `marks_obtained`, `is_absent` (S6).
   - `whatif_scenario`: split `direct_weight` / `indirect_weight`, add `co_target_level` (S4).
   - `whatif_po_result (scenario_id, po_id, attainment)` (S3).
   - `unlock_request (request_id, assessment_id, requested_by, approved_by, reason, ts)` (S7).
   - `audit_outbox` (S8).
5. Unique constraints: `enrollment (offering_id, usn)`; `co_po_map (co_id, po_id)`.

## Phase 2 — Synthetic data (week 2) · Member B

Output: database with 500k+ mark rows.

1. `datagen/` produces departments → programmes → courses (with prerequisites) → offerings over
   3+ academic years → students, enrolments, assessments, questions, marks.
2. Planted weakness: one upstream CO lowered for a cohort, the dependent CO lowered for the same
   students, plus an unrelated decoy CO (for the FR-6.2 tests).
3. Survey documents into MongoDB with `respondent_hash`, one per (respondent, offering, survey_type) (S12).
4. Deterministic seed so test runs are reproducible.
5. `db/seed/worked_example.sql` — the exact 60-student, 3-CO case from PRD Section 5.
