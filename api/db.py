"""Request-scoped database sessions.

Every request runs in one transaction as the caller's group role, with the session settings that
row-level security and the stored procedures read (app.role, app.faculty_id, app.usn, app.user).
"""

from contextlib import contextmanager
from dataclasses import dataclass

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from api import config

DB_ROLES = {"admin": "copo_admin", "faculty": "copo_faculty", "coordinator": "copo_coordinator",
            "student": "copo_student"}


@dataclass(frozen=True)
class User:
    user_id: int
    username: str
    role: str
    faculty_id: int | None = None
    usn: str | None = None


_pools: dict[str, ConnectionPool] = {}


def pool(dbname: str | None = None) -> ConnectionPool:
    key = dbname or config.PG_DATABASE
    if key not in _pools:
        _pools[key] = ConnectionPool(config.api_dsn(key), min_size=1, max_size=10,
                                     kwargs={"row_factory": dict_row}, open=True)
    return _pools[key]


def close_pools() -> None:
    for p in _pools.values():
        p.close()
    _pools.clear()


@contextmanager
def session(user: User, dbname: str | None = None):
    """A connection inside one transaction, acting as `user`. Commits on success."""
    with pool(dbname).connection() as conn:
        with conn.transaction():
            conn.execute(f"SET LOCAL ROLE {DB_ROLES[user.role]}")
            conn.execute(
                "SELECT set_config('app.role', %s, true), set_config('app.faculty_id', %s, true), "
                "set_config('app.usn', %s, true), set_config('app.user', %s, true)",
                (user.role, str(user.faculty_id or ""), user.usn or "", user.username),
            )
            yield conn


@contextmanager
def anonymous(dbname: str | None = None):
    """The bare API login, for the login lookup only."""
    with pool(dbname).connection() as conn:
        yield conn
