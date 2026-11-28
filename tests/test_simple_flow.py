"""The simple flow (migration 013): three CIEs with each student's best two, experiential learning (EL)
as one final mark outside CO attainment, the final total, per-student root cause, the semester
filter and the screens that are hidden (not deleted).
"""

from decimal import Decimal as D

import bcrypt
import pytest
from fastapi.testclient import TestClient

from api import config
from api import db as api_db
from api.main import app
from datagen import scenario
from tests import conftest
from tests.conftest import raises_sqlstate

PASSWORD = "test-password"

# (quiz n, test n) marks out of (10, 10) per CIE, SEE marks out of 10 for CO1-CO3, EL out of 40.
# S1: CIE 3 is the weakest and is dropped. S2: CIE 1 and CIE 2 tie at 50 %, so the later one, CIE 2,
# is dropped. S3: only two CIEs so far, both kept; no SEE or EL yet.
STUDENTS = {
    "1RV25WX201": {"cie": {1: (8, 8), 2: (6, 6), 3: (4, 4)}, "see": (5, 5, 5), "el": 30},
    "1RV25WX202": {"cie": {1: (5, 5), 2: (5, 5), 3: (9, 9)}, "see": (6, 6, 6), "el": "AB"},
    "1RV25WX203": {"cie": {1: (7, 7), 2: (7, 7)}, "see": None, "el": None},
}


@pytest.fixture
def best2(db):
    """Offering 2 of the worked-example course: Quiz n and CIE Test n (one 10-mark question each,
    both on CO n) for n = 1-3, a SEE with one 10-mark question per CO, and an EL out of 40."""
    db.execute("INSERT INTO course_offering VALUES (2, 1, '2025-26', 'even', 1, 'B')")
    for n in (1, 2, 3):
        db.execute("INSERT INTO assessment (assessment_id, offering_id, type, name, max_marks, cie_no) VALUES "
                   "(%s, 2, 'CIE_QUIZ', %s, 10, %s), (%s, 2, 'CIE_THEORY', %s, 10, %s)",
                   (30 + n, f"Quiz {n}", n, 40 + n, f"CIE Test {n}", n))
        db.execute("INSERT INTO assessment_question VALUES (%s, %s, 'Q1', 10), (%s, %s, 'Q1', 10)",
                   (300 + n, 30 + n, 400 + n, 40 + n))
        db.execute("INSERT INTO question_co_map VALUES (%s, %s, 1), (%s, %s, 1)", (300 + n, n, 400 + n, n))
    db.execute("""
        INSERT INTO assessment (assessment_id, offering_id, type, name, max_marks) VALUES
            (50, 2, 'SEE', 'SEE', 30), (60, 2, 'EL', 'Experiential Learning', 40);
        INSERT INTO assessment_question VALUES (501, 50, 'Q1', 10), (502, 50, 'Q2', 10), (503, 50, 'Q3', 10),
                                               (601, 60, 'Q1', 40);
        INSERT INTO question_co_map VALUES (501, 1, 1), (502, 2, 1), (503, 3, 1);
    """)
    for i, (usn, s) in enumerate(STUDENTS.items(), start=1):
        eid = 200 + i
        db.execute("INSERT INTO student (usn, name, program_id, admission_year, section) VALUES (%s, %s, 1, 2025, 'B')",
                   (usn, usn))
        db.execute("INSERT INTO enrollment VALUES (%s, 2, %s)", (eid, usn))
        for n, (quiz, test) in s["cie"].items():
            db.execute("INSERT INTO student_question_mark VALUES (%s, %s, %s, false), (%s, %s, %s, false)",
                       (eid, 300 + n, quiz, eid, 400 + n, test))
        for co, mark in enumerate(s["see"] or (), start=1):
            db.execute("INSERT INTO student_question_mark VALUES (%s, %s, %s, false)", (eid, 500 + co, mark))
        if s["el"] is not None:
            absent = s["el"] == "AB"
            db.execute("INSERT INTO student_question_mark VALUES (%s, 601, %s, %s)",
                       (eid, None if absent else s["el"], absent))
    return db


