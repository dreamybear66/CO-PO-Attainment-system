"""Minimal root-cause scenarios for tests and the evaluation script (PRD Section 11.6).

Three courses in a prerequisite chain, one offering each, n students, one SEE per offering with
one 10-mark question per CO:

    FD001 (2023-24 odd) -> UP101 (2024-25 odd) -> DN201 (2024-25 even)

Declared dependencies: DN201 CO4 <- UP101 CO2 (3, the planted cause), DN201 CO4 <- UP101 CO5
(2, a decoy with no real link), UP101 CO2 <- FD001 CO1 (3, reached at depth 2).
`effect` sets how strongly DN201 CO4 skill follows UP101 CO2 skill (0 = no link).
"""

import numpy as np

COURSES = [(1, "FD001", 1, "2023-24", "odd"), (2, "UP101", 3, "2024-25", "odd"), (3, "DN201", 4, "2024-25", "even")]


def co_id(course: int, n: int) -> int:
    return course * 10 + n


WEAK = co_id(3, 4)
CAUSE = co_id(2, 2)
DECOY = co_id(2, 5)
DEEP = co_id(1, 1)
DN_OFFERING = 3


def build(conn, *, n: int = 60, effect: float = 0.8, noise: float = 0.5, seed: int = 1) -> None:
    """Load the scenario into an empty, migrated database (owner connection, autocommit)."""
    rng = np.random.default_rng(seed)
    conn.execute("""
        INSERT INTO department VALUES (1, 'Scenario Dept');
        INSERT INTO program VALUES (1, 1, 'Scenario Programme', 'B.E.');
        INSERT INTO faculty VALUES (1, 1, 'Scenario Faculty', 'scenario@example.edu'),
                                   (2, 1, 'Other Faculty', 'other@example.edu');
        INSERT INTO program_outcome VALUES (1, 1, 'PO1', 'PO', 'Engineering knowledge');
        INSERT INTO attainment_config (config_id, program_id, target_pct, l3_pct, l2_pct, l1_pct,
            direct_weight, indirect_weight, co_target_level, po_target_level, valid_from)
        VALUES (1, 1, 60, 70, 60, 50, 80, 20, 2.0, 2.0, '2020-08-01');
        INSERT INTO config_component_weight VALUES (1, 'CIE_THEORY', 20), (1, 'CIE_QUIZ', 10), (1, 'EL', 20), (1, 'SEE', 50);
    """)
    for cid, code, sem, year, term in COURSES:
        conn.execute("INSERT INTO course VALUES (%s, %s, %s, 4, %s, 1)", (cid, code, code, sem))
        for k in range(1, 6):
            conn.execute("INSERT INTO course_outcome VALUES (%s, %s, %s, %s, 3)", (co_id(cid, k), cid, k, f"{code} CO{k}"))
            conn.execute("INSERT INTO co_po_map VALUES (%s, 1, 2)", (co_id(cid, k),))
        conn.execute("INSERT INTO course_offering VALUES (%s, %s, %s, %s, 1, 'A')", (cid, cid, year, term))
    conn.execute("INSERT INTO course_prerequisite VALUES (2, 1), (3, 2)")
    conn.execute("INSERT INTO co_dependency VALUES (%s, %s, 3), (%s, %s, 2), (%s, %s, 3)",
                 (WEAK, CAUSE, WEAK, DECOY, CAUSE, DEEP))

    usns = [f"1RV23SC{i:03d}" for i in range(1, n + 1)]
    with conn.cursor().copy("COPY student (usn, name, program_id, admission_year, section) FROM STDIN") as cp:
        for u in usns:
            cp.write_row((u, u, 1, 2023, "A"))

    skill = {co: rng.normal(size=n) for cid, *_ in COURSES for co in (co_id(cid, k) for k in range(1, 6))}
    skill[CAUSE] = 0.7 * skill[DEEP] + np.sqrt(1 - 0.49) * skill[CAUSE]
    skill[WEAK] = effect * skill[CAUSE] + np.sqrt(1 - effect ** 2) * skill[WEAK] - 0.6 * effect

    enrollment = 0
    for cid, *_ in COURSES:
        conn.execute("INSERT INTO assessment VALUES (%s, %s, 'SEE', 'SEE', 50, false, NULL)", (cid, cid))
        for k in range(1, 6):
            conn.execute("INSERT INTO assessment_question VALUES (%s, %s, %s, 10)", (co_id(cid, k), cid, f"Q{k}"))
            conn.execute("INSERT INTO question_co_map VALUES (%s, %s, 1)", (co_id(cid, k), co_id(cid, k)))
        rows = []
        for i, u in enumerate(usns):
            enrollment += 1
            conn.execute("INSERT INTO enrollment VALUES (%s, %s, %s)", (enrollment, cid, u))
            for k in range(1, 6):
                z = skill[co_id(cid, k)][i] + noise * rng.normal()
                rows.append((enrollment, co_id(cid, k), float(np.clip(np.round(10 / (1 + np.exp(-(0.7 + 1.1 * z)))), 0, 10))))
        with conn.cursor().copy("COPY student_question_mark (enrollment_id, question_id, marks_obtained) FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)
        conn.execute("UPDATE assessment SET locked = true WHERE assessment_id = %s", (cid,))
    conn.execute("CALL sp_compute_all()")
