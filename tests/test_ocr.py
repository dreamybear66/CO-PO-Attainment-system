"""Answer-sheet OCR (phase 7, FR-3.7 to FR-3.9, NFR-10).

The end-to-end tests read a synthetic scanned PDF (datagen/ocr_samples.py) and need Tesseract and
the trained digit model (python -m scripts.train_digits); they are skipped when either is missing.
"""

import io
import shutil
from pathlib import Path

import bcrypt
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api import config
from api import db as api_db
from api.main import app
from api.ocr import digits, paper
from tests import conftest

PASSWORD = "test-password"

needs_ocr = pytest.mark.skipif(
    not digits.MODEL_PATH.exists()
    or not (Path(config.tesseract_cmd()).exists() or shutil.which(config.tesseract_cmd())),
    reason="needs Tesseract and models/digits.joblib (python -m scripts.train_digits)")


# ---------------------------------------------------------------- reading the question paper

def test_question_lines_are_read_through_ocr_confusions():
    text = """RV College of Engineering, Bengaluru
    IS243 Database Management Systems
    CIE Test 1    Max. marks: 50
    Q.No Question Marks CO BL
    Qi Explain the three-schema architecture 10 coli L2
    Q2 Normalise the relation to BCNF 15 Cco2 L3
    Q3 Write SQL for the given queries 10 C02,CO03 L3
    Q4 Compare B+ tree and hash indexes 15 CO4 1"""
    r = paper.parse(text)
    assert r["paper_max"] == 50
    assert [(q["q_no"], q["max_marks"], q["cos"], q["bloom"]) for q in r["questions"]] == [
        ("Q1", 10, [1], 2), ("Q2", 15, [2], 3), ("Q3", 10, [2, 3], 3), ("Q4", 15, [4], 1)]
    assert r["warnings"] == []


def test_part_headings_tag_each_question_through_ocr_noise():
    text = """IS243 Database Management Systems
    CIE 1    Max. marks: 60
    PartA — Quiz
    Q1 Define a candidate key 2 CO1 L1
    Q2 Name two isolation levels 2 CO2 L1
    Part 8: Test
    Q3 Normalise the relation to BCNF 10 CO2 L3
    Q4 Write SQL for the given queries 10 CO3 L3"""
    r = paper.parse(text)
    assert [(q["q_no"], q["part"]) for q in r["questions"]] == [("Q1", "A"), ("Q2", "A"), ("Q3", "B"), ("Q4", "B")]
    assert r["paper_max"] == 60 and r["warnings"] == []
    for heading in ("Part A - Quiz", "Part A: Quiz", "PART - A", "part a quiz"):
        assert paper.parse(f"{heading}\nQ1 Define 2 CO1 L1")["questions"][0]["part"] == "A", heading
    # A paper with no headings (an SEE) leaves the part open.
    assert paper.parse("Q1 Explain 10 CO1 L2")["questions"][0]["part"] is None


def test_unreadable_question_line_is_reported_not_dropped():
    r = paper.parse("Q1 Explain 10 CO1 L2\nQ2 smudged line with no codes\nQ1 again 5 CO2 L1")
    assert [q["q_no"] for q in r["questions"]] == ["Q1"]
    assert any("Q2 smudged" in w for w in r["warnings"])
    assert any("more than once" in w for w in r["warnings"])


# ---------------------------------------------------------------- cover-page layout

def test_cover_page_has_twenty_rows_that_fit_on_a4_without_overlapping():
    from api.ocr import layout
    assert layout.MAX_QUESTIONS == 20
    rows = [layout.mark_boxes(i) for i in range(layout.MAX_QUESTIONS)]
    boxes = [*layout.USN_YEAR, *layout.USN_ROLL, *(b for r in rows for b in r), *layout.TOTAL]
    top = layout.FIDUCIALS["tl"][1] + layout.FIDUCIAL
    bottom = layout.FIDUCIALS["bl"][1]
    for b in boxes:                       # inside the corner squares, so alignment covers them
        assert layout.FIDUCIALS["tl"][0] + layout.FIDUCIAL < b.x and b.x + b.w < layout.FIDUCIALS["tr"][0]
        assert top < b.y and b.y + b.h < bottom
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y, (a, b)
    # Q1-Q10 down the left column, Q11-Q20 down the right; the total sits below both.
    assert rows[0][0].x == rows[9][0].x < rows[10][0].x == rows[19][0].x
    assert rows[0][0].y == rows[10][0].y and rows[9][0].y == rows[19][0].y
    assert layout.TOTAL[0].y > rows[9][0].y + layout.BOX_H
    assert layout.USN_YEAR[0].y + layout.BOX_H < rows[0][0].y


