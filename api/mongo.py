"""MongoDB access: survey_responses and the hash-chained audit_log."""

import threading

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database

from api import config

_clients: dict[str, MongoClient] = {}
_indexed: set[tuple[str, str]] = set()      # (uri, database) whose indexes exist
_lock = threading.Lock()


def get_db(name: str | None = None) -> Database:
    """The database, with its indexes created on first use in this process."""
    name = name or config.MONGO_DATABASE
    with _lock:
        client = _clients.get(config.MONGO_URI)
        if client is None:
            client = _clients[config.MONGO_URI] = MongoClient(config.MONGO_URI, tz_aware=True)
    db = client[name]
    if (config.MONGO_URI, name) not in _indexed:
        ensure_indexes(db)
        _indexed.add((config.MONGO_URI, name))
    return db


def reset_collections(db: Database, *names: str) -> None:
    """Drop collections and recreate their indexes (tests, demo builds)."""
    for name in names:
        db.drop_collection(name)
    ensure_indexes(db)


def ensure_indexes(db: Database) -> None:
    # One response per respondent, offering and survey type (S12).
    db.survey_responses.create_index(
        [("respondent_hash", ASCENDING), ("offering_id", ASCENDING), ("survey_type", ASCENDING)],
        unique=True, name="one_response_per_respondent",
    )
    db.survey_responses.create_index([("offering_id", ASCENDING)], name="by_offering")
    db.audit_log.create_index([("seq", DESCENDING)], unique=True, name="seq")
    # Lets the writer skip rows it already copied if it crashed before stamping the outbox.
    db.audit_log.create_index([("outbox_id", ASCENDING)], unique=True, name="outbox_id")
