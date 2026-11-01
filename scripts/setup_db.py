"""Create the database roles and the application database (run once, as superuser).

Roles
  copo_owner        LOGIN, owns every object; used by migrations and background jobs
  copo_api          LOGIN NOINHERIT; the API switches to one group role per request
  copo_admin, copo_faculty, copo_coordinator, copo_student   NOLOGIN group roles

Usage:  python -m scripts.setup_db [--database NAME]
"""

import argparse

import psycopg
from psycopg import sql

from api import config

GROUP_ROLES = ("copo_admin", "copo_faculty", "copo_coordinator", "copo_student")


def ensure_login_role(cur, name: str, password: str, *, inherit: bool) -> None:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
    verb = "ALTER" if cur.fetchone() else "CREATE"
    cur.execute(
        sql.SQL("{} ROLE {} LOGIN {} PASSWORD {}").format(
            sql.SQL(verb),
            sql.Identifier(name),
            sql.SQL("INHERIT" if inherit else "NOINHERIT"),
            sql.Literal(password),
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=config.PG_DATABASE)
    args = parser.parse_args()

    with psycopg.connect(config.superuser_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        ensure_login_role(cur, "copo_owner", config._env("PG_OWNER_PASSWORD"), inherit=True)
        ensure_login_role(cur, "copo_api", config._env("PG_API_PASSWORD"), inherit=False)
        for role in GROUP_ROLES:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if not cur.fetchone():
                cur.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
            cur.execute(sql.SQL("GRANT {} TO copo_api").format(sql.Identifier(role)))

        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (args.database,))
        if not cur.fetchone():
            cur.execute(
                sql.SQL("CREATE DATABASE {} OWNER copo_owner ENCODING 'UTF8'").format(
                    sql.Identifier(args.database)
                )
            )
            print(f"created database {args.database}")

    # Extensions need superuser on some installs; create them up front.
    with psycopg.connect(config.superuser_dsn(args.database), autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    print("roles and database ready")


if __name__ == "__main__":
    main()
