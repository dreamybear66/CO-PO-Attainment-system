# Adding NLP to the CO-PO Attainment System

**Status:** proposal only. Nothing here is built. v1 has no NLP: course-exit surveys store only a
1–5 rating per CO (`api/services/surveys.py`), so there is no text to analyse yet.

This document explains where NLP fits, what it should and should not do, and how to add it in
phases without breaking the existing design rules: PostgreSQL is the source of truth, MongoDB holds
surveys, rules live in `attainment_config`, and only synthetic data is committed.

## Where NLP adds value

| # | Feature | Input text | Output | Value |
| --- | --- | --- | --- | --- |
| 1 | Survey comment sentiment per CO | Free-text comment on each CO in the course-exit survey | Sentiment score per comment, % negative per CO | Explains *why* the indirect rating is low |
| 2 | Theme extraction | All comments for an offering | Ranked themes ("too fast", "needs more labs", "unclear notes") per CO | Gives faculty concrete improvement actions |
| 3 | Improvement-action drafting | Weak CO + root-cause result + top themes | Suggested text for the auto-created improvement action | Saves faculty time; faculty edits before saving |
| 4 | Question → CO / Bloom-level tagging | Question text from the question paper | Suggested CO and Bloom level for each question | Catches wrongly mapped questions before marks are entered |
| 5 | CO statement quality check | CO statements | Flags vague verbs ("understand", "know") and suggests measurable ones | Better-written outcomes, as NBA expects |
| 6 | CO–PO mapping suggestions | CO statement + PO statements | Suggested strength (1–3) for each CO-PO pair | Starting point for the mapping matrix |

Recommended order: **1 → 2 → 3**, then 4–6. Features 1–3 build on the survey pipeline that already
exists; 4–6 need question and outcome text that the schema stores only partly today.

## Ground rules

- **NLP never changes official attainment.** Attainment stays purely numeric (marks + ratings) and
  reproducible. NLP output is advisory: shown next to the numbers, never fed into
  `sp_compute_attainment`. If we ever want sentiment to count, it goes in as a new, versioned weight
  in `attainment_config` with its default set to 0, never hard-coded.
- **Suggestions, not decisions.** Tagging and mapping suggestions (4–6) are shown for a person to
  accept or reject. Accepting one is a normal write that goes through the audit chain.
- **Privacy.** Comments are stored under `respondent_hash` like ratings, never by USN. Strip names,
  USNs, emails and phone numbers from text before analysis or storage. Faculty see themes and
  aggregates, plus individual comments only when an offering has enough respondents (reuse a
  minimum-n rule such as `rc_min_n`).
- **Synthetic data only.** Demo comments come from `datagen/generate.py` templates, never real
  student feedback.
- **Runs offline in batch.** Analysis runs in the nightly job after the survey ETL, not inside a web
  request, so a slow model never blocks the API.

## Phase 1 — Collect free text

1. **Survey schema (MongoDB).** Add an optional `comment` to each answer and an optional
   offering-level `general_comment`:

   ```json
   {
     "survey_type": "course_exit",
     "offering_id": 12,
     "respondent_hash": "…",
     "answers": [
       {"co_id": 41, "rating": 2, "comment": "Normalisation went too fast, needed more examples"}
     ],
     "general_comment": "Labs were useful"
   }
   ```

2. **Validation in `submit_survey`.** Keep the existing reference checks. Add: comment is a string,
   trimmed, at most 1,000 characters, PII-scrubbed (regex for USN pattern, email, phone) before
   insert. Empty comments are dropped.
3. **Web app.** Add an optional text box under each CO rating in the student survey form.
4. **Synthetic data.** Extend `datagen/generate.py` with comment templates that correlate with the
   rating (low ratings → complaint templates), so the demo shows meaningful results.
5. **Tests.** Comment length limit, PII scrubbing, comment optional, old rating-only documents still
   accepted.

## Phase 2 — Sentiment and themes (batch job)

Add `api/jobs/nlp.py`, run from `api/jobs/__main__.py` right after `run_survey_etl`.

1. Read the comments for each offering from `survey_responses`.
2. **Sentiment:** score each comment from −1 to +1.
3. **Themes:** embed the comments, cluster them per offering (or per CO when there are enough), and
   label each cluster with its top keywords.
