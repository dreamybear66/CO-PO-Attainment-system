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
- Python 3.11–3.13 (the pinned psycopg-binary, numpy and pydantic have no wheels for 3.14 yet)

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
`DEMO_PASSWORD` from `.env`. Survey respondents are stored as an HMAC of the USN keyed by
`SURVEY_HASH_SECRET`, so set both before generating.

`--reset` empties PostgreSQL and the MongoDB `survey_responses` and `audit_log` together, and the
PostgreSQL load commits only once the surveys are in MongoDB. `--database NAME` targets the
PostgreSQL and MongoDB databases of that name (e.g. `copo_test`). `pytest tests/test_datagen.py`
checks the generator without a database.

`db/seed/worked_example.sql` is the PRD Section 5 example, loaded into an empty database by the tests.

## Computing attainment

```sql
CALL sp_compute_attainment(42);      -- one offering (all its assessments must be locked)
CALL sp_compute_all();               -- every offering whose assessments are all locked
```

Results land in `co_attainment` / `po_attainment` with the offering's own rule version (another
`config_id` is refused with CP015; try other rules as a what-if scenario). COs below target get an
automatic `improvement_action`; a recompute updates its text, or closes it once the CO meets the
target. Errors use SQLSTATE class `CP` (listed at the top of each migration).

Who may run what: `sp_compute_attainment` is granted to `copo_admin` and `copo_faculty` (faculty
only for offerings they teach), `sp_compute_all` and `fn_refresh_dashboards` to `copo_admin`. The
role comes from `app.role`, which is trusted only alongside the matching `SET ROLE copo_<role>`;
owner and superuser logins (migrations, jobs, tests) set neither.

While a compute runs, the offering's assessments cannot be locked or unlocked, and dashboard reads
continue (views refresh `CONCURRENTLY`). Students cannot be enrolled into an offering with a locked
assessment.

## Tests

```powershell
.\.venv\Scripts\python.exe -m scripts.setup_db --database copo_test   # once
.\.venv\Scripts\python.exe -m pytest
```

Tests rebuild `copo_test` and re-seed the worked example before each test.
`python -m scripts.explain_report` writes the index report to `docs/explain/report.md`.
