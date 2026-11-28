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
    Q4 Compare B+ tree and hash indexes 15 CO4 1
    Q5 Define a candidate key 2 cot L1"""
    r = paper.parse(text)
    assert r["paper_max"] == 50
    assert [(q["q_no"], q["max_marks"], q["cos"], q["bloom"]) for q in r["questions"]] == [
        ("Q1", 10, [1], 2), ("Q2", 15, [2], 3), ("Q3", 10, [2, 3], 3), ("Q4", 15, [4], 1), ("Q5", 2, [1], 1)]
    assert r["warnings"] == []


def test_bloom_field_read_as_lt_is_level_one():
    # Read on its own, a Bloom field Tesseract garbled as "14" in the full line comes back as "Lt".
    q = paper.parse("Q8 Write SQL for the given queries 10 CO5 Lt")["questions"][0]
    assert (q["q_no"], q["max_marks"], q["cos"], q["bloom"]) == ("Q8", 10, [5], 1)
    assert paper.BLOOM_WORD.match("Lt") and paper.BLOOM_WORD.match("L4") and not paper.BLOOM_WORD.match("14")


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
    # A stray mark that turns Q10 into Q1i0 (110, beyond the cover page) gives back the expected Q10;
    # a plausible number is kept as read.
    lines = "\n".join(f"Q{i} Explain {i} 5 CO1 L2" for i in range(1, 10))
    r = paper.parse(lines + "\nQ1i0 Compare indexes 5 CO4 L2\nQ12 Trace the log 5 CO2 L3")
    assert [q["q_no"] for q in r["questions"]][-2:] == ["Q10", "Q12"]


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
            (2, 'fac_b', %(pw)s, 'faculty', 2, NULL),
            (3, 'coord', %(pw)s, 'coordinator', NULL, NULL)""", {"pw": pw})
    db.execute("INSERT INTO assessment (assessment_id, offering_id, type, name, max_marks) "
               "VALUES (3, 1, 'CIE_THEORY', 'Test 1', 30)")
    db.execute("SELECT setval('assessment_assessment_id_seq', 10)")
    app.state.dbname = conftest.TEST_DB
    app.state.mongo_name = conftest.TEST_DB
    with TestClient(app) as c:
        yield c
    api_db.close_pools()


def login(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['token']}"}


PAPER = [("Q1", 2, [1], 1, "A"), ("Q2", 2, [2], 2, "A"), ("Q3", 2, [3], 1, "A"),
         ("Q4", 10, [1], 2, "B"), ("Q5", 10, [2], 3, "B"), ("Q6", 10, [2, 3], 4, "B")]


@pytest.fixture(scope="module")
def scanned(tmp_path_factory):
    """A CIE 1 paper (Part A quiz Q1-Q3, Part B test Q4-Q6) and 15 cover pages for the
    worked-example course (60 enrolled, so 45 have no sheet)."""
    from datagen.ocr_samples import STEMS, Paper, Question, build_pdf, random_key
    p = Paper("WX101", "Worked Example", "CIE 1", 36,
              [Question(q, m, cos, bl, STEMS[i], part) for i, (q, m, cos, bl, part) in enumerate(PAPER)])
    usns = [f"1RV25WX{i:03d}" for i in range(1, 16)]
    key = random_key(p, usns, np.random.default_rng(11), absent_share=0)
    out = build_pdf(key, tmp_path_factory.mktemp("ocr") / "cie1.pdf", seed=11)
    return out.read_bytes(), key


def scan(client, h, data, sitting="CIE1", offering=1):
    return client.post(f"/api/offerings/{offering}/scan?sitting={sitting}", headers=h,
                       files={"file": ("s.pdf", data, "application/pdf")})


def confirm_body(body, sitting="CIE1", **extra):
    """What the review screen sends after the teacher confirms everything as read."""
    return {"sitting": sitting,
            "questions": [{k: q[k] for k in ("q_no", "max_marks", "cos", "bloom", "part")} for q in body["paper"]["questions"]],
            "sheets": [{"page": s["page"], "usn": s["usn"], "marks": {m["q_no"]: m["value"] for m in s["marks"]}}
                       for s in body["sheets"]], **extra}


