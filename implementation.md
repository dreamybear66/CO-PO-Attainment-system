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
