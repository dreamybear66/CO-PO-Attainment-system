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
