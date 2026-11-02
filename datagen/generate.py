"""Synthetic dataset generator (Phase 2).

Builds one ISE programme with 16 courses, 6 student batches (1,440 students) and every course
offering from 2021-22 to the current term (2026-27 odd), then loads PostgreSQL with COPY and
writes course-exit surveys to MongoDB. Deterministic for a given --seed.

Each student has a latent skill per CO; question marks follow a logistic curve of that skill.
The weak batch carries the planted root-cause story described in datagen/catalog.py.

Usage:  python -m datagen.generate [--reset] [--seed 2026] [--database copo]
"""

import argparse
import time
from datetime import datetime, timezone

import bcrypt
import numpy as np
import psycopg
from faker import Faker
from pymongo import ASCENDING, MongoClient
from pymongo.database import Database

from api import config
from api.survey_hash import respondent_hash
from datagen import catalog as cat
from scripts.migrate import truncate_all

# Latent skill per (student, CO) = SHARED_ABILITY x general ability + UNIQUE x CO-specific noise,
# with unit variance. The shared part correlates every pair of COs (latent r = SHARED_ABILITY^2),
# so it is kept small: at 0.35 (r = 0.12), sampling at n = 60 per section pushed three unrelated
# declared dependencies and the decoy to the root-cause threshold rc_min_r = 0.40. At 0.15
# (r = 0.02), seed 2026 gives the planted pair r = 0.75-0.82 in every weak-batch section, the
# decoy at most 0.38, and one unrelated pair above 0.40 (IS363 CO3 <- IS233 CO2, 2024-25 even B,
# r = 0.46), which is sampling noise: it stays at 0.45 with no shared ability at all.
SHARED_ABILITY = 0.15
UNIQUE = float(np.sqrt(1 - SHARED_ABILITY ** 2))

TABLES_IN_LOAD_ORDER = [
    "department", "program", "faculty", "student", "course", "course_prerequisite",
    "program_outcome", "course_outcome", "co_po_map", "co_dependency",
    "attainment_config", "config_component_weight", "course_offering", "enrollment",
    "assessment", "assessment_question", "question_co_map", "student_question_mark", "app_user",
]


def academic_year(year: int) -> str:
    return f"{year}-{(year + 1) % 100:02d}"


def term_end(year: int, term: str) -> datetime:
    return (datetime(year, 12, 15, tzinfo=timezone.utc) if term == "odd"
            else datetime(year + 1, 5, 15, tzinfo=timezone.utc))


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


