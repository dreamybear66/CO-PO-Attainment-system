-- 010_question_bloom.sql
-- Answer-sheet OCR (phase 7, FR-3.7): the question paper gives each question a Bloom level, so the
-- level is stored per question as well as per CO. Nullable: questions entered before OCR, or from a
-- paper that does not print a level, have none. Same 1-6 range as course_outcome.bloom_level.
--
-- Grants and row-level security already cover the whole table; the audit trigger copies the row
-- as JSON, so the new column is audited without further changes.

ALTER TABLE assessment_question
    ADD COLUMN bloom_level smallint CHECK (bloom_level BETWEEN 1 AND 6);
