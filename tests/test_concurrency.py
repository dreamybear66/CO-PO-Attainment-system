"""PRD Section 8 'Concurrency' (NFR-3) and NFR-2 atomicity."""

from decimal import Decimal as D

import psycopg
import pytest

from tests.conftest import raises_sqlstate


def test_second_run_waits_or_is_refused(db, connect):
    first = connect(autocommit=False)
    first.execute("CALL sp_compute_attainment(1)")          # holds the offering row lock

    second = connect()
    second.execute("SET lock_timeout = '500ms'")
    with raises_sqlstate("55P03"):                          # lock_not_available: refused
        second.execute("CALL sp_compute_attainment(1)")

    first.commit()
    second.execute("CALL sp_compute_attainment(1)")         # proceeds once the first commits
    assert db.execute("SELECT count(*) FROM co_attainment WHERE offering_id = 1").fetchone()[0] == 3


def test_failed_run_leaves_previous_results(db):
    db.execute("CALL sp_compute_attainment(1)")
    before = db.execute("SELECT co_id, final_level, computed_at FROM co_attainment ORDER BY co_id").fetchall()

    db.execute("INSERT INTO course_outcome (course_id, co_number, statement, bloom_level) VALUES (1, 4, 'untested', 2)")
    with pytest.raises(psycopg.Error):
        db.execute("CALL sp_compute_attainment(1)")

    after = db.execute("SELECT co_id, final_level, computed_at FROM co_attainment ORDER BY co_id").fetchall()
    assert after == before
    assert [r[1] for r in after] == [D("3.00"), D("2.20"), D("0.40")]