class Builder:
    def __init__(self, seed: int, hash_key: bytes):
        self.rng = np.random.default_rng(seed)
        # Own stream for the PO6-PO11 maps, so adding them left every other draw unchanged.
        self.soft_po_rng = np.random.default_rng([seed, 1])
        self.hash_key = hash_key          # SURVEY_HASH_SECRET, for respondent ids
        self.fake = Faker("en_IN")
        Faker.seed(seed)
        self.rows: dict[str, list[tuple]] = {t: [] for t in TABLES_IN_LOAD_ORDER}
        self.surveys: list[dict] = []
        self.locks: list[int] = []        # assessment ids to lock after marks are loaded
        self.course_id: dict[str, int] = {}
        self.co_id: dict[tuple[str, int], int] = {}
        # Latent skill: one row per student (skill_row[usn]), one column per CO (co_id - 1).
        self.skill = np.empty((0, 0))
        self.skill_row: dict[str, int] = {}

    # ------------------------------------------------------------------ master data

    def master(self) -> None:
        r = self.rows
        r["department"].append((1, cat.PROGRAM["dept"]))
        r["program"].append((1, 1, cat.PROGRAM["name"], cat.PROGRAM["degree"]))

        for fid in range(1, cat.FACULTY_COUNT + 1):
            first, last = self.fake.first_name(), self.fake.last_name()
            r["faculty"].append((fid, 1, f"{first} {last}", f"{first}.{last}{fid}@example.edu".lower()))

        for cid, (code, title, credits, sem, _) in enumerate(cat.COURSES, start=1):
            self.course_id[code] = cid
            r["course"].append((cid, code, title, credits, sem, 1))
        for code, _, _, _, prereqs in cat.COURSES:
            for p in prereqs:
                r["course_prerequisite"].append((self.course_id[code], self.course_id[p]))

        for pid, (code, kind, statement) in enumerate(cat.PROGRAM_OUTCOMES, start=1):
            r["program_outcome"].append((pid, 1, code, kind, statement))

        co = 0
        for code, title, *_ in cat.COURSES:
            for n in range(1, cat.CO_COUNT + 1):
                co += 1
                self.co_id[(code, n)] = co
                bloom = min(6, 1 + n + int(self.rng.integers(0, 2)))
                statement = (cat.CO_STATEMENTS[code][n - 1] if code in cat.CO_STATEMENTS
                             else f"{cat.BLOOM_VERBS[bloom]} the unit {n} concepts of {title}")
                r["course_outcome"].append((co, self.course_id[code], n, statement, bloom))
                # Every CO supports PO1, plus 1-3 of PO2-PO5, PO12, PSO1, PSO2, and sometimes
                # one of PO6-PO11 at strength 1.
                r["co_po_map"].append((co, 1, int(self.rng.integers(2, 4))))
                extra = self.rng.choice([2, 3, 4, 5, 12, 13, 14], size=int(self.rng.integers(1, 4)), replace=False)
                for po in sorted(int(p) for p in extra):
                    r["co_po_map"].append((co, po, int(self.rng.integers(1, 4))))
                if self.soft_po_rng.random() < cat.SOFT_PO_SHARE:
                    r["co_po_map"].append((co, int(self.soft_po_rng.choice(cat.SOFT_POS)), 1))

        self.dependencies()

        for cfg_id, cfg in enumerate(cat.CONFIGS, start=1):
            c = cat.CONFIG_COMMON
            r["attainment_config"].append((
                cfg_id, 1, cfg["target_pct"], c["l3_pct"], c["l2_pct"], c["l1_pct"],
                c["direct_weight"], c["indirect_weight"], c["co_target_level"], c["po_target_level"],
                c["rc_min_n"], c["rc_min_r"], cfg["valid_from"], cfg["valid_to"],
            ))
            for comp, w in cat.COMPONENT_WEIGHTS.items():
                r["config_component_weight"].append((cfg_id, comp, w))

    def dependencies(self) -> None:
        """Fixed planted dependencies plus random ones to prerequisite-course COs."""
        seen = set()
        for (wc, wn), (pc, pn), strength in cat.FIXED_DEPENDENCIES:
            key = (self.co_id[(wc, wn)], self.co_id[(pc, pn)])
            seen.add(key)
            self.rows["co_dependency"].append((*key, strength))
        planted_course = cat.PLANTED["weak_co"][0]
        for code, _, _, _, prereqs in cat.COURSES:
            if not prereqs or code == planted_course:
                continue
            for n in range(1, cat.CO_COUNT + 1):
                if self.rng.random() < 0.4:
                    p = prereqs[int(self.rng.integers(0, len(prereqs)))]
                    key = (self.co_id[(code, n)], self.co_id[(p, int(self.rng.integers(1, cat.CO_COUNT + 1)))])
                    if key not in seen:
                        seen.add(key)
                        self.rows["co_dependency"].append((*key, int(self.rng.integers(1, 4))))

    # ------------------------------------------------------------------ students

    def students(self) -> dict[int, dict[str, list[str]]]:
        """Returns batch -> section -> [usn]."""
        out: dict[int, dict[str, list[str]]] = {}
        n_students = len(cat.BATCHES) * len(cat.SECTIONS) * cat.STUDENTS_PER_SECTION
        self.skill = np.empty((n_students, len(self.co_id)))
        for batch in cat.BATCHES:
            out[batch] = {s: [] for s in cat.SECTIONS}
            for i in range(len(cat.SECTIONS) * cat.STUDENTS_PER_SECTION):
                usn = f"1RV{batch % 100:02d}IS{i + 1:03d}"
                section = cat.SECTIONS[i // cat.STUDENTS_PER_SECTION]
                out[batch][section].append(usn)
                self.rows["student"].append((usn, self.fake.name(), 1, batch, section))
                row = self.skill_row[usn] = len(self.skill_row)
                theta = self.rng.normal()
                self.skill[row] = SHARED_ABILITY * theta + UNIQUE * self.rng.normal(size=len(self.co_id))
            if batch == cat.WEAK_BATCH:
                self.plant(out[batch])
        return out

    def plant(self, sections: dict[str, list[str]]) -> None:
        cause = self.co_id[cat.PLANTED["cause_co"]] - 1
        weak = self.co_id[cat.PLANTED["weak_co"]] - 1
        for usns in sections.values():
            for usn in usns:
                row = self.skill_row[usn]
                if self.rng.random() < 0.5:
                    self.skill[row, cause] -= 1.2
                self.skill[row, weak] = 0.8 * self.skill[row, cause] + 0.6 * self.rng.normal()

    # ------------------------------------------------------------------ offerings and marks

    def offerings(self, batches: dict[int, dict[str, list[str]]]) -> None:
        r = self.rows
        # Two faculty per course: sections A/B and C/D.
        teachers = {code: (1 + (2 * i) % cat.FACULTY_COUNT, 1 + (2 * i + 1) % cat.FACULTY_COUNT)
                    for i, (code, *_) in enumerate(cat.COURSES)}
        current = (cat.CURRENT_ACADEMIC_YEAR, cat.CURRENT_TERM)
        ids = {"offering": 0, "enrollment": 0, "assessment": 0, "question": 0}

        for batch, sections in batches.items():
            for code, _, _, sem, _ in cat.COURSES:
                course_cos = [self.co_id[(code, n)] for n in range(1, cat.CO_COUNT + 1)]
                year = batch + (sem - 1) // 2
                term = "odd" if sem % 2 else "even"
                if (year, term == "even") > (current[0], current[1] == "even"):
                    continue
                is_current = (year, term) == current
                for si, (section, usns) in enumerate(sections.items()):
                    ids["offering"] += 1
                    oid = ids["offering"]
                    fac = teachers[code][0 if si < 2 else 1]
                    r["course_offering"].append((oid, self.course_id[code], academic_year(year), term, fac, section))
                    enrol = []
                    for usn in usns:
                        ids["enrollment"] += 1
                        enrol.append((ids["enrollment"], usn))
                        r["enrollment"].append((ids["enrollment"], oid, usn))
                    # students x this course's COs, built once per offering
                    skills = self.skill[np.ix_([self.skill_row[u] for u in usns],
                                               [co - 1 for co in course_cos])]
                    for name, comp, qmarks, cos in cat.ASSESSMENTS:
                        if is_current and name not in cat.CURRENT_TERM_ASSESSMENTS:
                            continue
                        ids["assessment"] += 1
                        aid = ids["assessment"]
                        r["assessment"].append((aid, oid, comp, name, sum(qmarks), False, None))
                        if not is_current:
                            self.locks.append(aid)
                        questions = []
                        for qi, qmax in enumerate(qmarks):
                            ids["question"] += 1
                            qid = ids["question"]
                            r["assessment_question"].append((qid, aid, f"Q{qi + 1}", qmax))
                            if name in cat.SHARED_LAST_QUESTION and qi == len(qmarks) - 1:
                                tags = [(cos[0], 0.5), (cos[-1], 0.5)]
                            else:
                                tags = [(cos[qi % len(cos)], 1.0)]
                            weights = np.zeros(cat.CO_COUNT)      # question's weight per course CO
                            for n, w in tags:
                                r["question_co_map"].append((qid, self.co_id[(code, n)], w))
                                weights[n - 1] = w
                            questions.append((qid, qmax, weights))
                        self.marks(enrol, comp, questions, skills)
                    if not is_current:
                        self.survey(oid, course_cos, enrol, skills, year, term)

    def marks(self, enrol, comp, questions, skills) -> None:
        n = len(enrol)
        absent = self.rng.random(n) < cat.ABSENCE_RATE[comp]
        rows = self.rows["student_question_mark"]
        for qid, qmax, weights in questions:
            z = skills @ weights
            frac = sigmoid(cat.COMPONENT_EASE[comp] + 1.1 * z + self.rng.normal(0, 0.6, n))
            got = np.clip(np.round(frac * qmax * 2) / 2, 0, qmax)
            for (eid, _), a, m in zip(enrol, absent, got):
                rows.append((eid, qid, None, True) if a else (eid, qid, float(m), False))

    def survey(self, oid, cos, enrol, skills, year, term) -> None:
        submitted = term_end(year, term)
        for i, (_, usn) in enumerate(enrol):
            if self.rng.random() >= 0.8:
                continue
            answers = [{"co_id": co, "rating": int(np.clip(round(4.0 + 0.7 * skills[i, j]
                                                                  + self.rng.normal(0, 0.7)), 1, 5))}
                       for j, co in enumerate(cos)]
            self.surveys.append({
                "survey_type": "course_exit",
                "offering_id": oid,
                "respondent_hash": respondent_hash(usn, oid, "course_exit", self.hash_key),
                "submitted_at": submitted,
                "answers": answers,
            })

    # ------------------------------------------------------------------ users

    def users(self, batches, password: str) -> None:
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        r = self.rows["app_user"]
        # The HoD login is not linked to a faculty row: fac01 is faculty 1's login, and
        # app_user.faculty_id is unique (one login per faculty member).
        r.append((1, "hod", pw_hash, "admin", None, None))
        r.append((2, "coordinator", pw_hash, "coordinator", None, None))
        uid = 2
        for fid in range(1, cat.FACULTY_COUNT + 1):
            uid += 1
            r.append((uid, f"fac{fid:02d}", pw_hash, "faculty", fid, None))
        for section, usns in batches[cat.WEAK_BATCH].items():
            uid += 1
            r.append((uid, usns[0].lower(), pw_hash, "student", None, usns[0]))


COLUMNS = {
    "department": "dept_id, name",
    "program": "program_id, dept_id, name, degree",
    "faculty": "faculty_id, dept_id, name, email",
    "student": "usn, name, program_id, admission_year, section",
    "course": "course_id, code, title, credits, semester, program_id",
    "course_prerequisite": "course_id, prereq_course_id",
    "program_outcome": "po_id, program_id, code, type, statement",
    "course_outcome": "co_id, course_id, co_number, statement, bloom_level",
    "co_po_map": "co_id, po_id, strength",
    "co_dependency": "co_id, prereq_co_id, strength",
    "attainment_config": ("config_id, program_id, target_pct, l3_pct, l2_pct, l1_pct, direct_weight, "
                          "indirect_weight, co_target_level, po_target_level, rc_min_n, rc_min_r, valid_from, valid_to"),
    "config_component_weight": "config_id, component, weight_pct",
    "course_offering": "offering_id, course_id, academic_year, term, faculty_id, section",
    "enrollment": "enrollment_id, offering_id, usn",
    "assessment": "assessment_id, offering_id, type, name, max_marks, locked, locked_at",
    "assessment_question": "question_id, assessment_id, q_no, max_marks",
    "question_co_map": "question_id, co_id, weight",
    "student_question_mark": "enrollment_id, question_id, marks_obtained, is_absent",
    "app_user": "user_id, username, password_hash, role, faculty_id, usn",
}
SERIALS = {
    "department": "dept_id", "program": "program_id", "faculty": "faculty_id", "course": "course_id",
    "program_outcome": "po_id", "course_outcome": "co_id", "attainment_config": "config_id",
    "course_offering": "offering_id", "enrollment": "enrollment_id", "assessment": "assessment_id",
    "assessment_question": "question_id", "app_user": "user_id",
}


def load(b: Builder, dbname: str | None, mongo: Database, reset: bool) -> None:
    """Load both stores as one unit as far as possible: the PostgreSQL transaction commits only
    after the surveys are in MongoDB, so a MongoDB failure rolls the PostgreSQL load back."""
    with psycopg.connect(config.owner_dsn(dbname)) as conn:   # commits on exit, rolls back on error
        load_postgres(b, conn, reset)
        load_mongo(b, mongo, reset)


def load_postgres(b: Builder, conn: psycopg.Connection, reset: bool) -> None:
    with conn.cursor() as cur:
        if reset:
            truncate_all(cur)
        # Seed data is not an audited change: keep the audit triggers (audit_insert, audit_row)
        # from copying ~570k loaded rows into audit_outbox and the MongoDB hash chain. DISABLE
        # TRIGGER is transactional, so a failed load leaves them enabled.
        audit = cur.execute(
            "SELECT quote_ident(c.relname), quote_ident(t.tgname) FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE c.relnamespace = 'public'::regnamespace AND NOT t.tgisinternal "
            "AND t.tgenabled <> 'D' AND t.tgname LIKE 'audit%'"
        ).fetchall()
        for table, trigger in audit:
            cur.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
        for table in TABLES_IN_LOAD_ORDER:
            with cur.copy(f"COPY {table} ({COLUMNS[table]}) FROM STDIN") as copy:
                for row in b.rows[table]:
                    copy.write_row(row)
            print(f"  {table:<24} {len(b.rows[table]):>8,} rows")
        for table, col in SERIALS.items():
            cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', '{col}'), "
                        f"(SELECT max({col}) FROM {table}))")
        # Lock completed assessments only after their marks are in. The lock trigger counts each
        # assessment's marks; without statistics on the fresh rows it scans all of them per
        # assessment (minutes), so analyze first.
        cur.execute("ANALYZE")
        cur.execute("UPDATE assessment SET locked = true, locked_at = now() "
                    "WHERE assessment_id = ANY(%s)", (b.locks,))
        print(f"  locked {cur.rowcount:,} assessments")
        for table, trigger in audit:
            cur.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")


