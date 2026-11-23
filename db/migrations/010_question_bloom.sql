-- 010_question_bloom.sql (also: attainment_config.ocr_review_confidence)
-- Answer-sheet OCR (phase 7, FR-3.7): the question paper gives each question a Bloom level, so the
-- level is stored per question as well as per CO. Nullable: questions entered before OCR, or from a
-- paper that does not print a level, have none. Same 1-6 range as course_outcome.bloom_level.
--
-- Grants and row-level security already cover the whole table; the audit trigger copies the row
-- as JSON, so the new column is audited without further changes.

ALTER TABLE assessment_question
    ADD COLUMN bloom_level smallint CHECK (bloom_level BETWEEN 1 AND 6);

-- Values the OCR reads with less confidence than this are highlighted for the teacher to check.
-- A rule like the others, so it is versioned with them and changed as data, not in .env.
ALTER TABLE attainment_config
    ADD COLUMN ocr_review_confidence numeric(3,2) NOT NULL DEFAULT 0.90
        CHECK (ocr_review_confidence > 0 AND ocr_review_confidence <= 1);
