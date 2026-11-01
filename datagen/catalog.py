"""Fixed catalogue for the synthetic ISE programme: courses, prerequisites, COs, POs."""

PROGRAM = {"dept": "Information Science and Engineering",
           "name": "B.E. Information Science and Engineering", "degree": "B.E."}

# code, title, credits, semester, prerequisite codes
COURSES = [
    ("IS111", "Programming in C", 4, 1, []),
    ("MA111", "Engineering Mathematics", 4, 1, []),
    ("IS121", "Object-Oriented Programming", 4, 2, ["IS111"]),
    ("MA121", "Discrete Mathematical Structures", 3, 2, []),
    ("IS231", "Data Structures", 4, 3, ["IS111", "MA121"]),
    ("IS232", "Digital Logic Design", 3, 3, []),
    ("IS233", "Computer Organization", 3, 3, ["IS232"]),
    ("IS241", "Design and Analysis of Algorithms", 4, 4, ["IS231"]),
    ("IS242", "Operating Systems", 4, 4, ["IS233"]),
    ("IS243", "Database Management Systems", 4, 4, ["IS231", "MA121"]),
    ("IS351", "Computer Networks", 4, 5, ["IS242"]),
    ("IS352", "Software Engineering", 3, 5, ["IS121"]),
    ("IS353", "Theory of Computation", 3, 5, ["MA121"]),
    ("IS361", "Compiler Design", 4, 6, ["IS353", "IS231"]),
    ("IS362", "Machine Learning", 4, 6, ["MA111", "IS241"]),
    ("IS363", "Cloud Computing", 3, 6, ["IS351", "IS242"]),
]

CO_COUNT = 5

# Statements for the courses in the planted root-cause story; other courses get generic ones.
CO_STATEMENTS = {
    "IS111": ["Write programs using control structures", "Use functions and recursion",
              "Process arrays and strings", "Define structures and unions",
              "Use pointers and files"],
    "MA121": ["Apply propositional and predicate logic", "Construct proofs by induction",
              "Use sets, relations and functions", "Solve counting problems",
              "Model problems with graphs"],
    "IS231": ["Implement stacks, queues and linked lists", "Apply trees and hashing to search problems",
              "Analyse graph representations and traversals", "Compare sorting techniques",
              "Design solutions with suitable data structures"],
    "IS243": ["Model data with ER diagrams", "Apply the relational model and relational algebra",
              "Write SQL queries, views and triggers", "Analyse indexing (B+ trees, hashing) and query processing",
              "Design normalised schemas and reliable transactions"],
}

BLOOM_VERBS = {1: "Recall", 2: "Explain", 3: "Apply", 4: "Analyse", 5: "Evaluate", 6: "Design"}

PROGRAM_OUTCOMES = [
    ("PO1", "PO", "Engineering knowledge"),
    ("PO2", "PO", "Problem analysis"),
    ("PO3", "PO", "Design and development of solutions"),
    ("PO4", "PO", "Conduct investigations of complex problems"),
    ("PO5", "PO", "Modern tool usage"),
    ("PO6", "PO", "The engineer and society"),
    ("PO7", "PO", "Environment and sustainability"),
    ("PO8", "PO", "Ethics"),
    ("PO9", "PO", "Individual and team work"),
    ("PO10", "PO", "Communication"),
    ("PO11", "PO", "Project management and finance"),
    ("PO12", "PO", "Life-long learning"),
    ("PSO1", "PSO", "Apply data and software engineering to information systems"),
    ("PSO2", "PSO", "Build secure, scalable computing solutions"),
]

# Planted root-cause story (PRD Section 11.6). In the weak batch, Data Structures CO2 is
# weakened for half the students and DBMS CO4 depends strongly on it for the same students.
# Programming in C CO5 is a declared but unrelated (decoy) dependency of DBMS CO4.
WEAK_BATCH = 2023
PLANTED = {"weak_co": ("IS243", 4), "cause_co": ("IS231", 2), "decoy_co": ("IS111", 5)}
FIXED_DEPENDENCIES = [
    (("IS243", 4), ("IS231", 2), 3),
    (("IS243", 2), ("MA121", 3), 2),
    (("IS243", 4), ("IS111", 5), 2),
]

# (name, component, max marks per question, CO numbers covered). Questions cycle through the
# covered COs; the last question of each CIE test is shared 50/50 by its first and last CO.
ASSESSMENTS = [
    ("CIE Test 1", "CIE_THEORY", [10, 10, 10, 10, 5, 5], [1, 2, 3]),
    ("CIE Test 2", "CIE_THEORY", [10, 10, 10, 10, 5, 5], [3, 4, 5]),
    ("Quiz 1", "CIE_QUIZ", [2, 2, 2, 2, 2], [1, 2, 3]),
    ("Quiz 2", "CIE_QUIZ", [2, 2, 2, 2, 2], [3, 4, 5]),
    ("Experiential Learning", "EL", [10, 10, 10, 10], [2, 4, 5]),
    ("SEE", "SEE", [10] * 10, [1, 2, 3, 4, 5]),
]
SHARED_LAST_QUESTION = {"CIE Test 1", "CIE Test 2"}
# In the current (in-progress) term only these assessments have happened.
CURRENT_TERM_ASSESSMENTS = {"CIE Test 1", "Quiz 1"}

# Logit offsets per component: quizzes and EL score higher than the SEE.
COMPONENT_EASE = {"CIE_THEORY": 0.7, "CIE_QUIZ": 0.9, "EL": 1.1, "SEE": 0.4}
ABSENCE_RATE = {"CIE_THEORY": 0.03, "CIE_QUIZ": 0.03, "EL": 0.0, "SEE": 0.01}

# Two rule versions show that results keep the config they were computed with.
CONFIGS = [
    {"valid_from": "2021-08-01", "valid_to": "2024-08-01", "target_pct": 55},
    {"valid_from": "2024-08-01", "valid_to": None, "target_pct": 60},
]
CONFIG_COMMON = {"l3_pct": 70, "l2_pct": 60, "l1_pct": 50, "direct_weight": 80,
                 "indirect_weight": 20, "co_target_level": 2.0, "po_target_level": 2.0}
COMPONENT_WEIGHTS = {"CIE_THEORY": 20, "CIE_QUIZ": 10, "EL": 20, "SEE": 50}

BATCHES = [2021, 2022, 2023, 2024, 2025, 2026]
SECTIONS = ["A", "B", "C", "D"]
STUDENTS_PER_SECTION = 60
CURRENT_ACADEMIC_YEAR = 2026   # 2026-27
CURRENT_TERM = "odd"
FACULTY_COUNT = 14