# ---------------------------------------------------------------- choosing values

def onehot(d, p=0.9):
    v = np.full(10, (1 - p) / 9)
    v[d] = p
    return v


def test_mark_is_chosen_within_the_question_maximum():
    # The units box looks most like 9 but a little like 4; the question is out of 5, so 4 wins.
    units = np.full(10, 0.01)
    units[9], units[4] = 0.6, 0.3
    assert digits.best_number([None, units], 5)[0] == 4
    assert digits.best_number([None, units], 10)[0] == 9


def test_blank_boxes_mean_nothing_written_and_a_blank_tens_box_means_one_digit():
    assert digits.best_number([None, None], 10) == (None, 1.0)
    value, confidence = digits.best_number([None, onehot(7)], 10)
    assert value == 7 and confidence > 0.85
    assert digits.best_number([onehot(1), onehot(0)], 15)[0] == 10


def test_usn_is_chosen_among_enrolled_students():
    # Boxes read 2,5 / 0,0,7 but the 7 is unsure between 7 and 1; only ...001 is enrolled.
    roll = np.full(10, 0.01)
    roll[7], roll[1] = 0.55, 0.4
    probas = [onehot(2), onehot(5), onehot(0), onehot(0), roll]
    i, conf = digits.best_of(probas, ["25001", "25010"])
    assert i == 0 and conf > 0.9


# ---------------------------------------------------------------- end to end through the API

@pytest.fixture
def client(db, mongo):
    pw = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(4)).decode()
    db.execute("INSERT INTO faculty VALUES (2, 1, 'Faculty B', 'b@example.edu')")
    db.execute("""
        INSERT INTO app_user (user_id, username, password_hash, role, faculty_id, usn) VALUES
            (1, 'fac_a', %(pw)s, 'faculty', 1, NULL),
            (2, 'fac_b', %(pw)s, 'faculty', 2, NULL)""", {"pw": pw})
    db.execute("INSERT INTO assessment (assessment_id, offering_id, type, name, max_marks) "
               "VALUES (3, 1, 'CIE_THEORY', 'Test 1', 30)")
    app.state.dbname = conftest.TEST_DB
    app.state.mongo_name = conftest.TEST_DB
    with TestClient(app) as c:
        yield c
    api_db.close_pools()


