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


def add_offering(db, offering_id, academic_year, term, marks, section="A"):
    """A locked offering of the worked-example course: one SEE with a 10-mark question per CO 1-3,
    and one new student per entry of `marks`, each a (CO1, CO2, CO3) tuple of marks out of 10."""
    aid = offering_id * 10
    db.execute("INSERT INTO course_offering VALUES (%s, 1, %s, %s, 1, %s)", (offering_id, academic_year, term, section))
    db.execute("INSERT INTO assessment (assessment_id, offering_id, type, name, max_marks) "
               "VALUES (%s, %s, 'SEE', 'SEE', 30)", (aid, offering_id))
    for co in (1, 2, 3):
        db.execute("INSERT INTO assessment_question VALUES (%s, %s, %s, 10)", (aid * 10 + co, aid, f"Q{co}"))
        db.execute("INSERT INTO question_co_map VALUES (%s, %s, 1)", (aid * 10 + co, co))
    for i, row in enumerate(marks, start=1):
        usn, eid = f"1RV{offering_id:02d}WX{i:03d}", offering_id * 1000 + i
        db.execute("INSERT INTO student (usn, name, program_id, admission_year, section) "
                   "VALUES (%s, %s, 1, 2025, %s)", (usn, usn, section))
        db.execute("INSERT INTO enrollment VALUES (%s, %s, %s)", (eid, offering_id, usn))
        for co, mark in zip((1, 2, 3), row):
            db.execute("INSERT INTO student_question_mark VALUES (%s, %s, %s, false)", (eid, aid * 10 + co, mark))
    db.execute("UPDATE assessment SET locked = true WHERE assessment_id = %s", (aid,))
