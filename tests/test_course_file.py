"""Course-file report as a PDF (phase 10, FR-6.6): every number comes from the database.

The worked example (PRD Section 5) gives known results: CO 3.00 / 2.20 / 0.40, PO1 2.30, PO2 1.48.
"""

import bcrypt
import fitz
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


def pdf_text(content: bytes) -> str:
    return "\n".join(page.get_text() for page in fitz.open(stream=content, filetype="pdf"))


def test_course_file_needs_computed_results(client):
    r = client.get("/api/offerings/1/course-file.pdf", headers=login(client, "fac_a"))
    assert r.status_code == 409 and "Compute attainment first" in r.json()["detail"]


def test_every_number_in_the_course_file_matches_the_database(client, db):
    db.execute("CALL sp_compute_attainment(1)")
    r = client.get("/api/offerings/1/course-file.pdf", headers=login(client, "fac_a"))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert 'filename="' in r.headers["content-disposition"]
    text = pdf_text(r.content)
    lines = [ln.strip() for ln in text.splitlines()]
    # CO table rows: CO, statement..., attained %, direct, survey, final, target, met
    for co_number, final, direct, indirect, pct in db.execute("""
            SELECT co.co_number, ca.final_level, ca.direct_level, ca.indirect_level, ca.pct_attained
            FROM co_attainment ca JOIN course_outcome co USING (co_id) WHERE ca.offering_id = 1 ORDER BY 1""").fetchall():
        start = lines.index(f"CO{co_number}")
        row = lines[start:start + 12]
        assert f"{float(pct):.1f}%" in row and str(direct) in row and str(indirect) in row and f"{float(final):.2f}" in row
    for code, value in db.execute("""
            SELECT po.code, pa.attainment FROM po_attainment pa JOIN program_outcome po USING (po_id)
            WHERE pa.offering_id = 1""").fetchall():
        assert f"{float(value):.2f}" in lines[lines.index(code):lines.index(code) + 10]
    assert {"3.00", "2.20", "0.40", "2.30", "1.48"} <= set(lines)          # the worked example, PRD Section 5
    assert "CO3: final level 0.40 against a target of 2.00; 33 of 60 students scored below 60%." in " ".join(lines)
    assert "Rule version 1" in text and "CIE theory 20, CIE quiz 10, EL 20, SEE 50" in text
    assert "CO3 final level 0.40 is below the target 2.00" in " ".join(lines)          # the automatic action


def test_who_may_download(client, db):
    db.execute("CALL sp_compute_attainment(1)")
    assert client.get("/api/offerings/1/course-file.pdf", headers=login(client, "fac_b")).status_code == 404
    assert client.get("/api/offerings/1/course-file.pdf", headers=login(client, "coord")).status_code == 200
    assert client.get("/api/offerings/1/course-file.pdf").status_code == 401


def test_non_latin_text_is_drawn_not_garbled(client, db):
    """Review of #15: CO statements with symbols, curly quotes or Devanagari keep their characters."""
    db.execute("""UPDATE course_outcome SET statement = %s WHERE co_id = 1""",
               ("Score \u2265 60% on \u201cnormal forms\u201d \u2014 \u0938\u093e\u0930 \u20b9",))
    db.execute("CALL sp_compute_attainment(1)")
    text = pdf_text(client.get("/api/offerings/1/course-file.pdf", headers=login(client, "fac_a")).content)
    for ch in ("\u2265", "\u201c", "\u201d", "\u2014", "\u0938", "\u20b9"):
        assert ch in text, f"{ch!r} missing from the PDF text"
