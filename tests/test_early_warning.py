"""Weak-student lists and early warning (phase 9, FR-6.4, FR-6.5).

History: six earlier offerings of the worked-example course, each with CIE Test 1 and a SEE, whose
marks come from one hidden skill per student and CO, so CIE Test 1 says something about the end.
Target: a later offering with only CIE Test 1, which the teacher locks.
"""

import bcrypt
import numpy as np
import psycopg
import pytest
from fastapi.testclient import TestClient

from api import config
from api import db as api_db
from api.main import app
from api.services import early_warning
from tests import conftest

PASSWORD = "test-password"
TARGET = 200
HISTORY = [(101, "2021-22", "odd"), (102, "2021-22", "even"), (103, "2022-23", "odd"),
           (104, "2022-23", "even"), (105, "2023-24", "odd"), (106, "2023-24", "even")]


def add(db, oid, year, term, rng, students=40, see=True, lock=True):
    """An offering of course 1 with CIE Test 1 (and SEE), one 10-mark question per CO."""
    db.execute("INSERT INTO course_offering VALUES (%s, 1, %s, %s, 1, 'A')", (oid, year, term))
    kinds = [("CIE_THEORY", "CIE Test 1")] + ([("SEE", "SEE")] if see else [])
    aids = []
    for k, (kind, name) in enumerate(kinds, start=1):
        aid = oid * 10 + k
        aids.append(aid)
        db.execute("INSERT INTO assessment (assessment_id, offering_id, type, name, max_marks) VALUES (%s, %s, %s, %s, 30)",
                   (aid, oid, kind, name))
        for co in (1, 2, 3):
            db.execute("INSERT INTO assessment_question VALUES (%s, %s, %s, 10)", (aid * 10 + co, aid, f"Q{co}"))
            db.execute("INSERT INTO question_co_map VALUES (%s, %s, 1)", (aid * 10 + co, co))
    marks, cie = [], {}
    for i in range(1, students + 1):
        usn, eid = f"1RV{oid % 100:02d}WX{i:03d}", oid * 1000 + i
        db.execute("INSERT INTO student (usn, name, program_id, admission_year, section) VALUES (%s, %s, 1, 2021, 'A')",
                   (usn, f"Student {oid}-{i}"))
        db.execute("INSERT INTO enrollment VALUES (%s, %s, %s)", (eid, oid, usn))
        for co in (1, 2, 3):
            skill = rng.normal(0.62, 0.2)
            for aid in aids:
                m = int(np.clip(round(10 * (skill + rng.normal(0, 0.08))), 0, 10))
                marks.append((eid, aid * 10 + co, m))
                if aid == aids[0]:
                    cie[(usn, co)] = m
    with db.cursor() as c:
        c.executemany("INSERT INTO student_question_mark VALUES (%s, %s, %s, false)", marks)
    if lock:
        db.execute("UPDATE assessment SET locked = true WHERE offering_id = %s", (oid,))
    return cie


@pytest.fixture
def history(db):
    rng = np.random.default_rng(5)
    for oid, year, term in HISTORY:
        add(db, oid, year, term, rng)
    return add(db, TARGET, "2026-27", "odd", rng, see=False, lock=False)


@pytest.fixture
def client(db, mongo, history):
    pw = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(4)).decode()
    db.execute("INSERT INTO faculty VALUES (2, 1, 'Faculty B', 'b@example.edu')")
    db.execute("""
        INSERT INTO app_user (user_id, username, password_hash, role, faculty_id, usn) VALUES
            (1, 'fac_a', %(pw)s, 'faculty', 1, NULL), (2, 'fac_b', %(pw)s, 'faculty', 2, NULL),
            (4, 'coord', %(pw)s, 'coordinator', NULL, NULL)""", {"pw": pw})
    app.state.dbname = conftest.TEST_DB
    app.state.mongo_name = conftest.TEST_DB
    with TestClient(app) as c:
        yield c
    api_db.close_pools()


