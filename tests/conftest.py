"""Test fixtures. Tests run against a separate database (copo_test), migrated once per session
and re-seeded with the PRD worked example before every test."""

from contextlib import contextmanager

import psycopg
import pytest

from api import config
from scripts import migrate

TEST_DB = "copo_test"
SEED = config.ROOT / "db" / "seed" / "worked_example.sql"


@pytest.fixture(scope="session")
def migrated():
    migrate.apply(TEST_DB, reset=True)


def truncate_all(conn) -> None:
    tables = conn.execute(
        "SELECT string_agg(quote_ident(tablename), ', ') FROM pg_tables "
        "WHERE schemaname = 'public' AND tablename <> 'schema_migrations'"
    ).fetchone()[0]
    conn.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")


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


@contextmanager
def raises_sqlstate(sqlstate: str):
    """Assert the block fails with the given SQLSTATE (e.g. 'CP001', '23514')."""
    with pytest.raises(psycopg.Error) as info:
        yield info
    assert info.value.sqlstate == sqlstate, f"expected {sqlstate}, got {info.value.sqlstate}: {info.value}"
