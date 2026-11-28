"""End-to-end API flows: login, typed marks, lock, compute, unlock approval, what-if, student view."""

import bcrypt
import pytest
from fastapi.testclient import TestClient

from api import db as api_db
from api.main import app
from tests import conftest

PASSWORD = "test-password"


@pytest.fixture
def client(db, mongo):
    pw = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(4)).decode()
    db.execute("INSERT INTO faculty VALUES (2, 1, 'Faculty B', 'b@example.edu')")
    db.execute("""
        INSERT INTO app_user (user_id, username, password_hash, role, faculty_id, usn) VALUES
            (1, 'fac_a', %(pw)s, 'faculty', 1, NULL),
            (2, 'fac_b', %(pw)s, 'faculty', 2, NULL),
            (3, 'hod', %(pw)s, 'admin', NULL, NULL),
            (4, 'coord', %(pw)s, 'coordinator', NULL, NULL),
            (5, '1rv25wx001', %(pw)s, 'student', NULL, '1RV25WX001')""", {"pw": pw})
    db.execute("""
        INSERT INTO assessment (assessment_id, offering_id, type, name, max_marks) VALUES (2, 1, 'EL', 'Experiential Learning', 4);
        INSERT INTO assessment_question VALUES (21, 2, 'Q1', 4);       -- EL: one final mark, no CO
    """)
    app.state.dbname = conftest.TEST_DB
    app.state.mongo_name = conftest.TEST_DB
    with TestClient(app) as c:
        yield c
    api_db.close_pools()