def load_mongo(b: Builder, db: Database, reset: bool) -> None:
    if reset:
        # Reset both stores together. delete_many keeps the collections' indexes. The audit chain
        # mirrors audit_outbox, whose ids the PostgreSQL truncate restarts at 1; a stale audit_log
        # would make the outbox writer treat new rows as already copied.
        db.survey_responses.delete_many({})
        db.audit_log.delete_many({})
    # One response per respondent, offering and survey type (S12). Same definition as
    # api.mongo.ensure_indexes, so creating it twice is a no-op.
    db.survey_responses.create_index(
        [("respondent_hash", ASCENDING), ("offering_id", ASCENDING), ("survey_type", ASCENDING)],
        unique=True, name="one_response_per_respondent",
    )
    if b.surveys:
        db.survey_responses.insert_many(b.surveys, ordered=False)
    print(f"  survey_responses         {len(b.surveys):>8,} documents")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--reset", action="store_true", help="truncate tables and surveys first")
    parser.add_argument("--database")
    args = parser.parse_args()

    # Check settings and both databases before the 10-40 s of generation.
    demo_password = config._env("DEMO_PASSWORD")
    hash_key = config.survey_hash_secret().encode()
    dbname = args.database or config.PG_DATABASE
    with psycopg.connect(config.owner_dsn(dbname)) as conn:
        if conn.execute("SELECT to_regclass('public.student_question_mark')").fetchone()[0] is None:
            raise SystemExit(f"Database {dbname} has no schema; run `python -m scripts.migrate` first")
    client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    # Surveys go to the MongoDB database named like the PostgreSQL one (default MONGO_DATABASE),
    # so --database copo_test never touches the main dataset.
    mongo = client[args.database or config.MONGO_DATABASE]

    started = time.perf_counter()
    b = Builder(args.seed, hash_key)
    b.master()
    batches = b.students()
    b.offerings(batches)
    b.users(batches, demo_password)
    print(f"generated in {time.perf_counter() - started:.1f}s; loading")
    load(b, dbname, mongo, args.reset)
    print(f"done in {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main()
