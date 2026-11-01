-- worked_example.sql
-- The PRD Section 5 acceptance example: one offering, 60 students, 3 COs, 2 POs.
-- Expected: CO1 3.00, CO2 2.20, CO3 0.40 (below target); PO1 2.30, PO2 1.48.
-- Load into an empty, migrated database.

INSERT INTO department (dept_id, name) VALUES (1, 'Worked Example Department');
INSERT INTO program (program_id, dept_id, name, degree) VALUES (1, 1, 'Worked Example Programme', 'B.E.');
INSERT INTO faculty (faculty_id, dept_id, name, email) VALUES (1, 1, 'Example Faculty', 'example.faculty@example.edu');
INSERT INTO course (course_id, code, title, credits, semester, program_id)
VALUES (1, 'WX101', 'Worked Example Course', 4, 4, 1);

INSERT INTO program_outcome (po_id, program_id, code, type, statement) VALUES
    (1, 1, 'PO1', 'PO', 'Engineering knowledge'),
    (2, 1, 'PO2', 'PO', 'Problem analysis');
INSERT INTO course_outcome (co_id, course_id, co_number, statement, bloom_level) VALUES
    (1, 1, 1, 'Worked example CO1', 2),
    (2, 1, 2, 'Worked example CO2', 3),
    (3, 1, 3, 'Worked example CO3', 4);
-- PO1 from CO1 (3), CO2 (2), CO3 (1); PO2 from CO2 (3), CO3 (2)
INSERT INTO co_po_map (co_id, po_id, strength) VALUES
    (1, 1, 3), (2, 1, 2), (3, 1, 1), (2, 2, 3), (3, 2, 2);

-- target 60%, thresholds 70/60/50, weights 80/20, CO and PO target level 2.0
INSERT INTO attainment_config (config_id, program_id, target_pct, l3_pct, l2_pct, l1_pct,
                               direct_weight, indirect_weight, co_target_level, po_target_level, valid_from)
VALUES (1, 1, 60, 70, 60, 50, 80, 20, 2.0, 2.0, '2020-08-01');
INSERT INTO config_component_weight (config_id, component, weight_pct) VALUES
    (1, 'CIE_THEORY', 20), (1, 'CIE_QUIZ', 10), (1, 'EL', 20), (1, 'SEE', 50);

INSERT INTO course_offering (offering_id, course_id, academic_year, term, faculty_id, section)
VALUES (1, 1, '2025-26', 'even', 1, 'A');

INSERT INTO student (usn, name, program_id, admission_year, section)
SELECT format('1RV25WX%s', lpad(i::text, 3, '0')), 'Student ' || i, 1, 2025, 'A'
FROM generate_series(1, 60) i;
INSERT INTO enrollment (enrollment_id, offering_id, usn)
SELECT i, 1, format('1RV25WX%s', lpad(i::text, 3, '0'))
FROM generate_series(1, 60) i;

-- One assessment, one 10-mark question per CO. Only SEE tests the COs, so each student's
-- CO score is their SEE percentage on that question.
INSERT INTO assessment (assessment_id, offering_id, type, name, max_marks) VALUES (1, 1, 'SEE', 'SEE', 30);
INSERT INTO assessment_question (question_id, assessment_id, q_no, max_marks) VALUES
    (1, 1, 'Q1', 10), (2, 1, 'Q2', 10), (3, 1, 'Q3', 10);
INSERT INTO question_co_map (question_id, co_id, weight) VALUES (1, 1, 1), (2, 2, 1), (3, 3, 1);

-- 48, 39 and 27 of 60 students reach 60%; CO3 uses exactly 6/10 to test the >= boundary.
INSERT INTO student_question_mark (enrollment_id, question_id, marks_obtained, is_absent)
SELECT i, 1, CASE WHEN i <= 48 THEN 8 ELSE 4 END, false FROM generate_series(1, 60) i
UNION ALL
SELECT i, 2, CASE WHEN i <= 39 THEN 7 ELSE 3 END, false FROM generate_series(1, 60) i
UNION ALL
SELECT i, 3, CASE WHEN i <= 27 THEN 6 ELSE 5 END, false FROM generate_series(1, 60) i;

-- Survey-based indirect levels 3, 3 and 2.
INSERT INTO indirect_attainment (offering_id, co_id, respondents, pct_favourable, level) VALUES
    (1, 1, 50, 80.00, 3), (1, 2, 50, 74.00, 3), (1, 3, 50, 62.00, 2);

UPDATE assessment SET locked = true, locked_at = now() WHERE assessment_id = 1;

SELECT setval(pg_get_serial_sequence(t, c), (SELECT 1000))
FROM (VALUES ('department', 'dept_id'), ('program', 'program_id'), ('faculty', 'faculty_id'),
             ('course', 'course_id'), ('program_outcome', 'po_id'), ('course_outcome', 'co_id'),
             ('attainment_config', 'config_id'), ('course_offering', 'offering_id'),
             ('enrollment', 'enrollment_id'), ('assessment', 'assessment_id'),
             ('assessment_question', 'question_id')) AS s(t, c);
