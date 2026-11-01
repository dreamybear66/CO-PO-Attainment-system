"""Build the full demo database from scratch.

  reset schema -> all migrations -> synthetic data -> survey ETL -> compute every offering
  -> chain the audit outbox -> anchor -> verify

Usage:  python -m scripts.demo
"""

import time

import psycopg

from api import config
from api.jobs import audit, etl
from api.mongo import get_db
from datagen import generate
from scripts import migrate


def step(label, fn):
    started = time.perf_counter()
    result = fn()
    print(f"{label:<28} {time.perf_counter() - started:6.1f}s  {result if result is not None else ''}")
    return result


def main() -> None:
    step("migrations", lambda: len(migrate.apply(reset=True)))
    b = generate.Builder(2026)

    def load():
        b.master()
        batches = b.students()
        b.offerings(batches)
        b.users(batches)
        generate.load_postgres(b, None, reset=False)
        generate.load_mongo(b, reset=True)

    step("synthetic data", load)
    mongo = get_db()
    mongo.audit_log.drop()
    with psycopg.connect(config.owner_dsn(), autocommit=True) as pg:
        step("survey ETL", lambda: etl.run_survey_etl(pg, mongo))
        step("compute all offerings", lambda: pg.execute("CALL sp_compute_all()") and None)
        step("audit chain", lambda: audit.drain_outbox(pg, mongo, batch=20000))
        step("anchor", lambda: audit.anchor(pg, mongo))
        step("verify", lambda: audit.verify(pg, mongo))


if __name__ == "__main__":
    main()
