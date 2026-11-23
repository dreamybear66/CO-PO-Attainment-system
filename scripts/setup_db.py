"""Create the database roles and the application database (run once, as superuser).

Roles
  copo_owner        LOGIN, owns every object; used by migrations and background jobs
  copo_api          LOGIN NOINHERIT, member of each group role WITH INHERIT FALSE, SET TRUE;
                    the API switches to one group role per request
  copo_admin, copo_faculty, copo_coordinator, copo_student   NOLOGIN group roles

Usage:  python -m scripts.setup_db [--database NAME]
"""

import argparse

import psycopg
from psycopg import sql

from api import config

GROUP_ROLES = ("copo_admin", "copo_faculty", "copo_coordinator", "copo_student")


def ensure_login_role(cur, name: str, password: str, *, inherit: bool) -> None:
    """An empty password means none (PASSWORD NULL), for trust or SSPI authentication."""
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
    verb = "ALTER" if cur.fetchone() else "CREATE"
    cur.execute(
        sql.SQL("{} ROLE {} LOGIN {} PASSWORD {}").format(
            sql.SQL(verb),
            sql.Identifier(name),
            sql.SQL("INHERIT" if inherit else "NOINHERIT"),
            sql.Literal(password) if password else sql.SQL("NULL"),
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=config.PG_DATABASE)
    args = parser.parse_args()

    with psycopg.connect(config.superuser_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        ensure_login_role(cur, "copo_owner", config._env("PG_OWNER_PASSWORD", allow_empty=True), inherit=True)
        ensure_login_role(cur, "copo_api", config._env("PG_API_PASSWORD", allow_empty=True), inherit=False)
        for role in GROUP_ROLES:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if not cur.fetchone():
                cur.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
            # Explicit options: on PG16 a plain GRANT copies copo_api's INHERIT flag at grant time
            # and a repeated plain GRANT never changes an existing membership.
            cur.execute(sql.SQL("GRANT {} TO copo_api WITH INHERIT FALSE, SET TRUE").format(sql.Identifier(role)))

        cur.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s", (args.database,))
        row = cur.fetchone()
        if not row:
            cur.execute(
                sql.SQL("CREATE DATABASE {} OWNER copo_owner ENCODING 'UTF8'").format(
                    sql.Identifier(args.database)
                )
            )
            print(f"created database {args.database}")
        elif row[0] != "copo_owner":
            # migrate needs copo_owner to own the database: on PG15+ that is what lets it create
            # tables in, and drop and recreate, the public schema (owned by pg_database_owner).
            cur.execute(sql.SQL("ALTER DATABASE {} OWNER TO copo_owner").format(sql.Identifier(args.database)))
            print(f"database {args.database} was owned by {row[0]}; now owned by copo_owner")

    # Extensions need superuser on some installs; create them up front. They live in their own
    # schema so that `migrate --reset`, which drops public, leaves them in place.
    with psycopg.connect(config.superuser_dsn(args.database), autocommit=True) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS extensions AUTHORIZATION copo_owner")
        row = conn.execute(
            "SELECT extnamespace::regnamespace::text FROM pg_extension WHERE extname = 'btree_gist'"
        ).fetchone()
        if row is None:
            conn.execute("CREATE EXTENSION btree_gist SCHEMA extensions")
        elif row[0] != "extensions":
            conn.execute("ALTER EXTENSION btree_gist SET SCHEMA extensions")
            print(f"moved btree_gist from schema {row[0]} to extensions")

    print("roles and database ready")


if __name__ == "__main__":
    main()