@needs_ocr
def test_combined_paper_is_read_into_parts_usns_and_marks(client, scanned):
    data, key = scanned
    r = scan(client, login(client, "fac_a"), data)
    assert r.status_code == 200, r.text
    body = r.json()
    qs = body["paper"]["questions"]
    assert [(q["q_no"], q["max_marks"], q["cos"], q["bloom"], q["part"]) for q in qs] == PAPER
    assert [q["number"] for q in qs] == ["Q1", "Q2", "Q3", "Q1", "Q2", "Q3"]     # renumbered per assessment
    assert [(p["part"], p["name"], p["type"], p["create"]) for p in body["parts"]] == [
        ("A", "Quiz 1", "CIE_QUIZ", True), ("B", "CIE Test 1", "CIE_THEORY", True)]
    assert any("'Quiz 1' is not in this offering yet" in w for w in body["paper"]["warnings"])
    assert len(body["sheets"]) == 15 and len(body["absent"]) == 45
    usn_right = 0
    for sheet, truth in zip(body["sheets"], key.sheets):
        usn_right += sheet["usn"] == truth.usn
        assert sheet["usn"] == truth.usn or sheet["check"], f"page {sheet['page']}: wrong USN not flagged"
        assert [m["q_no"] for m in sheet["marks"]] == [q[0] for q in PAPER]       # both parts on one sheet
        for m in sheet["marks"]:
            right = m["value"] == truth.marks[m["q_no"]]
            assert right or m["check"] or sheet["check"], f"page {sheet['page']} {m['q_no']}: wrong mark not flagged"
    assert usn_right >= 14


@needs_ocr
def test_confirmed_scan_creates_quiz_and_test_and_saves_every_mark(client, db, scanned):
    data, _ = scanned
    h = login(client, "fac_a")
    body = scan(client, h, data).json()
    r = client.post("/api/offerings/1/scan/confirm", headers=h, json=confirm_body(body))
    assert r.status_code == 200, r.text
    assert [(a["name"], a["created"], a["questions"], a["marks_saved"]) for a in r.json()["assessments"]] == [
        ("Quiz 1", True, 3, 180), ("CIE Test 1", True, 3, 180)]      # 15 sheets + 45 absent, 3 questions each
    rows = db.execute("""
        SELECT a.name, a.type::text, a.max_marks::int, q.q_no, q.max_marks::int, q.bloom_level,
               array_agg(co.co_number ORDER BY co.co_number), sum(m.weight)
        FROM assessment a JOIN assessment_question q USING (assessment_id)
        JOIN question_co_map m USING (question_id) JOIN course_outcome co USING (co_id)
        WHERE a.offering_id = 1 AND a.name IN ('Quiz 1', 'CIE Test 1')
        GROUP BY a.assessment_id, q.question_id ORDER BY a.name DESC, q.q_no""").fetchall()
    assert rows == [("Quiz 1", "CIE_QUIZ", 6, "Q1", 2, 1, [1], 1), ("Quiz 1", "CIE_QUIZ", 6, "Q2", 2, 2, [2], 1),
                    ("Quiz 1", "CIE_QUIZ", 6, "Q3", 2, 1, [3], 1),
                    ("CIE Test 1", "CIE_THEORY", 30, "Q1", 10, 2, [1], 1),
                    ("CIE Test 1", "CIE_THEORY", 30, "Q2", 10, 3, [2], 1),
                    ("CIE Test 1", "CIE_THEORY", 30, "Q3", 10, 4, [2, 3], 1)]
    # The paper's Q6 is the test's Q3: the mark written in row Q6 lands there.
    first = body["sheets"][0]
    q6 = db.execute("""
        SELECT m.marks_obtained::int FROM student_question_mark m JOIN enrollment e USING (enrollment_id)
        JOIN assessment_question q USING (question_id) JOIN assessment a USING (assessment_id)
        WHERE e.usn = %s AND a.name = 'CIE Test 1' AND q.q_no = 'Q3'""", (first["usn"],)).fetchone()[0]
    assert q6 == first["marks"][5]["value"]
    # Saving only: locking stays a separate step, and both can now be locked.
    assert db.execute("SELECT count(*) FROM assessment WHERE locked").fetchone()[0] == 1     # the seed's SEE
    for a in r.json()["assessments"]:
        assert client.post(f"/api/assessments/{a['assessment_id']}/lock", headers=h).status_code == 200


def test_confirm_with_row_errors_saves_nothing_and_creates_nothing(client, db):
    h = login(client, "fac_a")
    body = {"sitting": "CIE1",
            "questions": [{"q_no": "Q1", "max_marks": 2, "cos": [1], "bloom": 1, "part": "A"},
                          {"q_no": "Q2", "max_marks": 10, "cos": [2], "bloom": 2, "part": "B"}],
            "sheets": [{"page": 2, "usn": "1RV25WX001", "marks": {"Q1": 3, "Q2": 7}},
                       {"page": 3, "usn": "NOSUCH", "marks": {"Q1": 1, "Q2": 1}},
                       {"page": 4, "usn": "1RV25WX002", "marks": {"Q1": 1}}]}
    r = client.post("/api/offerings/1/scan/confirm", headers=h, json=body)
    assert r.status_code == 422
    assert {(e["row"], e["usn"], e["column"]) for e in r.json()["errors"]} == {
        (2, "1RV25WX001", "Q1"), (3, "NOSUCH", "usn"), (4, "1RV25WX002", "Q2")}     # columns use the paper's numbers
    assert db.execute("SELECT count(*) FROM assessment WHERE name IN ('Quiz 1', 'CIE Test 1')").fetchone()[0] == 0