def co_scores(db):
    return {(usn, co): round(pct, 2) for usn, co, pct in db.execute(
        "SELECT usn, co_id, pct FROM student_co_score WHERE offering_id = 2")}


def test_co_scores_leave_out_each_students_dropped_cie(best2):
    s = co_scores(best2)
    # S1 drops CIE 3: CO3 comes from the SEE alone; CO1 = (20 x 80 + 30 x 80 + 50 x 50) / 100
    assert s[("1RV25WX201", 1)] == D("65.00") and s[("1RV25WX201", 3)] == D("50.00")
    # S2: CIE 1 and CIE 2 tie at 50 %; the earlier is kept, so CO2 comes from the SEE alone
    assert s[("1RV25WX202", 1)] == D("55.00") and s[("1RV25WX202", 2)] == D("60.00")
    assert s[("1RV25WX202", 3)] == D("75.00")
    # S3 has two CIEs: both count; no SEE yet, so CO3 has no score
    assert s[("1RV25WX203", 1)] == D("70.00") and ("1RV25WX203", 3) not in s


def test_cie_ranking_and_kept_flags(best2):
    rows = best2.execute("SELECT usn, cie_no, round(pct, 1), place, kept FROM student_cie_result "
                         "WHERE offering_id = 2 ORDER BY usn, cie_no").fetchall()
    assert rows == [("1RV25WX201", 1, D("80.0"), 1, True), ("1RV25WX201", 2, D("60.0"), 2, True),
                    ("1RV25WX201", 3, D("40.0"), 3, False),
                    ("1RV25WX202", 1, D("50.0"), 2, True), ("1RV25WX202", 2, D("50.0"), 3, False),
                    ("1RV25WX202", 3, D("90.0"), 1, True),
                    ("1RV25WX203", 1, D("70.0"), 1, True), ("1RV25WX203", 2, D("70.0"), 2, True)]


def test_final_total_best_two_cies_el_and_see(best2):
    rows = {r[0]: r[1:] for r in best2.execute(
        "SELECT usn, dropped_cies, round(cie_pct, 1), total, out_of FROM student_final_marks WHERE offering_id = 2")}
    # avg(80, 60) x 30 + 30/40 x 20 + 15/30 x 50 = 21 + 15 + 25
    assert rows["1RV25WX201"] == ([3], D("70.0"), D("61.00"), D("100"))
    # avg(50, 90) x 30 + AB (0) x 20 + 18/30 x 50 = 21 + 0 + 30
    assert rows["1RV25WX202"] == ([2], D("70.0"), D("51.00"), D("100"))
    # partial while the term runs: CIEs only, out of 30
    assert rows["1RV25WX203"] == ([], D("70.0"), D("21.00"), D("30"))


def test_best_of_and_total_weights_come_from_the_rule_version(best2):
    best2.execute("UPDATE attainment_config SET cie_best_of = 3, total_cie_weight = 40, total_el_weight = 10 "
                  "WHERE config_id = 1")
    # S1 keeps CIE 3 now: CO3 = (20 x 40 + 30 x 40 + 50 x 50) / 100
    assert co_scores(best2)[("1RV25WX201", 3)] == D("45.00")
    total = best2.execute("SELECT total FROM student_final_marks WHERE usn = '1RV25WX201'").fetchone()[0]
    assert total == D("56.50")                           # 60 % x 40 + 30/40 x 10 + 50 % x 50
    with raises_sqlstate("23514"):                       # the final weights add up to 100
        best2.execute("UPDATE attainment_config SET total_see_weight = 60 WHERE config_id = 1")


def test_attainment_counts_only_kept_cies(best2):
    db = best2
    # complete S3 (CIE 3 absent, SEE, EL) so every assessment of offering 2 can be locked and computed
    db.execute("INSERT INTO student_question_mark VALUES (203, 303, NULL, true), (203, 403, NULL, true), "
               "(203, 501, 9, false), (203, 502, 9, false), (203, 503, 9, false), (203, 601, 20, false)")
    db.execute("UPDATE assessment SET locked = true WHERE offering_id = 2")      # EL locks without a CO tag
    db.execute("CALL sp_compute_attainment(2)")
    students = dict(db.execute("SELECT co_id, students FROM co_attainment WHERE offering_id = 2").fetchall())
    assert students == {1: 3, 2: 3, 3: 3}
    # S3 now has three CIEs and drops the absent CIE 3: CO3 = SEE alone = 90 %
    assert co_scores(db)[("1RV25WX203", 3)] == D("90.00")
    with raises_sqlstate("CP001"):                       # a locked assessment keeps its CIE number
        db.execute("UPDATE assessment SET cie_no = 2 WHERE assessment_id = 43")


