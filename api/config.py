"""Settings loaded from .env (see .env.example)."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing setting {name}; copy .env.example to .env and fill it in")
    return value


PG_HOST = _env("PG_HOST", "localhost")
PG_PORT = int(_env("PG_PORT", "5432"))
PG_DATABASE = _env("PG_DATABASE", "copo")

MONGO_URI = _env("MONGO_URI", "mongodb://localhost:27017")
MONGO_DATABASE = _env("MONGO_DATABASE", "copo")


def superuser_dsn(dbname: str = "postgres") -> str:
    return (
        f"host={PG_HOST} port={PG_PORT} dbname={dbname} "
        f"user={_env('PG_SUPERUSER', 'postgres')} password={_env('PG_SUPERUSER_PASSWORD')}"
    )


def owner_dsn(dbname: str | None = None) -> str:
    """Schema owner: runs migrations, ETL and background jobs."""
    return (
        f"host={PG_HOST} port={PG_PORT} dbname={dbname or PG_DATABASE} "
        f"user=copo_owner password={_env('PG_OWNER_PASSWORD')}"
    )


def api_dsn(dbname: str | None = None) -> str:
    """Request-serving login; switches to a role per request (SET LOCAL ROLE)."""
    return (
        f"host={PG_HOST} port={PG_PORT} dbname={dbname or PG_DATABASE} "
        f"user=copo_api password={_env('PG_API_PASSWORD')}"
    )


def jwt_secret() -> str:
    return _env("JWT_SECRET")
