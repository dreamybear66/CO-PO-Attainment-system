"""Apply db/migrations/*.sql in order, each in its own transaction.

Usage:
  python -m scripts.migrate                 apply pending migrations
  python -m scripts.migrate --reset         drop and recreate the public schema first
  python -m scripts.migrate --until 004     stop after the migration with this number
  python -m scripts.migrate --database X    target another database (tests use copo_test)

With --reset, the drop and every migration run in one transaction, so a failure leaves the
previous schema in place. Extensions live in the `extensions` schema, which reset keeps.
"""

import argparse
from contextlib import nullcontext
from pathlib import Path

import psycopg

from api import config

MIGRATIONS = config.ROOT / "db" / "migrations"


def number(path: Path) -> int:
    return int(path.name.split("_", 1)[0])


def migration_files(until: str | int | None = None) -> list[Path]:
    files = sorted(MIGRATIONS.glob("*.sql"), key=number)
    if until is None:
        return files
    last = int(until)
    if last not in {number(f) for f in files}:
        raise ValueError(f"No migration numbered {until}; have {', '.join(f.name for f in files)}")
    return [f for f in files if number(f) <= last]


def apply(dbname: str | None = None, *, reset: bool = False, until: str | int | None = None) -> list[str]:
    files = migration_files(until)
    applied: list[str] = []
    with psycopg.connect(config.owner_dsn(dbname), autocommit=True) as conn:
        with conn.transaction() if reset else nullcontext():
            if reset:
                conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
                conn.execute("CREATE SCHEMA public")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
            for path in files:
                if path.name in done:
                    continue
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
                applied.append(path.name)
    return applied


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--until", help="last migration number to apply, e.g. 004 or 4")
    parser.add_argument("--database")
    args = parser.parse_args()
    applied = apply(args.database, reset=args.reset, until=args.until)
    print("\n".join(f"applied {name}" for name in applied) or "nothing to apply")


if __name__ == "__main__":
    main()
