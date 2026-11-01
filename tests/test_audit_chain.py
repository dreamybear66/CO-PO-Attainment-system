"""PRD Section 8 'Audit tamper' (NFR-6): the hash chain reports the first broken sequence number."""

from api.jobs import audit


def drained(db, mongo):
    moved = audit.drain_outbox(db, mongo)
    assert db.execute("SELECT count(*) FROM audit_outbox WHERE sent_at IS NULL").fetchone()[0] == 0
    return moved


def test_changes_reach_the_chain_with_before_and_after(db, mongo):
    db.execute("UPDATE co_po_map SET strength = 2 WHERE co_id = 1 AND po_id = 1")
    moved = drained(db, mongo)
    assert moved == mongo.audit_log.count_documents({})
    doc = mongo.audit_log.find_one({"table": "co_po_map", "op": "UPDATE"})
    assert doc["key"] == {"co_id": 1, "po_id": 1}
    assert (doc["before"]["strength"], doc["after"]["strength"]) == (3, 2)
    assert audit.verify(db, mongo)["ok"]


def test_compute_results_are_audited(db, mongo):
    db.execute("CALL sp_compute_attainment(1)")
    drained(db, mongo)
    assert mongo.audit_log.count_documents({"table": "co_attainment", "op": "INSERT"}) == 3


def test_edited_document_is_reported(db, mongo):
    drained(db, mongo)
    target = mongo.audit_log.find_one({"table": "student_question_mark"}, sort=[("seq", 1)])
    mongo.audit_log.update_one({"seq": target["seq"]}, {"$set": {"after.marks_obtained": 10}})
    result = audit.verify(db, mongo)
    assert not result["ok"]
    assert result["first_broken_seq"] == target["seq"]
    assert result["reason"] == "content does not match hash"


def test_deleted_document_is_reported(db, mongo):
    drained(db, mongo)
    mongo.audit_log.delete_one({"seq": 5})
    result = audit.verify(db, mongo)
    assert (result["ok"], result["first_broken_seq"]) == (False, 5)


def test_rewritten_history_is_caught_by_the_anchor(db, mongo):
    drained(db, mongo)
    seq, _ = audit.anchor(db, mongo)
    # Rewrite document 3 and re-hash everything after it, so the chain is internally consistent.
    mongo.audit_log.update_one({"seq": 3}, {"$set": {"user": "someone-else"}})
    prev = mongo.audit_log.find_one({"seq": 2})["hash"]
    for doc in mongo.audit_log.find({"seq": {"$gte": 3}}, sort=[("seq", 1)]):
        h = audit.chain_hash(prev, {**doc, "prev_hash": prev})
        mongo.audit_log.update_one({"seq": doc["seq"]}, {"$set": {"prev_hash": prev, "hash": h}})
        prev = h
    result = audit.verify(db, mongo)
    assert not result["ok"]
    assert result["first_broken_seq"] == seq
    assert "rewritten" in result["reason"]


def test_writer_recovers_without_duplicates(db, mongo):
    drained(db, mongo)
    count = mongo.audit_log.count_documents({})
    # Simulate a crash after the MongoDB insert but before the outbox was stamped.
    db.execute("UPDATE audit_outbox SET sent_at = NULL")
    assert audit.drain_outbox(db, mongo) == 0
    assert mongo.audit_log.count_documents({}) == count
    assert audit.verify(db, mongo)["ok"]


def test_denied_attempts_are_recorded(db, mongo):
    db.execute("SELECT fn_audit_denied('student_question_mark', '{\"enrollment_id\": 1, \"question_id\": 1}', "
               "'{\"error\": \"Assessment is locked\"}')")
    drained(db, mongo)
    doc = mongo.audit_log.find_one({"op": "DENIED"})
    assert doc["after"] == {"error": "Assessment is locked"}