def login(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def full_marks(client, h, assessment_id=2, fill=2):
    """Every enrolled student with every question filled in, from the typed-marks table."""
    sheet = client.get(f"/api/assessments/{assessment_id}/marks", headers=h).json()
    return [{"usn": s["usn"], "marks": {q["q_no"]: fill for q in sheet["questions"]}} for s in sheet["students"]]


def test_login_rejects_wrong_password(client):
    assert client.post("/api/auth/login", json={"username": "fac_a", "password": "nope"}).status_code == 401
    assert client.get("/api/offerings").status_code == 401


def test_faculty_lists_only_own_offerings(client):
    assert [o["offering_id"] for o in client.get("/api/offerings", headers=login(client, "fac_a")).json()] == [1]
    assert client.get("/api/offerings", headers=login(client, "fac_b")).json() == []
    assert client.get("/api/offerings/1", headers=login(client, "fac_b")).status_code == 404


def test_typed_marks_with_errors_save_nothing(client, db):
    h = login(client, "fac_a")
    rows = [{"usn": "1RV25WX001", "marks": {"Q1": 5}},
            {"usn": "1rv25wx002", "marks": {"Q1": "x"}},
            {"usn": "NOSUCH", "marks": {"Q1": 1}},
            {"usn": "1RV25WX003", "marks": {"Q9": 1, "Q2": None}}]
    r = client.put("/api/assessments/2/marks", headers=h, json=rows)
    assert r.status_code == 422
    problems = {(e["row"], e["usn"], e["column"]) for e in r.json()["errors"]}
    assert problems == {(1, "1RV25WX001", "Q1"), (2, "1RV25WX002", "Q1"), (3, "NOSUCH", "usn"),
                        (4, "1RV25WX003", "Q9"), (4, "1RV25WX003", "Q2")}
    assert db.execute("SELECT count(*) FROM student_question_mark WHERE question_id IN (21, 22)").fetchone()[0] == 0


def test_typed_marks_lock_compute_flow(client, db):
    h = login(client, "fac_a")
    assert client.put("/api/assessments/2/marks", headers=h, json=full_marks(client, h)).json() == {"saved": 60}
    sheet = client.get("/api/assessments/2/marks", headers=login(client, "coord")).json()     # the coordinator reads
    assert sheet["type"] == "EL" and sheet["students"][0]["marks"] == {"Q1": 2}
    assert client.post("/api/assessments/2/lock", headers=h).status_code == 200
    result = client.post("/api/offerings/1/compute", headers=h).json()
    assert len(result["cos"]) == 3 and len(result["pos"]) == 2
    assert client.post("/api/offerings/1/compute", headers=login(client, "coord")).status_code == 403


def test_locked_typed_marks_are_refused_and_logged(client, db):
    h = login(client, "fac_a")
    client.put("/api/assessments/2/marks", headers=h, json=full_marks(client, h))
    client.post("/api/assessments/2/lock", headers=h)
    r = client.put("/api/assessments/2/marks", headers=h, json=[{"usn": "1RV25WX001", "marks": {"Q1": 1}}])
    assert r.status_code == 409
    assert db.execute("SELECT count(*) FROM audit_outbox WHERE op = 'DENIED'").fetchone()[0] == 1


def test_marks_are_typed_for_el_only_and_csv_upload_is_gone(client, db):
    h = login(client, "fac_a")
    row = [{"usn": "1RV25WX001", "marks": {"Q1": 9}}]
    r = client.put("/api/assessments/1/marks", headers=h, json=row)            # the seed's SEE
    assert r.status_code == 422 and "scanned answer sheets" in r.json()["detail"]
    assert client.put("/api/assessments/2/marks", headers=login(client, "coord"), json=row).status_code == 403
    assert client.put("/api/assessments/2/marks", headers=login(client, "fac_b"), json=row).status_code == 404
    assert client.post("/api/assessments/2/marks", headers=h,
                       files={"file": ("m.csv", "usn,Q1\n1RV25WX001,2\n")}).status_code == 405
    assert client.get("/api/assessments/2/template", headers=h).status_code == 404


def test_unlock_needs_hod_approval(client):
    fac, hod = login(client, "fac_a"), login(client, "hod")
    assert client.post("/api/assessments/1/unlock", headers=fac).status_code == 409
    rid = client.post("/api/assessments/1/unlock-requests", headers=fac,
                      json={"reason": "Q2 marks were swapped for two students"}).json()["request_id"]
    assert client.post(f"/api/unlock-requests/{rid}/decision", headers=fac, json={"approve": True}).status_code == 403
    assert client.post(f"/api/unlock-requests/{rid}/decision", headers=hod, json={"approve": True}).status_code == 200
    assert client.post("/api/assessments/1/unlock", headers=fac).status_code == 200


def test_compute_refused_while_assessment_unlocked(client):
    r = client.post("/api/offerings/1/compute", headers=login(client, "fac_a"))
    assert r.status_code == 409 and r.json()["code"] == "CP012"


def test_whatif_endpoint(client, db):
    db.execute("DELETE FROM question_co_map WHERE question_id IN (21, 22)")
    db.execute("DELETE FROM assessment_question WHERE assessment_id = 2")
    db.execute("DELETE FROM assessment WHERE assessment_id = 2")
    h = login(client, "fac_a")
    client.post("/api/offerings/1/compute", headers=h)
    r = client.post("/api/offerings/1/whatif", headers=h, json={"name": "lower", "l3_pct": 60, "l2_pct": 50, "l1_pct": 40})
    po2 = next(p for p in r.json()["pos"] if p["code"] == "PO2")
    assert po2["change"] == "now meets"


def test_student_scores_and_survey(client):
    h = login(client, "1rv25wx001")
    scores = client.get("/api/me/scores", headers=h).json()
    assert {s["co_number"] for s in scores} == {1, 2, 3}
    assert client.get("/api/offerings", headers=h).status_code == 403
    surveys = client.get("/api/me/surveys", headers=h).json()
    assert surveys == []        # the EL of offering 1 is still unlocked


def drop_quiz(db):
    db.execute("DELETE FROM question_co_map WHERE question_id IN (21, 22); "
               "DELETE FROM assessment_question WHERE assessment_id = 2; DELETE FROM assessment WHERE assessment_id = 2")


def test_student_submits_a_survey(client, db):
    drop_quiz(db)                                      # offering 1 is now finished
    h = login(client, "1rv25wx001")
    body = {"offering_id": 1, "answers": [{"co_id": c, "rating": 4} for c in (1, 2, 3)]}
    assert client.post("/api/me/surveys", headers=h, json=body).status_code == 201
    assert client.get("/api/me/surveys", headers=h).json()[0]["answered"] is True
    assert client.post("/api/me/surveys", headers=h, json=body).status_code == 422          # only once
    partial = {"offering_id": 1, "answers": [{"co_id": 1, "rating": 4}]}
    assert client.post("/api/me/surveys", headers=login(client, "fac_a"), json=partial).status_code == 403


def test_audit_verify_endpoint_after_an_anchor(client, db, mongo):
    from api.jobs import audit
    audit.drain_outbox(db, mongo)
    audit.anchor(db, mongo)
    r = client.get("/api/audit/verify", headers=login(client, "hod"))
    assert r.status_code == 200 and r.json()["ok"] is True, r.text


def test_nan_marks_are_a_row_error(client, db):
    h = login(client, "fac_a")
    r = client.put("/api/assessments/2/marks", headers=h,
                   json=[{"usn": "1RV25WX001", "marks": {"Q1": "nan", "Q2": "Infinity"}}])
    assert r.status_code == 422
    assert {e["column"] for e in r.json()["errors"]} == {"Q1", "Q2"}


def test_faculty_see_the_same_programme_figures_as_the_hod(client, db):
    drop_quiz(db)
    db.execute("CALL sp_compute_attainment(1)")
    hod, fac_b = login(client, "hod"), login(client, "fac_b")       # fac_b teaches nothing here
    for path in ("/api/analytics/program-po", "/api/academic-years", "/api/analytics/weakest?academic_year=2025-26"):
        a, b = client.get(path, headers=hod).json(), client.get(path, headers=fac_b).json()
        assert a == b and a, path
    assert client.get("/api/analytics/program-po", headers=login(client, "1rv25wx001")).status_code == 403


@pytest.fixture
def built_app(tmp_path, monkeypatch):
    """The app with a fake web/dist next to a secret file, as on a machine with .env beside it."""
    import importlib
    from api import config
    from api import main as main_module
    root = tmp_path / "repo"
    (root / "web" / "dist" / "assets").mkdir(parents=True)
    (root / "web" / "dist" / "index.html").write_text("<html>app</html>")
    (root / ".env").write_text("JWT_SECRET=do-not-serve")
    monkeypatch.setattr(config, "ROOT", root)
    app = importlib.reload(main_module).app
    yield TestClient(app)
    monkeypatch.undo()
    importlib.reload(main_module)


def test_spa_fallback_never_serves_files_outside_dist(built_app):
    for path in ("/..%2F..%2F.env", "/..%2F.env", "/%2E%2E/%2E%2E/.env", "/C:%2FWindows%2Fwin.ini"):
        r = built_app.get(path)
        assert "do-not-serve" not in r.text and "[fonts]" not in r.text, path
    assert built_app.get("/offerings/1").text == "<html>app</html>"
    assert built_app.get("/api/no-such-endpoint").status_code == 404     # not the app's page
