"""Test fixtures. Tests run against a separate database (copo_test), migrated once per session
and re-seeded with the PRD worked example before every test."""

from contextlib import contextmanager

import psycopg
import pytest

from api import config
from scripts import migrate
from scripts.migrate import truncate_all  # also refreshes materialized views, so none stay stale

TEST_DB = "copo_test"
SEED = config.ROOT / "db" / "seed" / "worked_example.sql"


@pytest.fixture(scope="session")
def migrated():
    migrate.apply(TEST_DB, reset=True)
    # The API's group roles reach the routines granted to them through the schema.
    with psycopg.connect(config.owner_dsn(TEST_DB), autocommit=True) as conn:
        conn.execute("GRANT USAGE ON SCHEMA public TO copo_admin, copo_faculty, copo_coordinator, copo_student")


@pytest.fixture
def db(migrated):
    """Owner connection (autocommit) on a freshly seeded worked example."""
    conn = psycopg.connect(config.owner_dsn(TEST_DB), autocommit=True)
    truncate_all(conn)
    conn.execute(SEED.read_text(encoding="utf-8"))
    yield conn
    conn.close()


@pytest.fixture
def connect(migrated):
    """Factory for extra owner connections (concurrency tests)."""
    opened = []

    def _connect(autocommit=True):
        conn = psycopg.connect(config.owner_dsn(TEST_DB), autocommit=autocommit)
        opened.append(conn)
        return conn

    yield _connect
    for conn in opened:
        conn.close()


@pytest.fixture
def api_connect(migrated):
    """Factory for API-login connections acting as an application role, as api/db.py does:
    SET ROLE copo_<role> plus app.role / app.faculty_id. app_role overrides the app.role setting."""
    opened = []

    def _connect(role, faculty_id=None, autocommit=True, app_role=None):
        conn = psycopg.connect(config.api_dsn(TEST_DB), autocommit=autocommit)
        opened.append(conn)
        conn.execute(f"SET ROLE copo_{role}")
        conn.execute("SELECT set_config('app.role', %s, false), set_config('app.faculty_id', %s, false)",
                     (app_role or role, str(faculty_id or "")))
        return conn

    yield _connect
    for conn in opened:
        conn.close()


@contextmanager
def raises_sqlstate(sqlstate: str):
    """Assert the block fails with the given SQLSTATE (e.g. 'CP001', '23514')."""
    with pytest.raises(psycopg.Error) as info:
        yield info
    assert info.value.sqlstate == sqlstate, f"expected {sqlstate}, got {info.value.sqlstate}: {info.value}"