def test_cie_number_belongs_to_quizzes_and_tests_once_each(best2):
    with raises_sqlstate("23514"):
        best2.execute("UPDATE assessment SET cie_no = 1 WHERE assessment_id = 50")       # the SEE
    with raises_sqlstate("23505"):
        best2.execute("INSERT INTO assessment (offering_id, type, name, max_marks, cie_no) "
                      "VALUES (2, 'CIE_QUIZ', 'Quiz 1b', 10, 1)")


def test_migration_fills_cie_numbers_of_existing_quizzes_and_tests():
    sql = (config.ROOT / "db" / "migrations" / "013_simple_flow.sql").read_text(encoding="utf-8")
    assert "name ~ '^Quiz [1-3]$'" in sql and "name ~ '^CIE Test [1-3]$'" in sql


# ---------------------------------------------------------------- per-student root cause (SQL)

def test_student_root_cause_lists_weak_prerequisites(empty_db, api_connect):
    scenario.build(empty_db)
    rows = empty_db.execute("SELECT usn, co_id, up_co_id, depth, up_pct, up_target_pct, up_below "
                            "FROM fn_student_root_cause(%s)", (scenario.DN_OFFERING,)).fetchall()
    weak = [r for r in rows if r[1] == scenario.WEAK]
    assert {(r[2], r[3]) for r in weak} == {(scenario.CAUSE, 1), (scenario.DECOY, 1), (scenario.DEEP, 2)}
    assert all(r[6] == (r[4] < r[5]) for r in weak)
    share = {up: sum(r[6] for r in weak if r[2] == up) / sum(1 for r in weak if r[2] == up)
             for up in (scenario.CAUSE, scenario.DECOY)}
    assert share[scenario.CAUSE] > share[scenario.DECOY]          # the planted cause shows per student too
    with raises_sqlstate("42501"):
        api_connect("faculty", faculty_id=2).execute("SELECT * FROM fn_student_root_cause(3)")


# ---------------------------------------------------------------- API

@pytest.fixture
def client(db, mongo):
    pw = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(4)).decode()
    db.execute("INSERT INTO faculty VALUES (2, 1, 'Faculty B', 'b@example.edu')")
    db.execute("""
        INSERT INTO app_user (user_id, username, password_hash, role, faculty_id, usn) VALUES
            (1, 'fac_a', %(pw)s, 'faculty', 1, NULL), (2, 'fac_b', %(pw)s, 'faculty', 2, NULL),
            (3, 'coord', %(pw)s, 'coordinator', NULL, NULL)""", {"pw": pw})
    app.state.dbname = conftest.TEST_DB
    app.state.mongo_name = conftest.TEST_DB
    with TestClient(app) as c:
        yield c
    api_db.close_pools()


