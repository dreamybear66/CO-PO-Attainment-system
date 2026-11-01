"""Settings loaded from .env (see .env.example)."""

import os
from pathlib import Path

from dotenv import load_dotenv
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str | None = None, *, allow_empty: bool = False) -> str:
    """A setting from the environment. A variable that is unset or empty falls back to the default.
    allow_empty accepts a missing value as "" (passwords under trust or SSPI authentication)."""
    value = os.getenv(name) or default
    if value is None:
        if allow_empty:
            return ""
        raise RuntimeError(f"Missing setting {name}; copy .env.example to .env and fill it in")
    return value


PG_HOST = _env("PG_HOST", "localhost")
PG_PORT = int(_env("PG_PORT", "5432"))
PG_DATABASE = _env("PG_DATABASE", "copo")

MONGO_URI = _env("MONGO_URI", "mongodb://localhost:27017")
MONGO_DATABASE = _env("MONGO_DATABASE", "copo")


def _dsn(dbname: str, user: str, password: str) -> str:
    """libpq connection string. make_conninfo quotes every value, so passwords may contain
    spaces, quotes or backslashes."""
    params = {"host": PG_HOST, "port": PG_PORT, "dbname": dbname, "user": user}
    if password:
        params["password"] = password
    return make_conninfo(**params)


def superuser_dsn(dbname: str = "postgres") -> str:
    return _dsn(dbname, _env("PG_SUPERUSER", "postgres"), _env("PG_SUPERUSER_PASSWORD", allow_empty=True))


def owner_dsn(dbname: str | None = None) -> str:
    """Schema owner: runs migrations, ETL and background jobs."""
    return _dsn(dbname or PG_DATABASE, "copo_owner", _env("PG_OWNER_PASSWORD", allow_empty=True))


def api_dsn(dbname: str | None = None) -> str:
    """Request-serving login; switches to a role per request (SET LOCAL ROLE)."""
    return _dsn(dbname or PG_DATABASE, "copo_api", _env("PG_API_PASSWORD", allow_empty=True))


def jwt_secret() -> str:
    return _env("JWT_SECRET")