def fake_raw(n_paper_questions=3, rows=None, aligned=True, part=lambda i: "A" if i <= 5 else "B"):
    """What reader.read_pdf returns, without a PDF: every mark row reads as `rows[i]` (units digit)."""
    rows = rows or [1, 2, 3, 4, 5, 6, 7, 8, 9, 0] * 2
    sheet = {"page": 2, "aligned": aligned, "image": "x"}
    if aligned:
        sheet |= {"usn": {"probas": [onehot(2), onehot(5), onehot(0), onehot(0), onehot(1)], "image": "u"},
                  "marks": {i: {"probas": [None, onehot(v)], "image": f"r{i}"} for i, v in enumerate(rows)},
                  "total": {"probas": [None, None, None], "image": "t"}}
    qs = [{"q_no": f"Q{i}", "text": "", "max_marks": 9, "cos": [1], "bloom": 2, "part": part(i)}
          for i in range(1, n_paper_questions + 1)]
    return {"paper": {"questions": qs, "paper_max": None, "warnings": []}, "sheets": [sheet]}


def test_scan_fills_existing_assessments_and_keeps_marks_of_students_without_a_sheet(client, db, monkeypatch):
    from api.routers import ocr as ocr_router
    monkeypatch.setattr(ocr_router.reader, "read_pdf", lambda data, fallback=None: fake_raw(7))
    # 'CIE Test 1' exists with the paper's Part B (Q6, Q7 -> its Q1, Q2) and a mark for 1RV25WX050.
    db.execute("""
        INSERT INTO assessment (assessment_id, offering_id, type, name, max_marks) VALUES (4, 1, 'CIE_THEORY', 'CIE Test 1', 18);
        INSERT INTO assessment_question (question_id, assessment_id, q_no, max_marks, bloom_level) VALUES
            (41, 4, 'Q1', 9, 2), (42, 4, 'Q2', 9, 2);
        INSERT INTO question_co_map VALUES (41, 1, 1), (42, 1, 1);
        INSERT INTO student_question_mark VALUES (50, 41, 4, false), (50, 42, 5, false)""")
    h = login(client, "fac_a")
    body = scan(client, h, b"%PDF").json()
    test = body["parts"][1]
    assert (test["name"], test["create"], test["same_as_saved"], test["absent_with_marks"]) == (
        "CIE Test 1", False, True, ["1RV25WX050"])
    assert body["parts"][0]["create"] is True and body["parts"][0]["absent_with_marks"] == []
    r = client.post("/api/offerings/1/scan/confirm", headers=h, json=confirm_body(body))
    assert r.status_code == 200, r.text
    assert [(a["name"], a["created"], a["questions_saved"]) for a in r.json()["assessments"]] == [
        ("Quiz 1", True, True), ("CIE Test 1", False, False)]
    marks = dict(db.execute("""
        SELECT e.usn || ' ' || q.q_no, coalesce(m.marks_obtained::int::text, 'AB')
        FROM student_question_mark m JOIN enrollment e USING (enrollment_id) JOIN assessment_question q USING (question_id)
        WHERE q.assessment_id = 4 AND e.usn IN ('1RV25WX001', '1RV25WX002', '1RV25WX050')""").fetchall())
    assert marks == {"1RV25WX001 Q1": "6", "1RV25WX001 Q2": "7",         # rows Q6 and Q7 of the sheet
                     "1RV25WX002 Q1": "AB", "1RV25WX002 Q2": "AB",       # no sheet, no marks yet: absent
                     "1RV25WX050 Q1": "4", "1RV25WX050 Q2": "5"}         # no sheet but marked earlier: kept
    # The teacher can opt in to marking them absent too.
    r = client.post("/api/offerings/1/scan/confirm", headers=h, json=confirm_body(body, overwrite_absent=True))
    assert r.status_code == 200
    assert db.execute("SELECT count(*) FROM student_question_mark WHERE enrollment_id = 50 AND question_id IN (41, 42) "
                      "AND is_absent").fetchone()[0] == 2