def login(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def scanned(tmp_path_factory):
    """15 cover pages for the worked-example course (60 enrolled, so 45 have no sheet)."""
    from datagen.ocr_samples import STEMS, Paper, Question, build_pdf, random_key
    p = Paper("WX101", "Worked Example", "Test 1", 30, [
        Question("Q1", 10, [1], 2, STEMS[0]), Question("Q2", 10, [2], 3, STEMS[1]),
        Question("Q3", 10, [2, 3], 4, STEMS[2])])
    usns = [f"1RV25WX{i:03d}" for i in range(1, 16)]
    key = random_key(p, usns, np.random.default_rng(11), absent_share=0)
    out = build_pdf(key, tmp_path_factory.mktemp("ocr") / "test1.pdf", seed=11)
    return out.read_bytes(), key


@needs_ocr
def test_pdf_is_read_into_questions_usns_and_marks(client, scanned):
    data, key = scanned
    h = login(client, "fac_a")
    r = client.post("/api/assessments/3/ocr", headers=h, files={"file": ("t.pdf", data, "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()
    qs = body["paper"]["questions"]
    assert [(q["q_no"], q["max_marks"], q["cos"], q["bloom"]) for q in qs] == [
        ("Q1", 10, [1], 2), ("Q2", 10, [2], 3), ("Q3", 10, [2, 3], 4)]
    assert body["paper"]["same_as_saved"] is False and body["paper"]["warnings"] == []
    assert len(body["sheets"]) == 15 and len(body["absent"]) == 45
    usn_right = 0
    for sheet, truth in zip(body["sheets"], key.sheets):
        usn_right += sheet["usn"] == truth.usn
        assert sheet["usn"] == truth.usn or sheet["check"], f"page {sheet['page']}: wrong USN not flagged"
        for m in sheet["marks"]:
            right = m["value"] == truth.marks[m["q_no"]]
            assert right or m["check"] or sheet["check"], f"page {sheet['page']} {m['q_no']}: wrong mark not flagged"
    assert usn_right >= 14


@needs_ocr
def test_confirmed_questions_and_marks_are_saved_through_the_usual_checks(client, db, scanned):
    data, key = scanned
    h = login(client, "fac_a")
    body = client.post("/api/assessments/3/ocr", headers=h, files={"file": ("t.pdf", data, "application/pdf")}).json()
    payload = {"questions": [{k: q[k] for k in ("q_no", "max_marks", "cos", "bloom")} for q in body["paper"]["questions"]]}
    assert client.put("/api/assessments/3/questions", headers=h, json=payload).json() == {"saved": 3}
    rows = db.execute("""
        SELECT q.q_no, q.bloom_level, array_agg(co.co_number ORDER BY co.co_number), sum(m.weight)
        FROM assessment_question q JOIN question_co_map m USING (question_id) JOIN course_outcome co USING (co_id)
        WHERE q.assessment_id = 3 GROUP BY q.question_id ORDER BY q.q_no""").fetchall()
    assert rows == [("Q1", 2, [1], 1), ("Q2", 3, [2], 1), ("Q3", 4, [2, 3], 1)]
    # The review screen sends the confirmed values as CSV to the existing marks endpoint.
    lines = ["usn,Q1,Q2,Q3"]
    for sheet in body["sheets"]:
        lines.append(",".join([sheet["usn"], *(str(m["value"]) for m in sheet["marks"])]))
    lines += [f"{u},AB,AB,AB" for u in body["absent"]]
    r = client.post("/api/assessments/3/marks", headers=h, files={"file": ("m.csv", "\n".join(lines))})
    assert r.json() == {"saved": 180}


def test_questions_can_only_be_retagged_once_marks_exist(client, db):
    h = login(client, "fac_a")
    first = {"questions": [{"q_no": "Q1", "max_marks": 30, "cos": [1], "bloom": 2}]}
    assert client.put("/api/assessments/3/questions", headers=h, json=first).status_code == 200
    db.execute("INSERT INTO student_question_mark SELECT 1, question_id, 5, false FROM assessment_question WHERE assessment_id = 3")
    retag = {"questions": [{"q_no": "Q1", "max_marks": 30, "cos": [1, 2], "bloom": 3}]}
    assert client.put("/api/assessments/3/questions", headers=h, json=retag).status_code == 200
    reshape = {"questions": [{"q_no": "Q1", "max_marks": 20, "cos": [1], "bloom": 3},
                             {"q_no": "Q2", "max_marks": 10, "cos": [2], "bloom": 3}]}
    r = client.put("/api/assessments/3/questions", headers=h, json=reshape)
    assert r.status_code == 409 and "only CO tags" in r.json()["detail"]
    weights = db.execute("SELECT array_agg(weight ORDER BY co_id) FROM question_co_map m "
                         "JOIN assessment_question q USING (question_id) WHERE q.assessment_id = 3").fetchone()[0]
    assert [float(w) for w in weights] == [0.5, 0.5]


def test_question_paper_rules(client, db):
    h = login(client, "fac_a")
    bad_co = {"questions": [{"q_no": "Q1", "max_marks": 30, "cos": [9], "bloom": 2}]}
    assert client.put("/api/assessments/3/questions", headers=h, json=bad_co).status_code == 422
    thirds = {"questions": [{"q_no": "Q1", "max_marks": 30, "cos": [1, 2, 3], "bloom": 2}]}
    assert client.put("/api/assessments/3/questions", headers=h, json=thirds).status_code == 200
    assert client.put("/api/assessments/3/questions", headers=login(client, "fac_b"), json=thirds).status_code == 404
    db.execute("UPDATE assessment SET locked = true WHERE assessment_id = 1")        # the seed's SEE
    assert client.put("/api/assessments/1/questions", headers=h, json=thirds).status_code == 409


def test_ocr_refuses_locked_assessments_and_non_pdfs(client, db):
    h = login(client, "fac_a")
    r = client.post("/api/assessments/3/ocr", headers=h, files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 422 and "not a readable PDF" in r.json()["detail"]
    db.execute("UPDATE assessment SET locked = true WHERE assessment_id = 1")
    r = client.post("/api/assessments/1/ocr", headers=h, files={"file": ("x.pdf", io.BytesIO(b"%PDF"), "application/pdf")})
    assert r.status_code == 409
    assert client.post("/api/assessments/3/ocr", headers=login(client, "fac_b"),
                       files={"file": ("x.pdf", b"x", "application/pdf")}).status_code == 404


# ---------------------------------------------------------------- review fixes (PR #12)

def fake_raw(n_paper_questions=3, rows=None, aligned=True):
    """What reader.read_pdf returns, without a PDF: every mark row reads as `rows[i]` (units digit)."""
    rows = rows or [1, 2, 3, 4, 5, 6, 7, 8, 9, 0] * 2
    sheet = {"page": 2, "aligned": aligned, "image": "x"}
    if aligned:
        sheet |= {"usn": {"probas": [onehot(2), onehot(5), onehot(0), onehot(0), onehot(1)], "image": "u"},
                  "marks": {i: {"probas": [None, onehot(v)], "image": f"r{i}"} for i, v in enumerate(rows)},
                  "total": {"probas": [None, None, None], "image": "t"}}
    qs = [{"q_no": f"Q{i}", "text": "", "max_marks": 9, "cos": [1], "bloom": 2} for i in range(1, n_paper_questions + 1)]
    return {"paper": {"questions": qs, "paper_max": None, "warnings": []}, "sheets": [sheet]}


def test_marks_follow_question_numbers_not_list_position():
    from api.ocr import reader
    # Page 1's Q3 line could not be read: Q4 must still come from the Q4 row, not the Q3 row.
    qs = [{"q_no": "Q1", "max_marks": 9}, {"q_no": "Q2", "max_marks": 9}, {"q_no": "Q4", "max_marks": 9}]
    r = reader.review(fake_raw(), qs, ["1RV25WX001"], 0.9)
    assert [(m["q_no"], m["value"]) for m in r["sheets"][0]["marks"]] == [("Q1", 1), ("Q2", 2), ("Q4", 4)]


def test_an_unreadable_page_gets_one_empty_input_per_question():
    from api.ocr import reader
    qs = [{"q_no": "Q1", "max_marks": 9}, {"q_no": "Q2", "max_marks": 9}]
    s = reader.review(fake_raw(aligned=False), qs, ["1RV25WX001"], 0.9)["sheets"][0]
    assert s["check"] and [(m["q_no"], m["value"], m["check"]) for m in s["marks"]] == [("Q1", None, True), ("Q2", None, True)]


def test_questions_beyond_the_cover_page_are_not_returned_and_existing_marks_are_reported(client, db, monkeypatch):
    from api.routers import ocr as ocr_router
    monkeypatch.setattr(ocr_router.reader, "read_pdf", lambda data, fallback=None: fake_raw(22))
    db.execute("UPDATE attainment_config SET ocr_review_confidence = 0.55")
    db.execute("INSERT INTO assessment_question (question_id, assessment_id, q_no, max_marks) VALUES (31, 3, 'Q1', 30)")
    db.execute("INSERT INTO question_co_map VALUES (31, 1, 1)")
    db.execute("INSERT INTO student_question_mark VALUES (50, 31, 12, false)")          # 1RV25WX050 already marked
    body = client.post("/api/assessments/3/ocr", headers=login(client, "fac_a"),
                       files={"file": ("t.pdf", b"%PDF", "application/pdf")}).json()
    assert [q["q_no"] for q in body["paper"]["questions"]] == [f"Q{i}" for i in range(1, 21)]
    assert any("Q21, Q22" in w for w in body["paper"]["warnings"])
    assert "1RV25WX050" in body["absent"] and body["absent_with_marks"] == ["1RV25WX050"]
    assert body["threshold"] == 0.55                                   # from the rule version, not .env