def login(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_el_is_added_with_its_maximum_and_one_mark_per_student(client, db):
    h = login(client, "fac_a")
    el = {"max_marks": 40}
    assert client.post("/api/offerings/1/assessments", headers=login(client, "coord"), json=el).status_code == 403
    assert client.post("/api/offerings/1/assessments", headers=login(client, "fac_b"), json=el).status_code == 404
    assert client.post("/api/offerings/1/assessments", headers=h, json={**el, "type": "SEE"}).status_code == 422
    r = client.post("/api/offerings/1/assessments", headers=h, json=el)
    assert r.status_code == 201, r.text
    aid = r.json()["assessment_id"]
    assert client.post("/api/offerings/1/assessments", headers=h, json=el).status_code == 409      # one EL
    assert db.execute("SELECT a.type::text, a.max_marks::int, q.q_no, q.max_marks::int, "
                      "(SELECT count(*) FROM question_co_map m WHERE m.question_id = q.question_id) "
                      "FROM assessment a JOIN assessment_question q USING (assessment_id) "
                      "WHERE a.assessment_id = %s", (aid,)).fetchall() == [("EL", 40, "Q1", 40, 0)]
    rows = [{"usn": f"1RV25WX{i:03d}", "marks": {"Q1": "AB" if i == 2 else 35}} for i in range(1, 61)]
    assert client.put(f"/api/assessments/{aid}/marks", headers=h, json=rows).json() == {"saved": 60}
    assert client.post(f"/api/assessments/{aid}/lock", headers=h).status_code == 200   # no CO tag needed

    f = client.get("/api/offerings/1/final-marks", headers=h).json()
    assert f["best_of"] == 2 and f["weights"] == {"cie": 30, "el": 20, "see": 50}
    first, second = f["students"][0], f["students"][1]
    # student 1: SEE 8 + 7 + 6 = 21 of 30 -> 35, EL 35 of 40 -> 17.5; no CIE yet, so out of 70
    assert (first["usn"], first["total"], first["out_of"], first["dropped"]) == ("1RV25WX001", 52.5, 70, [])
    assert second["el"] == 0 and second["total"] == 35                     # AB counts as zero
    # CO attainment is unchanged by EL: the worked example still gives CO 3.00 / 2.20 / 0.40
    cos = client.post("/api/offerings/1/compute", headers=h).json()["cos"]
    assert [c["final_level"] for c in cos] == [3.0, 2.2, 0.4]


def test_offerings_filtered_by_semester(client):
    h = login(client, "fac_a")
    assert [o["offering_id"] for o in client.get("/api/offerings?semester=4", headers=h).json()] == [1]
    assert client.get("/api/offerings?semester=5", headers=h).json() == []
    assert client.get("/api/offerings?semester=9", headers=h).status_code == 422


def test_weak_students_endpoint(client):
    h = login(client, "fac_a")
    r = client.get("/api/offerings/1/weak-students", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target_pct"] == 60
    # students 49-60 miss all three COs (SEE 4, 3 and 5 of 10); they come first
    worst = body["students"][0]
    assert [c["co_number"] for c in worst["missed"]] == [1, 2, 3]
    assert [(q["q_no"], q["lost"]) for q in worst["questions"]] == [("Q2", 7), ("Q1", 6), ("Q3", 5)]
    assert all(c["prereqs"] == [] for c in worst["missed"])          # the course has no prerequisite
    assert len(body["students"]) == 60 - 27                         # below 60 % in at least CO3
    assert client.get("/api/offerings/1/weak-students", headers=login(client, "fac_b")).status_code == 404
    assert client.get("/api/offerings/1/weak-students", headers=login(client, "coord")).status_code == 200


# ---------------------------------------------------------------- hidden screens

def test_hidden_screens_are_not_in_the_navigation_but_their_code_stays():
    web = config.ROOT / "web" / "src"
    shell = (web / "components" / "Shell.tsx").read_text(encoding="utf-8")
    offering = (web / "pages" / "Offering.tsx").read_text(encoding="utf-8")
    settings = (web / "pages" / "Settings.tsx").read_text(encoding="utf-8")
    app_routes = (web / "App.tsx").read_text(encoding="utf-8")
    nav = shell[shell.index("const nav: Nav[]"):shell.index("const item")]
    assert "/trends" not in nav and "/actions" not in nav               # Trends, Improvement actions
    tabs = next(line for line in offering.splitlines() if line.startswith("const TABS"))
    assert "whatif" not in tabs                                         # What-if tab
    assert "<Versions" not in settings.split("export function Settings", 1)[1].split("\nfunction", 1)[0]
    # hidden, not deleted: the pages, routes and endpoints remain
    assert (web / "pages" / "Trends.tsx").exists() and (web / "pages" / "Actions.tsx").exists()
    assert (web / "pages" / "offering" / "WhatIfTab.tsx").exists() and "function Versions" in settings
    assert 'path="/trends"' in app_routes and 'path="/actions"' in app_routes