def login(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def owner():
    return psycopg.connect(config.owner_dsn(conftest.TEST_DB))


def test_needs_a_locked_cie_and_a_running_term(db, history):
    with owner() as pg, pytest.raises(early_warning.EarlyWarningError, match="Lock a CIE"):
        early_warning.predict(pg, TARGET)
    with owner() as pg, pytest.raises(early_warning.EarlyWarningError, match="results are in"):
        early_warning.predict(pg, 101)


def test_weaker_cie_marks_mean_higher_risk_with_reasons(db, history):
    db.execute("UPDATE assessment SET locked = true WHERE offering_id = %s", (TARGET,))
    with owner() as pg:
        r = early_warning.predict(pg, TARGET)
    assert r["stage"] == [{"type": "CIE_THEORY", "rank": 1, "name": "CIE Test 1"}]
    m = r["model"]
    assert m["training_offerings"] == 6 and m["training_rows"] == 6 * 40 * 3 and m["training_auc"] > 0.75
    assert m["coefficients"]["co_so_far"] < 0                      # more marks so far, less risk
    p = {(x["usn"], x["co_id"]): x for x in r["predictions"]}
    low = [p[k]["probability"] for k, v in history.items() if v <= 3]
    high = [p[k]["probability"] for k, v in history.items() if v >= 8]
    assert np.mean(low) > 0.7 > 0.3 > np.mean(high)
    flagged = [x for x in r["predictions"] if x["flagged"]]
    assert flagged and all(x["probability"] >= 0.5 for x in flagged)
    assert all(x["reasons"][0]["feature"] == "co_so_far" and "marks so far" in x["reasons"][0]["label"] for x in flagged)


def test_cut_off_comes_from_the_rule_version(db, history):
    db.execute("UPDATE assessment SET locked = true WHERE offering_id = %s", (TARGET,))
    counts = []
    for cut in (0.3, 0.8):
        db.execute("UPDATE attainment_config SET ew_flag_prob = %s", (cut,))
        with owner() as pg:
            counts.append(sum(x["flagged"] for x in early_warning.predict(pg, TARGET)["predictions"]))
    assert counts[0] > counts[1] > 0


def test_locking_a_cie_runs_the_warning_and_leaves_official_results_alone(client, db):
    h = login(client, "fac_a")
    before = db.execute("SELECT count(*) FROM co_attainment").fetchone()[0]
    assert client.post(f"/api/assessments/{TARGET * 10 + 1}/lock", headers=h).json() == {"locked": True}
    run = db.execute("SELECT stage, flag_prob FROM early_warning_run WHERE offering_id = %s", (TARGET,)).fetchone()
    assert run[0][0]["name"] == "CIE Test 1" and float(run[1]) == 0.5
    assert db.execute("SELECT count(*) FROM early_warning WHERE offering_id = %s", (TARGET,)).fetchone()[0] == 120
    assert db.execute("SELECT count(*) FROM co_attainment").fetchone()[0] == before
    body = client.get(f"/api/offerings/{TARGET}/students", headers=h).json()
    ew = body["early_warning"]
    assert ew["stage"][0]["name"] == "CIE Test 1" and ew["flagged"]
    assert all(f["name"].startswith("Student") and f["reasons"] for f in ew["flagged"])


def test_weak_student_lists_are_the_students_below_target(client, db, history):
    h = login(client, "fac_a")
    body = client.get(f"/api/offerings/{TARGET}/students", headers=h).json()
    assert body["target_pct"] == 60.0 and body["finished"] is False and body["early_warning"] is None
    for co in body["weak"]:
        expected = sorted(u for (u, c), v in history.items() if c == co["co_number"] and 10 * v < 60)
        assert sorted(s["usn"] for s in co["below"]) == expected
        assert co["scored"] == 40


def test_who_may_see_and_run(client, db):
    db.execute("UPDATE assessment SET locked = true WHERE offering_id = %s", (TARGET,))
    assert client.get(f"/api/offerings/{TARGET}/students", headers=login(client, "fac_b")).status_code == 404
    assert client.post(f"/api/offerings/{TARGET}/early-warning", headers=login(client, "fac_b")).status_code == 404
    assert client.post(f"/api/offerings/{TARGET}/early-warning", headers=login(client, "coord")).status_code == 403
    assert client.get(f"/api/offerings/{TARGET}/students", headers=login(client, "coord")).status_code == 200
    r = client.post(f"/api/offerings/{TARGET}/early-warning", headers=login(client, "fac_a"))
    assert r.status_code == 200 and r.json()["predictions"] == 120
    r = client.post("/api/offerings/1/early-warning", headers=login(client, "fac_a"))     # the seed: SEE only, locked
    assert r.status_code == 409
