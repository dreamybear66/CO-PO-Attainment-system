"""Hash-chained audit log (PRD FR-7.2, NFR-6, S8).

drain_outbox  moves audit_outbox rows into MongoDB audit_log, each document carrying
              prev_hash and hash = SHA256(prev_hash + canonical JSON of the document).
anchor        copies the chain head into PostgreSQL audit_anchor (run daily).
verify        recomputes the chain and checks every anchor; returns the first broken seq.

Only one writer may extend the chain at a time (PostgreSQL advisory lock).
"""

import hashlib
import json
from datetime import datetime

from pymongo.database import Database

GENESIS = "0" * 64
WRITER_LOCK = 734_221   # arbitrary advisory-lock key for the chain writer
HASHED_FIELDS = ("seq", "outbox_id", "ts", "user", "table", "op", "key", "before", "after", "prev_hash")


def canonical(doc: dict) -> str:
    body = {k: doc.get(k) for k in HASHED_FIELDS}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def chain_hash(prev_hash: str, doc: dict) -> str:
    return hashlib.sha256((prev_hash + canonical(doc)).encode("utf-8")).hexdigest()


def head(mongo: Database) -> tuple[int, str]:
    last = mongo.audit_log.find_one(sort=[("seq", -1)], projection={"seq": 1, "hash": 1})
    return (last["seq"], last["hash"]) if last else (0, GENESIS)


def drain_outbox(pg, mongo: Database, batch: int = 5000) -> int:
    """Copy pending outbox rows to the chain. `pg` is an owner connection. Returns rows moved."""
    if not pg.execute("SELECT pg_try_advisory_lock(%s)", (WRITER_LOCK,)).fetchone()[0]:
        return 0        # another writer is running
    moved = 0
    try:
        while True:
            with pg.transaction():
                rows = pg.execute(
                    "SELECT outbox_id, ts, app_user, table_name, op, key, before, after "
                    "FROM audit_outbox WHERE sent_at IS NULL ORDER BY outbox_id LIMIT %s",
                    (batch,),
                ).fetchall()
                if not rows:
                    break
                ids = [r[0] for r in rows]
                done = {d["outbox_id"] for d in mongo.audit_log.find(
                    {"outbox_id": {"$in": ids}}, projection={"outbox_id": 1})}
                seq, prev = head(mongo)
                docs = []
                for outbox_id, ts, user, table, op, key, before, after in rows:
                    if outbox_id in done:
                        continue
                    seq += 1
                    doc = {"seq": seq, "outbox_id": outbox_id,
                           "ts": ts.isoformat() if isinstance(ts, datetime) else ts,
                           "user": user, "table": table, "op": op,
                           "key": key, "before": before, "after": after, "prev_hash": prev}
                    doc["hash"] = prev = chain_hash(doc["prev_hash"], doc)
                    docs.append(doc)
                if docs:
                    mongo.audit_log.insert_many(docs, ordered=True)
                pg.execute("UPDATE audit_outbox SET sent_at = now() WHERE outbox_id = ANY(%s)", (ids,))
                moved += len(docs)
    finally:
        pg.execute("SELECT pg_advisory_unlock(%s)", (WRITER_LOCK,))
    return moved


def anchor(pg, mongo: Database) -> tuple[int, str] | None:
    seq, h = head(mongo)
    if seq == 0:
        return None
    with pg.transaction():
        pg.execute("INSERT INTO audit_anchor (seq, head_hash) VALUES (%s, %s)", (seq, h))
    return seq, h


def verify(pg, mongo: Database) -> dict:
    """Walk the chain in seq order. Returns {'ok', 'checked', 'first_broken_seq', 'reason'}."""
    expected_seq, prev = 1, GENESIS
    hashes: dict[int, str] = {}
    for doc in mongo.audit_log.find({}, projection={"_id": 0}, sort=[("seq", 1)], batch_size=5000):
        seq = doc["seq"]
        if seq != expected_seq:
            return {"ok": False, "checked": expected_seq - 1, "first_broken_seq": expected_seq,
                    "reason": f"sequence gap: expected {expected_seq}, found {seq}"}
        if doc.get("prev_hash") != prev:
            return {"ok": False, "checked": seq - 1, "first_broken_seq": seq, "reason": "prev_hash does not match"}
        if chain_hash(prev, doc) != doc.get("hash"):
            return {"ok": False, "checked": seq - 1, "first_broken_seq": seq, "reason": "content does not match hash"}
        prev = doc["hash"]
        hashes[seq] = prev
        expected_seq += 1

    for seq, head_hash in pg.execute("SELECT seq, head_hash FROM audit_anchor ORDER BY seq"):
        if hashes.get(seq) != head_hash:
            return {"ok": False, "checked": expected_seq - 1, "first_broken_seq": seq,
                    "reason": "chain differs from the anchored head (history rewritten)"}
    return {"ok": True, "checked": expected_seq - 1, "first_broken_seq": None, "reason": None}
