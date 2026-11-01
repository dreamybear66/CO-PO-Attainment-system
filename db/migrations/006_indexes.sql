-- 006_indexes.sql
-- Indexes for the attainment aggregation (PRD NFR-7). Kept in their own migration so the
-- before/after EXPLAIN ANALYZE comparison can run with `migrate --until 005` first.
-- Already covered by constraint indexes, so not repeated here:
--   student_question_mark (enrollment_id, ...)  primary key
--   enrollment (offering_id, ...)               UNIQUE (offering_id, usn)
-- These serve the per-offering computation. The indexes below serve access by CO or by question
-- across offerings (root-cause analysis, trends) and the remaining foreign-key joins.

CREATE INDEX student_question_mark_question_idx ON student_question_mark (question_id);
CREATE INDEX question_co_map_co_idx             ON question_co_map (co_id);
CREATE INDEX assessment_offering_idx            ON assessment (offering_id);
CREATE INDEX assessment_question_assessment_idx ON assessment_question (assessment_id);
CREATE INDEX course_offering_course_idx         ON course_offering (course_id);
CREATE INDEX course_offering_faculty_idx        ON course_offering (faculty_id);
CREATE INDEX co_attainment_co_idx               ON co_attainment (co_id);
CREATE INDEX enrollment_usn_idx                 ON enrollment (usn);
