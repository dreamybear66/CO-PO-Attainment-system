"""Synthetic data generator (Phase 2): determinism, size and the planted root-cause story.

Pure Python on the in-memory Builder; no database needed.
"""

import hashlib
from collections import defaultdict

import numpy as np
import pytest

from api.survey_hash import respondent_hash
from datagen import catalog as cat
from datagen.generate import Builder

SEED = 2026
KEY = b"test-key"


def build(seed: int = SEED) -> tuple[Builder, dict]:
    b = Builder(seed, KEY)
    b.master()
    batches = b.students()
    b.offerings(batches)
    return b, batches


@pytest.fixture(scope="module")
def built():
    return build()


def co_scores(b: Builder, usns: set[str]) -> dict[tuple[str, int], float]:
    """Student CO % per (usn, co_id) for the given students, computed like student_co_score:
    weighted marks / weighted maximum per component (absent = 0), then component-weighted.
    Each student takes each course once, so (usn, co_id) is unique."""
    enrollment = {eid: usn for eid, _, usn in b.rows["enrollment"] if usn in usns}
    component = {aid: comp for aid, _, comp, *_ in b.rows["assessment"]}
    question = {qid: (component[aid], qmax) for qid, aid, _, qmax in b.rows["assessment_question"]}
    tags = defaultdict(list)
    for qid, co, w in b.rows["question_co_map"]:
        tags[qid].append((co, w))
    parts = defaultdict(lambda: [0.0, 0.0])
    for eid, qid, marks, _ in b.rows["student_question_mark"]:
        if eid in enrollment:
            comp, qmax = question[qid]
            for co, w in tags[qid]:
                part = parts[(enrollment[eid], co, comp)]
                part[0] += (marks or 0) * w
                part[1] += qmax * w
    num, den = defaultdict(float), defaultdict(float)
    for (usn, co, comp), (got, top) in parts.items():
        weight = cat.COMPONENT_WEIGHTS[comp]
        num[(usn, co)] += weight * 100 * got / top
        den[(usn, co)] += weight
    return {key: num[key] / den[key] for key in num}


def test_same_seed_gives_the_same_data(built):
    again, _ = build()
    assert again.rows == built[0].rows
    assert again.surveys == built[0].surveys


def test_another_seed_gives_other_marks(built):
    other, _ = build(SEED + 1)
    assert other.rows["student_question_mark"] != built[0].rows["student_question_mark"]


def test_dataset_size(built):
    b, _ = built
    assert len(b.rows["student"]) == 1440
    assert len(b.rows["course_offering"]) == 280
    assert len(b.rows["enrollment"]) == 16800
    assert len(b.rows["student_question_mark"]) == 556800
    assert len(b.locks) == 1488                       # every assessment outside the current term

    current = {oid for oid, _, year, term, *_ in b.rows["course_offering"]
               if (year, term) == (f"{cat.CURRENT_ACADEMIC_YEAR}-{(cat.CURRENT_ACADEMIC_YEAR + 1) % 100:02d}",
                                   cat.CURRENT_TERM)}
    completed = sum(1 for _, oid, _ in b.rows["enrollment"] if oid not in current)
    assert 0.77 < len(b.surveys) / completed < 0.83   # ~80% response, none for the current term


@pytest.mark.parametrize("section", cat.SECTIONS)
def test_planted_cause_stands_out_and_the_decoy_does_not(built, section):
    b, batches = built
    usns = batches[cat.WEAK_BATCH][section]
    scores = co_scores(b, set(usns))
    weak, cause, decoy = (b.co_id[cat.PLANTED[k]] for k in ("weak_co", "cause_co", "decoy_co"))

    def r(up: int) -> float:
        return float(np.corrcoef([scores[(u, up)] for u in usns], [scores[(u, weak)] for u in usns])[0, 1])

    min_r = cat.CONFIG_COMMON["rc_min_r"]
    assert r(cause) > 0.6 > min_r
    assert r(decoy) < min_r


def test_every_programme_outcome_is_mapped(built):
    mapped = {po for _, po, _ in built[0].rows["co_po_map"]}
    assert mapped == set(range(1, len(cat.PROGRAM_OUTCOMES) + 1))


def test_survey_respondents_are_keyed_hashes(built):
    b, _ = built
    usn, oid = "1RV23IS001", 1
    plain = hashlib.sha256(f"{usn}:{oid}:course_exit".encode()).hexdigest()
    assert respondent_hash(usn, oid, "course_exit", KEY) not in {plain, respondent_hash(usn, oid, "course_exit", b"other")}
    assert all("1RV" not in str(doc) for doc in b.surveys[:500])


def test_one_login_per_faculty_member_and_student():
    b = Builder(SEED, KEY)
    b.master()
    batches = b.students()
    b.users(batches, "demo")
    faculty = [row[4] for row in b.rows["app_user"] if row[4] is not None]
    students = [row[5] for row in b.rows["app_user"] if row[5] is not None]
    assert len(faculty) == len(set(faculty)) == cat.FACULTY_COUNT
    assert len(students) == len(set(students))
