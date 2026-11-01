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
`DEMO_PASSWORD` from `.env`.

`db/seed/worked_example.sql` is the PRD Section 5 example, loaded into an empty database by the tests.