def test_scan_refuses_locked_assessments_other_faculty_the_coordinator_and_non_pdfs(client, db):
    h = login(client, "fac_a")
    r = scan(client, h, b"not a pdf")
    assert r.status_code == 422 and "not a readable PDF" in r.json()["detail"]
    r = scan(client, h, b"%PDF", sitting="SEE")                          # the seed's SEE is locked
    assert r.status_code == 409 and "SEE is locked" in r.json()["detail"]
    see = {"sitting": "SEE", "questions": [{"q_no": "Q1", "max_marks": 10, "cos": [1], "bloom": 2, "part": "B"}],
           "sheets": [{"page": 2, "usn": "1RV25WX001", "marks": {"Q1": 5}}]}
    assert client.post("/api/offerings/1/scan/confirm", headers=h, json=see).status_code == 409
    assert db.execute("SELECT count(*) FROM audit_outbox WHERE op = 'DENIED'").fetchone()[0] == 1
    assert scan(client, h, b"%PDF", sitting="CIE3").status_code == 422
    assert scan(client, login(client, "fac_b"), b"%PDF").status_code == 404
    assert scan(client, login(client, "coord"), b"%PDF").status_code == 403
    body = {**see, "sitting": "CIE1"}
    assert client.post("/api/offerings/1/scan/confirm", headers=login(client, "coord"), json=body).status_code == 403
    assert client.post("/api/offerings/1/scan/confirm", headers=login(client, "fac_b"), json=body).status_code == 404
    # The old per-assessment reader is gone.
    assert client.post("/api/assessments/3/ocr", headers=h, files={"file": ("x.pdf", b"%PDF")}).status_code in (404, 405)


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
    thirds = {"questions": [{"q_no": "Q1", "max_marks": 20, "cos": [1, 2, 3], "bloom": 2}]}
    assert client.put("/api/assessments/3/questions", headers=h, json=thirds).status_code == 200
    # With no marks yet, the assessment's maximum follows its questions.
    assert db.execute("SELECT max_marks::int FROM assessment WHERE assessment_id = 3").fetchone()[0] == 20
    assert client.put("/api/assessments/3/questions", headers=login(client, "fac_b"), json=thirds).status_code == 404
    db.execute("UPDATE assessment SET locked = true WHERE assessment_id = 1")        # the seed's SEE
    assert client.put("/api/assessments/1/questions", headers=h, json=thirds).status_code == 409


def test_el_assessment_is_created_with_its_questions_and_marks_are_typed(client, db):
    h = login(client, "fac_a")
    el = {"name": "Experiential Learning", "questions": [{"q_no": "Q1", "max_marks": 20, "cos": [1, 2], "bloom": 3},
                                                         {"q_no": "Q2", "max_marks": 20, "cos": [3], "bloom": 4}]}
    assert client.post("/api/offerings/1/assessments", headers=login(client, "coord"), json=el).status_code == 403
    assert client.post("/api/offerings/1/assessments", headers=login(client, "fac_b"), json=el).status_code == 404
    assert client.post("/api/offerings/1/assessments", headers=h, json={**el, "type": "SEE"}).status_code == 422
    r = client.post("/api/offerings/1/assessments", headers=h, json=el)
    assert r.status_code == 201, r.text
    aid = r.json()["assessment_id"]
    assert db.execute("SELECT type::text, max_marks::int FROM assessment WHERE assessment_id = %s", (aid,)).fetchone() == ("EL", 40)
    r = client.put(f"/api/assessments/{aid}/marks", headers=h,
                   json=[{"usn": "1RV25WX001", "marks": {"Q1": 18, "Q2": "AB"}}])
    assert r.json() == {"saved": 2}
    sheet = client.get(f"/api/assessments/{aid}/marks", headers=h).json()
    assert sheet["students"][0] == {"usn": "1RV25WX001", "name": "Student 1", "marks": {"Q1": 18, "Q2": "AB"}}
    assert sheet["students"][1]["marks"] == {"Q1": None, "Q2": None}


# ---------------------------------------------------------------- review fixes (PR #12)

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


def test_questions_beyond_the_cover_page_and_missing_headings_are_reported(client, db, monkeypatch):
    from api.routers import ocr as ocr_router
    monkeypatch.setattr(ocr_router.reader, "read_pdf", lambda data, fallback=None: fake_raw(22, part=lambda i: None))
    db.execute("UPDATE attainment_config SET ocr_review_confidence = 0.55")
    body = scan(client, login(client, "fac_a"), b"%PDF").json()
    assert [q["q_no"] for q in body["paper"]["questions"]] == [f"Q{i}" for i in range(1, 21)]
    assert any("Q21, Q22" in w for w in body["paper"]["warnings"])
    assert any("No 'Part A - Quiz' or 'Part B - Test' heading" in w for w in body["paper"]["warnings"])
    assert all("choose its part" in q["problems"][-1] for q in body["paper"]["questions"])
    assert body["threshold"] == 0.55                                   # from the rule version, not .env
