"""Course-exit surveys as Google Forms (phase 8, FR-5.1, FR-5.3 to FR-5.5, NFR-9).

Google is replaced by an httpx.MockTransport, so these tests never reach the network. The worked
example's offering 1 (60 students, CO1-CO3, its only assessment locked) is the surveyed offering.
"""

import base64
import json
from urllib.parse import parse_qs, urlparse

import bcrypt
import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from api import db as api_db
from api.google import client as google
from api.main import app
from api.routers.survey_forms import _safe_path, sync_all
from tests import conftest

PASSWORD = "test-password"


class FakeGoogle:
    """Just enough of Google's OAuth and Forms API, recording what was asked."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.batch: list[dict] = []
        self.responses: list[dict] = []
        self.deleted: list[str] = []
        self.fail_batch = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append((request.method, url.split("?")[0]))
        if url.startswith(google.TOKEN_URL):
            payload = base64.urlsafe_b64encode(json.dumps({"email": "teacher@gmail.com"}).encode()).decode().rstrip("=")
            return httpx.Response(200, json={"access_token": "access-1", "refresh_token": "refresh-secret",
                                             "id_token": f"h.{payload}.s"})
        if url.startswith(google.REVOKE_URL):
            return httpx.Response(200)
        if request.method == "DELETE" and url.startswith(google.DRIVE_FILES_URL):
            self.deleted.append(url.rsplit("/", 1)[1])
            return httpx.Response(204)
        if request.method == "POST" and url.endswith("/v1/forms"):
            return httpx.Response(200, json={"formId": "F1", "responderUri": "https://docs.google.com/forms/d/e/F1/viewform"})
        if url.endswith(":batchUpdate"):
            if self.fail_batch:
                return httpx.Response(500, json={"error": {"message": "backend error"}})
            reqs = json.loads(request.content)["requests"]
            self.batch = reqs
            return httpx.Response(200, json={"replies": [
                {"createItem": {"itemId": f"i{n}", "questionId": [f"q{n}"]}} if "createItem" in r else {}
                for n, r in enumerate(reqs)]})
        if url.endswith(":setPublishSettings"):
            return httpx.Response(200, json={})
        if "/responses" in url:
            return httpx.Response(200, json={"responses": self.responses})
        return httpx.Response(404, json={"error": {"message": "not faked"}})


def answer(email, usn, ratings, name="A Student", phone="9999999999"):
    # Question ids follow the fake batchUpdate: q2 usn, q3 name, q4 phone, q5.. COs (requests 0 and 1
    # are the description and settings updates). The email is Google's verified respondent email.
    values = {"q2": usn, "q3": name, "q4": phone}
    values.update({f"q{5 + i}": str(r) for i, r in enumerate(ratings) if r is not None})
    out = {"answers": {k: {"questionId": k, "textAnswers": {"answers": [{"value": v}]}} for k, v in values.items()}}
    if email:
        out["respondentEmail"] = email
    return out


def mail(usn):
    return f"{usn.lower()}@rvce.edu.in"


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-1")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-1")
    monkeypatch.setenv("GOOGLE_TOKEN_KEY", Fernet.generate_key().decode())
    g = FakeGoogle()
    monkeypatch.setattr(google, "transport", httpx.MockTransport(g))
    return g


@pytest.fixture
def client(db, mongo):
    pw = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(4)).decode()
    db.execute("INSERT INTO faculty VALUES (2, 1, 'Faculty B', 'b@example.edu')")
    db.execute("""
        INSERT INTO app_user (user_id, username, password_hash, role, faculty_id, usn) VALUES
            (1, 'fac_a', %(pw)s, 'faculty', 1, NULL),
            (2, 'fac_b', %(pw)s, 'faculty', 2, NULL),
            (3, 'hod', %(pw)s, 'admin', NULL, NULL),
            (4, 'coord', %(pw)s, 'coordinator', NULL, NULL)""", {"pw": pw})
    db.execute("UPDATE student SET email = lower(usn) || '@rvce.edu.in'")         # the college emails on record
    app.state.dbname = conftest.TEST_DB
    app.state.mongo_name = conftest.TEST_DB
    with TestClient(app) as c:
        yield c
    api_db.close_pools()


def login(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def connect_google(client, h, return_to="/offerings/1"):
    url = client.get("/api/google/connect", params={"return_to": return_to}, headers=h).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    return client.get("/api/google/callback", params={"state": state, "code": "code-1"}, follow_redirects=False), url


def test_google_must_be_set_up_before_connecting(client, monkeypatch):
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_TOKEN_KEY"):
        monkeypatch.setenv(name, "")
    h = login(client, "fac_a")
    assert client.get("/api/google/status", headers=h).json() == {"configured": False, "connected": False, "email": None}
    r = client.get("/api/google/connect", headers=h)
    assert r.status_code == 409 and "GOOGLE_CLIENT_ID" in r.json()["detail"]


def test_connecting_stores_only_an_encrypted_token_seen_by_its_owner(client, db, fake):
    h = login(client, "fac_a")
    r, url = connect_google(client, h)
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["client-1"] and q["access_type"] == ["offline"]
    assert "forms.body" in q["scope"][0] and "forms.responses.readonly" in q["scope"][0]
    assert r.status_code == 303 and r.headers["location"] == "/offerings/1?google=connected"
    stored = db.execute("SELECT google_email, refresh_token_enc FROM google_account WHERE user_id = 1").fetchone()
    assert stored[0] == "teacher@gmail.com" and "refresh-secret" not in stored[1]
    assert client.get("/api/google/status", headers=h).json()["connected"] is True
    # Another teacher and the HoD see no one else's Google connection.
    assert client.get("/api/google/status", headers=login(client, "fac_b")).json()["connected"] is False
    assert client.get("/api/google/status", headers=login(client, "hod")).json()["connected"] is False
    # Tokens never reach the audit chain.
    assert db.execute("SELECT count(*) FROM audit_outbox WHERE table_name = 'google_account'").fetchone()[0] == 0
    assert client.post("/api/google/disconnect", headers=h).json() == {"connected": False}
    assert db.execute("SELECT count(*) FROM google_account").fetchone()[0] == 0


def test_sign_in_state_cannot_be_used_as_a_login_or_to_leave_the_site(client, fake):
    h = login(client, "fac_a")
    url = client.get("/api/google/connect", params={"return_to": "//evil.example/x"}, headers=h).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    assert client.get("/api/offerings", headers={"Authorization": f"Bearer {state}"}).status_code == 401
    r = client.get("/api/google/callback", params={"state": state, "code": "c"}, follow_redirects=False)
    assert r.headers["location"] == "/?google=connected"
    assert _safe_path("https://evil.example") == "/" and _safe_path("/\\evil") == "/" and _safe_path("/ok?x=1") == "/ok?x=1"


def test_form_is_created_with_identity_fields_and_one_scale_per_co(client, db, fake):
    h = login(client, "fac_a")
    assert client.post("/api/offerings/1/survey-form", headers=h).status_code == 409    # not connected yet
    connect_google(client, h)
    r = client.post("/api/offerings/1/survey-form", headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["responder_uri"].endswith("/viewform")
    assert {"updateSettings": {"settings": {"emailCollectionType": "VERIFIED"},
                               "updateMask": "emailCollectionType"}} in fake.batch
    items = [x["createItem"]["item"] for x in fake.batch if "createItem" in x]
    assert [i["title"] for i in items[:3]] == ["USN", "Name", "Phone number"]
    scales = [i for i in items if "scaleQuestion" in i["questionItem"]["question"]]
    assert len(scales) == 3 and all(s["questionItem"]["question"]["scaleQuestion"]["high"] == 5 for s in scales)
    assert ("POST", "https://forms.googleapis.com/v1/forms/F1:setPublishSettings") in fake.calls
    ids = db.execute("SELECT question_ids FROM survey_form WHERE offering_id = 1").fetchone()[0]
    assert "email" not in ids and ids["usn"] == "q2" and ids["cos"] == {"1": "q5", "2": "q6", "3": "q7"}
    assert client.post("/api/offerings/1/survey-form", headers=h).status_code == 409    # one per offering
    assert client.post("/api/offerings/1/survey-form", headers=login(client, "fac_b")).status_code == 404


def test_responses_are_checked_stored_anonymously_and_counted(client, db, mongo, fake):
    h = login(client, "fac_a")
    connect_google(client, h)
    client.post("/api/offerings/1/survey-form", headers=h)
    db.execute("INSERT INTO student (usn, name, program_id, admission_year, section, email) "
               "VALUES ('1RV25WX099', 'Not enrolled', 1, 2025, 'A', '1rv25wx099@rvce.edu.in')")
    fake.responses = [
        answer(mail("1RV25WX001"), "1rv25wx001", [4, 5, 3]),       # accepted (USN case does not matter)
        answer(mail("1RV25WX001"), "1RV25WX001", [1, 1, 1]),       # same student again
        answer(mail("1RV25WX002"), "1RV25WX005", [1, 1, 1]),       # a classmate answering as someone else
        answer("b@gmail.com", "1RV25WX002", [5, 5, 5]),            # not a college email
        answer(None, "1RV25WX006", [5, 5, 5]),                     # no verified email collected
        answer("c@rvce.edu.in", "ABC", [5, 5, 5]),                 # USN format
        answer(mail("1RV25WX099"), "1RV25WX099", [5, 5, 5]),       # not enrolled
        answer(mail("1RV25WX003"), "1RV25WX003", [5, None, 5]),    # a CO left unrated
        answer(mail("1RV25WX004"), "1RV25WX004", [2, 4, 5]),       # accepted
    ]
    s = client.post("/api/offerings/1/survey-form/sync", headers=h).json()
    assert s["read"] == 9 and s["accepted"] == 2 and s["already"] == 1
    assert s["rejected"] == {"Email is not the one on record for this USN": 1, "Not a college email": 1,
                             "No verified email (form not collecting emails)": 1, "USN not in the right format": 1,
                             "USN not enrolled in this offering": 1, "Ratings incomplete or out of range": 1}
    docs = list(mongo.survey_responses.find({"offering_id": 1}, {"_id": 0}))
    assert len(docs) == 2
    for d in docs:                                     # no email, name, phone or plain USN kept
        assert set(d) == {"survey_type", "offering_id", "respondent_hash", "submitted_at", "answers"}
        assert "1RV25WX" not in json.dumps(d, default=str)
    again = client.post("/api/offerings/1/survey-form/sync", headers=h).json()
    assert again["accepted"] == 0 and again["already"] == 3
    dash = client.get("/api/offerings/1/survey-form", headers=h).json()
    d = dash["dashboard"]
    assert d["enrolled"] == 60 and d["responses"] == 2 and d["yet_to_respond"] == 58
    co1 = d["cos"][0]
    assert co1["counts"] == [0, 1, 0, 1, 0] and co1["favourable_pct"] == 50.0
    assert dash["form"]["mine"] is True and dash["form"]["last_sync"]["accepted"] == 0
    assert "refresh" not in json.dumps(dash)


def test_who_may_see_and_fetch(client, db, fake):
    h = login(client, "fac_a")
    connect_google(client, h)
    client.post("/api/offerings/1/survey-form", headers=h)
    assert client.get("/api/offerings/1/survey-form", headers=login(client, "fac_b")).status_code == 404
    coord = client.get("/api/offerings/1/survey-form", headers=login(client, "coord"))
    assert coord.status_code == 200 and coord.json()["form"]["mine"] is False
    assert client.post("/api/offerings/1/survey-form/sync", headers=login(client, "coord")).status_code == 403
    assert client.post("/api/offerings/1/survey-form/sync", headers=login(client, "hod")).status_code == 403


def test_nightly_job_fetches_with_the_owners_connection(client, db, mongo, fake):
    h = login(client, "fac_a")
    connect_google(client, h)
    client.post("/api/offerings/1/survey-form", headers=h)
    fake.responses = [answer(mail("1RV25WX010"), "1RV25WX010", [3, 3, 3])]
    import psycopg

    from api import config
    with psycopg.connect(config.owner_dsn(conftest.TEST_DB), autocommit=True) as pg:
        out = sync_all(pg, mongo)
    assert out == {"forms": 1, "accepted": 1, "skipped": []}
    client.post("/api/google/disconnect", headers=h)
    with psycopg.connect(config.owner_dsn(conftest.TEST_DB), autocommit=True) as pg:
        out = sync_all(pg, mongo)
    assert out["forms"] == 0 and out["skipped"][0]["reason"] == "owner not connected to Google"


def test_a_sign_in_link_finished_in_another_browser_is_refused(client, db, fake):
    """Review of #13: teacher A must not be able to get teacher B's Google account linked to A."""
    url = client.get("/api/google/connect", params={"return_to": "/offerings/1"},
                     headers=login(client, "fac_a")).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    with TestClient(app) as other_browser:                      # B's browser has no nonce cookie
        r = other_browser.get("/api/google/callback", params={"state": state, "code": "code-1"},
                              follow_redirects=False)
    assert r.status_code == 303 and "google_error" in r.headers["location"]
    assert db.execute("SELECT count(*) FROM google_account").fetchone()[0] == 0
    assert not any(u == google.TOKEN_URL for _, u in fake.calls)              # the code was never exchanged


def test_a_failed_creation_leaves_no_form_behind(client, db, fake):
    h = login(client, "fac_a")
    connect_google(client, h)
    fake.fail_batch = True
    r = client.post("/api/offerings/1/survey-form", headers=h)
    assert r.status_code == 502 and fake.deleted == ["F1"]
    assert db.execute("SELECT count(*) FROM survey_form").fetchone()[0] == 0
