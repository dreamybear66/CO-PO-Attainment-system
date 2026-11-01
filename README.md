# CO-PO Attainment Management System

DBMS (CD252IA) project, Dept. of ISE, RV College of Engineering — Team 2.
PostgreSQL + MongoDB system that computes Course Outcome (CO) and Program Outcome (PO)
attainment from question-wise marks and course-exit surveys.

- Requirements: [PRD](https://claude.ai/artifact/G8HdvxVTjQ47XZ6AeEhard)
- Build plan: [implementation.md](implementation.md)
- Schema: [docs/er-diagram.md](docs/er-diagram.md)

## Prerequisites

- PostgreSQL 16 (Windows: `winget install PostgreSQL.PostgreSQL.16`)
- MongoDB 8 running on `localhost:27017`
- Python 3.11+

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env        # then fill in the passwords and secrets

.\.venv\Scripts\python.exe -m scripts.setup_db    # roles + database (uses the superuser password)
.\.venv\Scripts\python.exe -m scripts.migrate     # apply db/migrations in order
```

`scripts.migrate --reset` drops and recreates the schema; `--until 005` stops after a given migration.

## Synthetic data

```powershell
.\.venv\Scripts\python.exe -m datagen.generate --reset
```

One ISE programme: 16 courses, 6 batches (1,440 students), 280 offerings from 2021-22 to the current
term (2026-27 odd), ~557k question-wise marks and ~12k course-exit surveys in MongoDB. Current-term
offerings have only CIE Test 1 and Quiz 1 and stay unlocked. The 2023 batch carries the planted
root-cause story (Data Structures CO2 → DBMS CO4, with Programming in C CO5 as a decoy); see
`datagen/catalog.py`. Demo logins (`hod`, `coordinator`, `fac01`–`fac14`, four student USNs) use
`DEMO_PASSWORD` from `.env`.

`db/seed/worked_example.sql` is the PRD Section 5 example, loaded into an empty database by the tests.

## Computing attainment

```sql
CALL sp_compute_attainment(42);      -- one offering (all its assessments must be locked)
CALL sp_compute_all();               -- every offering whose assessments are all locked
```

Results land in `co_attainment` / `po_attainment` with the `config_id` used; COs below target get
an `improvement_action`. Errors use SQLSTATE class `CP` (listed at the top of each migration).

## Root cause and what-if

```sql
SELECT * FROM fn_root_cause(42, 196);         -- ranked upstream COs for a weak CO (correlational evidence)
SELECT fn_root_cause_action(42, 196);         -- pre-fill an improvement action from the top cause
CALL sp_compute_attainment(42, NULL, false, 7);  -- run what-if scenario 7 (official tables untouched)
```

`python -m scripts.evaluate_root_cause` writes detection, false-positive and noise-sensitivity results
to `docs/root-cause-evaluation.md`.

## Background jobs (surveys and audit)

```powershell
.\.venv\Scripts\python.exe -m api.jobs etl        # surveys (MongoDB) -> indirect_attainment
.\.venv\Scripts\python.exe -m api.jobs audit      # audit_outbox -> hash-chained MongoDB audit_log
.\.venv\Scripts\python.exe -m api.jobs anchor     # copy the chain head into audit_anchor
.\.venv\Scripts\python.exe -m api.jobs verify     # recompute the chain; reports the first broken seq
.\.venv\Scripts\python.exe -m api.jobs schedule   # all of the above on their schedules
```

Audited changes are written to `audit_outbox` in the same transaction as the change, so the
MongoDB chain can lag but never miss a change.

## Tests

```powershell
.\.venv\Scripts\python.exe -m scripts.setup_db --database copo_test   # once
.\.venv\Scripts\python.exe -m pytest
```

Tests rebuild `copo_test` and re-seed the worked example before each test.
`python -m scripts.explain_report` writes the index report to `docs/explain/report.md`.
