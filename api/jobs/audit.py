"""Hash-chained audit log (PRD FR-7.2, NFR-6, S8).

drain_outbox  moves audit_outbox rows into MongoDB audit_log, each document carrying
              prev_hash and hash = SHA256(prev_hash + canonical JSON of the document).
anchor        copies the chain head into PostgreSQL audit_anchor (run daily).
verify        recomputes the chain and checks it against PostgreSQL; returns the first broken seq.

For every row, PostgreSQL records its place in the chain (audit_outbox.chain_seq, chain_hash)
before the document is written, and stamps sent_at once MongoDB has it. So PostgreSQL always
knows where the chain should end:
  - after a crash between the two steps, the writer stamps the rows whose documents are in
    MongoDB and releases the rest to be written again;
  - documents removed from (or added to) the end of the chain stop the writer and fail verify,
    instead of being silently written over.
A PostgreSQL reset empties the outbox but not MongoDB: the chain then simply goes on from its head.

Only one writer may extend the chain at a time (PostgreSQL advisory lock). Every query runs on a
tuple-row cursor, so callers may pass connections with any row factory.
"""

import hashlib
import json
from datetime import datetime

from psycopg.rows import tuple_row
from pymongo.database import Database

GENESIS = "0" * 64
WRITER_LOCK = 734_221   # arbitrary advisory-lock key for the chain writer
HASHED_FIELDS = ("seq", "outbox_id", "ts", "user", "table", "op", "key", "before", "after", "prev_hash")


class ChainError(RuntimeError):
    """MongoDB and PostgreSQL disagree about the chain; the writer stops until someone looks."""


def canonical(doc: dict) -> str:
    body = {k: doc.get(k) for k in HASHED_FIELDS}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def chain_hash(prev_hash: str, doc: dict) -> str:
    return hashlib.sha256((prev_hash + canonical(doc)).encode("utf-8")).hexdigest()


def head(mongo: Database) -> tuple[int, str]:
    last = mongo.audit_log.find_one(sort=[("seq", -1)], projection={"seq": 1, "hash": 1})
    return (last["seq"], last["hash"]) if last else (0, GENESIS)


def _last_recorded(cur, sent_only: bool = False) -> tuple[int, str] | None:
    """The newest event PostgreSQL placed in the chain (only those confirmed sent, if asked)."""
    return cur.execute(
        "SELECT chain_seq, chain_hash FROM audit_outbox WHERE chain_seq IS NOT NULL"
        + (" AND sent_at IS NOT NULL" if sent_only else "")
        + " ORDER BY chain_seq DESC LIMIT 1"
    ).fetchone()


def _recover(pg, cur, mongo: Database) -> None:
    """Resolve rows placed in the chain whose sent_at was never stamped (the writer stopped
    between writing MongoDB and stamping): stamp those whose document is there, release the rest."""
    with pg.transaction():
        placed = cur.execute(
            "SELECT outbox_id, chain_seq, chain_hash FROM audit_outbox "
            "WHERE sent_at IS NULL AND chain_seq IS NOT NULL"
        ).fetchall()
        if not placed:
            return
        written = {d["seq"]: d.get("hash") for d in mongo.audit_log.find(
            {"seq": {"$in": [p[1] for p in placed]}}, projection={"seq": 1, "hash": 1})}
        sent = [p[0] for p in placed if written.get(p[1]) == p[2]]
        unsent = [p[0] for p in placed if written.get(p[1]) != p[2]]
        cur.execute("UPDATE audit_outbox SET sent_at = now() WHERE outbox_id = ANY(%s)", (sent,))
        cur.execute("UPDATE audit_outbox SET chain_seq = NULL, chain_hash = NULL WHERE outbox_id = ANY(%s)",
                    (unsent,))


def _tip(cur, mongo: Database) -> tuple[int, str]:
    """Where the next document goes. MongoDB's head must be the last event PostgreSQL recorded."""
    recorded = _last_recorded(cur)
    mongo_head = head(mongo)
    if recorded is None:            # nothing written from this database yet (new or reset)
        return mongo_head
    if tuple(recorded) != mongo_head:
        raise ChainError(
            f"MongoDB audit_log ends at #{mongo_head[0]}, but PostgreSQL recorded #{recorded[0]} as the "
            "last event in the chain; run `python -m api.jobs verify` and investigate before writing more")
    return recorded[0], recorded[1]