4. Upsert the results into PostgreSQL (new migration, e.g. `010_nlp.sql`):

   ```sql
   CREATE TABLE survey_text_summary (
       offering_id     int NOT NULL REFERENCES course_offering,
       co_id           int NOT NULL REFERENCES course_outcome,
       comments        int NOT NULL CHECK (comments >= 0),
       pct_negative    numeric(5,2) CHECK (pct_negative BETWEEN 0 AND 100),
       avg_sentiment   numeric(4,3) CHECK (avg_sentiment BETWEEN -1 AND 1),
       model_version   text NOT NULL,
       analysed_at     timestamptz NOT NULL DEFAULT now(),
       PRIMARY KEY (offering_id, co_id)
   );

   CREATE TABLE survey_theme (
       theme_id        serial PRIMARY KEY,
       offering_id     int NOT NULL REFERENCES course_offering,
       co_id           int REFERENCES course_outcome,      -- NULL = offering-level theme
       label           text NOT NULL,
       keywords        text[] NOT NULL,
       comment_count   int NOT NULL CHECK (comment_count > 0),
       avg_sentiment   numeric(4,3),
       model_version   text NOT NULL
   );
   ```

   Same pattern as `indirect_attainment`: derived data, safe to re-run, stamped with
   `model_version` so a result can be traced to the model that produced it.
5. **RLS.** Apply the existing row-level security policies: faculty see only their offerings,
   students see nothing from these tables.
6. **API + UI.** `GET /offerings/{id}/feedback` returns summary + themes. On the Attainment tab,
   show a "What students said" panel next to each CO's indirect level, and on the Root-cause tab,
   show themes for the weak CO next to the upstream-CO evidence.

## Phase 3 — Suggested improvement actions

When the attainment procedure creates an improvement action for a CO below target, a follow-up step
drafts the action text from three inputs: the CO statement, the root-cause result, and the top
negative themes. The draft is stored as `suggested_text` on the action. Faculty edit and save it; the
saved text is what counts, and the save is audited like any other change.

This is the one place where an LLM (rather than a small local model) is worth it. Send only
aggregated themes and CO text, never individual comments or anything identifying a student.

## Phase 4 — Question and outcome text tools

- **Question tagging (4):** if question text is uploaded with the paper, a classifier suggests the
  CO (embedding similarity between question and CO statements) and Bloom level (verb lookup first,
  a classifier later). Mismatches with the entered mapping are flagged for review.
- **CO statement check (5):** rule-based first: a list of non-measurable verbs plus Bloom's verb
  table. No model needed.
- **CO–PO suggestions (6):** similarity between CO and PO statements, mapped to a 1–3 strength
  through thresholds stored in config. Shown as a pre-filled, editable matrix.

## Tool choices

| Need | Simple start | Better later |
| --- | --- | --- |
| PII scrubbing | Regex (USN, email, phone) | spaCy NER for names |
| Sentiment | VADER (fast, no GPU, fine for short English comments) | Fine-tuned transformer, e.g. a DistilBERT/RoBERTa sentiment model |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`, runs on CPU) | Larger embedding model |
| Themes | KMeans / HDBSCAN on embeddings + TF-IDF keywords | BERTopic |
| Bloom verbs | Lookup table | Classifier trained on labelled questions |
| Action drafting | Template text from themes | LLM call with aggregated inputs only |

Keep the NLP dependencies in an optional extra (e.g. `pip install .[nlp]`) so the core API and
tests do not need them.

## Testing

- **Unit:** PII scrubber, comment validation, theme labelling on a fixed set of synthetic comments.
- **Determinism:** fix random seeds for clustering; pin model versions; store `model_version`.
- **Golden set:** about 100 labelled synthetic comments; check that sentiment accuracy stays above
  an agreed level when the model changes.
- **Isolation:** a test that runs the attainment procedure with and without NLP tables populated and
  checks that the official results are identical.
- **Security:** RLS tests for the new tables, the same as the existing per-role tests.

## Effort estimate

| Phase | Work | Rough size |
| --- | --- | --- |
| 1 | Comment field, validation, form, synthetic comments | 1–2 days |
| 2 | NLP job, two tables, API endpoint, UI panel | 3–5 days |
| 3 | Suggested action text | 1–2 days |
| 4 | Question/CO tools | 1 week+ |

## Open questions

- Should students be able to comment in languages other than English? That changes the model choice.
- What minimum number of comments should an offering need before individual comments are visible?
- Is an external LLM API acceptable for Phase 3, or must everything run on college servers?
