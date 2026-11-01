"""Run background jobs by hand or on a schedule.

  python -m api.jobs etl          survey ETL into indirect_attainment
  python -m api.jobs audit        move pending audit rows into the MongoDB chain
  python -m api.jobs anchor       copy the chain head into audit_anchor
  python -m api.jobs verify       recompute the chain; exit 1 if broken
  python -m api.jobs schedule     run all of the above on their schedules (foreground)
"""

import json
import sys

import psycopg

from api import config
from api.jobs import audit, etl
from api.mongo import get_db


def run(job: str, dbname: str | None = None, mongo_name: str | None = None) -> dict:
    mongo = get_db(mongo_name)
    with psycopg.connect(config.owner_dsn(dbname), autocommit=True) as pg:
        if job == "etl":
            return etl.run_survey_etl(pg, mongo)
        if job == "audit":
            return {"moved": audit.drain_outbox(pg, mongo)}
        if job == "anchor":
            result = audit.anchor(pg, mongo)
            return {"seq": result[0], "hash": result[1]} if result else {"seq": None}
        if job == "verify":
            return audit.verify(pg, mongo)
    raise SystemExit(f"unknown job {job!r}")


def schedule() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler

    s = BlockingScheduler(timezone="Asia/Kolkata")
    s.add_job(lambda: print("audit", run("audit")), "interval", seconds=30, id="audit", max_instances=1)
    s.add_job(lambda: print("etl", run("etl")), "cron", hour=1, minute=30, id="etl")
    s.add_job(lambda: print("anchor", run("anchor")), "cron", hour=23, minute=55, id="anchor")
    s.add_job(lambda: print("verify", run("verify")), "cron", hour=2, minute=0, id="verify")
    print("scheduler running (Ctrl+C to stop)")
    s.start()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    if sys.argv[1] == "schedule":
        schedule()
        return
    result = run(sys.argv[1])
    print(json.dumps(result, default=str))
    if sys.argv[1] == "verify" and not result["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