def drain_outbox(pg, mongo: Database, batch: int = 5000) -> int:
    """Copy pending outbox rows to the chain. `pg` is an owner connection in autocommit mode.
    Returns the number of documents written."""
    cur = pg.cursor(row_factory=tuple_row)
    if not cur.execute("SELECT pg_try_advisory_lock(%s)", (WRITER_LOCK,)).fetchone()[0]:
        return 0        # another writer is running
    moved = 0
    try:
        _recover(pg, cur, mongo)
        while True:
            # 1. place the batch in the chain (committed before MongoDB is touched)
            with pg.transaction():
                rows = cur.execute(
                    "SELECT outbox_id, ts, app_user, table_name, op, key, before, after "
                    "FROM audit_outbox WHERE sent_at IS NULL AND chain_seq IS NULL "
                    "ORDER BY outbox_id LIMIT %s",
                    (batch,),
                ).fetchall()
                if not rows:
                    break
                seq, prev = _tip(cur, mongo)
                docs = []
                for outbox_id, ts, user, table, op, key, before, after in rows:
                    seq += 1
                    doc = {"seq": seq, "outbox_id": outbox_id,
                           "ts": ts.isoformat() if isinstance(ts, datetime) else ts,
                           "user": user, "table": table, "op": op,
                           "key": key, "before": before, "after": after, "prev_hash": prev}
                    doc["hash"] = prev = chain_hash(doc["prev_hash"], doc)
                    docs.append(doc)
                ids = [d["outbox_id"] for d in docs]
                cur.execute(
                    "UPDATE audit_outbox o SET chain_seq = p.seq, chain_hash = p.hash "
                    "FROM unnest(%s::bigint[], %s::bigint[], %s::text[]) AS p(outbox_id, seq, hash) "
                    "WHERE o.outbox_id = p.outbox_id",
                    (ids, [d["seq"] for d in docs], [d["hash"] for d in docs]),
                )
            # 2. write the documents, 3. confirm them
            mongo.audit_log.insert_many(docs, ordered=True)
            with pg.transaction():
                cur.execute("UPDATE audit_outbox SET sent_at = now() WHERE outbox_id = ANY(%s)", (ids,))
            moved += len(docs)
    finally:
        cur.execute("SELECT pg_advisory_unlock(%s)", (WRITER_LOCK,))
    return moved


def anchor(pg, mongo: Database) -> tuple[int, str] | None:
    """Copy the chain head into audit_anchor. Waits for a running writer, and refuses to anchor a
    head that disagrees with PostgreSQL."""
    cur = pg.cursor(row_factory=tuple_row)
    cur.execute("SELECT pg_advisory_lock(%s)", (WRITER_LOCK,))
    try:
        _recover(pg, cur, mongo)
        seq, h = _tip(cur, mongo)
        if seq == 0:
            return None
        with pg.transaction():
            cur.execute("INSERT INTO audit_anchor (seq, head_hash) VALUES (%s, %s)", (seq, h))
        return seq, h
    finally:
        cur.execute("SELECT pg_advisory_unlock(%s)", (WRITER_LOCK,))


def verify(pg, mongo: Database) -> dict:
    """Walk the chain in seq order and compare it with what PostgreSQL holds: the daily anchors and
    the last event the writer confirmed. Returns {'ok', 'checked', 'first_broken_seq', 'reason'}."""
    cur = pg.cursor(row_factory=tuple_row)
    # Read PostgreSQL first: anchors and events added while the walk runs are not compared, so a
    # long walk cannot raise a false alarm.
    checks = [(seq, h, "anchored head") for seq, h in
              cur.execute("SELECT seq, head_hash FROM audit_anchor").fetchall()]
    last = _last_recorded(cur, sent_only=True)
    if last:
        checks.append((last[0], last[1], "last event recorded in PostgreSQL"))
    checks.sort()

    def broken(seq: int, reason: str) -> dict:
        return {"ok": False, "checked": seq - 1, "first_broken_seq": seq, "reason": reason}

    expected_seq, prev, i = 1, GENESIS, 0
    for doc in mongo.audit_log.find({}, projection={"_id": 0}, sort=[("seq", 1)], batch_size=5000):
        seq = doc["seq"]
        if seq != expected_seq:
            return broken(expected_seq, f"sequence gap: expected {expected_seq}, found {seq}")
        if doc.get("prev_hash") != prev:
            return broken(seq, "prev_hash does not match")
        if chain_hash(prev, doc) != doc.get("hash"):
            return broken(seq, "content does not match hash")
        prev = doc["hash"]
        while i < len(checks) and checks[i][0] == seq:
            if checks[i][1] != prev:
                return broken(seq, f"chain differs from the {checks[i][2]} (history rewritten)")
            i += 1
        expected_seq += 1

    if i < len(checks):
        return broken(expected_seq, f"documents from #{expected_seq} are missing: PostgreSQL holds the "
                                    f"{checks[-1][2]} at #{checks[-1][0]}")
    return {"ok": True, "checked": expected_seq - 1, "first_broken_seq": None, "reason": None}
