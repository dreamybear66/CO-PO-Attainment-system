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

## Background jobs (surveys and audit)

```powershell
.\.venv\Scripts\python.exe -m api.jobs etl        # surveys (MongoDB) -> indirect_attainment, then recompute
.\.venv\Scripts\python.exe -m api.jobs audit      # audit_outbox -> hash-chained MongoDB audit_log
.\.venv\Scripts\python.exe -m api.jobs anchor     # copy the chain head into audit_anchor
.\.venv\Scripts\python.exe -m api.jobs verify     # recompute the chain; reports the first broken seq
.\.venv\Scripts\python.exe -m api.jobs schedule   # all of the above on their schedules
```

- **Surveys.** A response is accepted once the offering is finished (all assessments locked), from an
  enrolled student, and must rate every CO of the course 1–5. Respondents are stored as a keyed hash
  (`SURVEY_HASH_SECRET`). The ETL stores respondents and % favourable per (offering, CO), using the
  rule version's `favourable_rating` (default 4); the engine turns that % into a level with the
  thresholds of each run. Groups without responses are removed, and offerings with official results
  whose survey input changed are recomputed; one that cannot be (an assessment unlocked again) is
  reported and keeps its results.
- **Audit chain.** Audited changes (marks, maps, rules, results, survey input, logins, enrolments,
  workflow, and `TRUNCATE`) are written to `audit_outbox` in the same transaction as the change, so
  the MongoDB chain can lag but never miss a change. Password hashes are never copied. Only the API
  login's `app.user` names the person; other sessions are recorded under their login.
- **Chain and PostgreSQL agree.** The writer records each event's place in the chain in the outbox
  before writing MongoDB, so after a crash it knows what reached MongoDB, and `verify` treats the last
  recorded event as an anchor: deleting the newest documents is reported, and the writer stops
  (`ChainError`) rather than writing over the gap. A PostgreSQL reset does not break the chain; it
  carries on from its head.
- **Schedule.** Outbox every 30 s, ETL 01:30, verify 02:00, anchor 23:55 (Asia/Kolkata). A run
  missed while the machine was off happens once when it is back.

## Tests

```powershell
.\.venv\Scripts\python.exe -m scripts.setup_db --database copo_test   # once
.\.venv\Scripts\python.exe -m pytest
```

Tests rebuild `copo_test` and re-seed the worked example before each test.
`python -m scripts.explain_report` writes the index report to `docs/explain/report.md`.
