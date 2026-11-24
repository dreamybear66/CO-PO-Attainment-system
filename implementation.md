# Implementation Plan

How the CO-PO Attainment Management System gets built. Requirement IDs (FR-x, NFR-x) and suggested
changes (S1–S13) refer to the [PRD](https://claude.ai/artifact/G8HdvxVTjQ47XZ6AeEhard).

## Progress (23 Nov 2026)

Phases 1–6 are built and merged; phases 7–10 are built (PRs open); 205 tests pass. On 23 Nov 2026 the project was rescoped from
accreditation support to automating teachers' CO-PO work, which added phases 7–10 (not started).

| Phase | Status | Branch · PR | Output |
| --- | --- | --- | --- |
| Planning | Merged | `docs/project-planning` · #1 | PRD, this plan, CLAUDE.md |
| 1 — Schema and constraints | Merged | `feat/schema` · #2 | 29 tables, ER diagram, CHECK/EXCLUDE constraints |
| 2 — Synthetic data | Merged | `feat/datagen` · #3 | 556,800 marks, 1,440 students, 280 offerings, worked-example fixture |
| 3 — Attainment engine | Merged | `feat/attainment-engine` · #4 | Triggers, `sp_compute_attainment`, matches the worked example exactly |
| 4 — MongoDB, ETL, audit | Merged | `feat/mongo-audit` · #5 | 11,965 surveys, ETL, 573,223 audit records chained and verified |
| 5 — Innovation features | Merged | `feat/innovation` · #6 | Root cause (planted cause ranks 1st, decoy excluded), what-if, versioned rules |
| 6 — API, UI, security | Merged | `feat/web-app` · #7 | RLS on 17 tables, FastAPI, React app, demo script, test report |
| NLP plan | Merged | `docs/nlp-plan` · #8 | [nlp.md](nlp.md), a proposal only |
| Rescope | PR open | `docs/rescope` | PRD, CLAUDE.md, README and this plan updated for teacher automation |
| UI motion | PR open | `feat/ui-motion` | Motion/GSAP animation layer, animated sign-in; `main` merged in |
| Landing page | PR open | `feat/landing-page` | Product page at `/` for signed-out visitors, rendered ER diagram images |
| 7 — Answer-sheet OCR | PR open | `feat/answer-sheet-ocr` | See [Phase 7](#phase-7--answer-sheet-ocr-novelty) |
| 8 — Google Forms surveys | PR open | `feat/google-forms-surveys` | See [Phase 8](#phase-8--google-forms-surveys-and-whatsapp-sharing) |
| 9 — Weak students, early warning | PR open | `feat/early-warning` | See [Phase 9](#phase-9--weak-student-lists-and-early-warning-novelty) |
| 10 — Course-file PDF | PR open | `feat/course-file` | See [Phase 10](#phase-10--course-file-pdf) |
| Combined paper, no CSV | Merged (#17) | `feat/ocr-combined-paper` | One scanned PDF per sitting (Part A quiz + Part B test), 20-row cover page, typed EL marks, CSV upload removed; decisions M1-M6 |
| Scan review fixes | PR open | `fix/scan-review-save` | Save bar kept in view on the scan review; Bloom field re-read so no question line is dropped |

## Pending

**Needs action**
- [x] `feat/ui-motion`: `main` merged in (conflicts in `Shell.tsx` and `RootCauseTab.tsx`), web
  build and API tests pass, PR opened.
- [x] `feat/landing-page`: committed, `feat/ui-motion` merged in, copy updated for the rescope,
  PR opened after the UI-motion PR.
- [x] Regenerate [docs/test-report.md](docs/test-report.md): done 23 Nov 2026, 166 passed (was
  the first run, 84 tests).

**Needs a decision** (open questions in the PRD)
- [ ] Final report: format and template from the course.
- [ ] OCR accuracy target: what share of marks must be read correctly before the teacher's review?
- [ ] A sample (blank or synthetic) question paper and answer-sheet cover page, so the OCR matches
  the college layout.
- [x] Who owns the Google Cloud project: Krrish's personal Google account (decided 23 Nov 2026).
- [ ] Create the Google Cloud project and put its OAuth client in `.env` (README: Google Forms setup).
- [ ] Early-warning target: what recall and precision? The cut-off is 0.5 (decided); at 0.5 after
  CIE Test 1, recall is 35 % and precision 78 %, at 0.3 69 % and 61 %
  ([docs/early-warning-evaluation.md](docs/early-warning-evaluation.md)).
- [ ] Course-file PDF: which sections, and does the college have a template?

**Later (deferred on purpose)**
- [ ] NLP on survey comments ([nlp.md](nlp.md)).
- [ ] Per-course component weights: add a nullable `course_id` to `config_component_weight`. This is
  a data and lookup change only; v1 uses one scheme for every course.
- [ ] Real course catalogue (course titles, CO statements, CO-PO mappings). The demo values are
  invented; real student marks must never be committed.
- [ ] SAP / ERP export of results: out of scope for v1.
- [ ] Housekeeping: the Starlette test client shows an `anyio` deprecation warning (harmless).

## Stack (as built)

| Layer | Choice |
| --- | --- |
| Relational DB | PostgreSQL 16 (PL/pgSQL, RLS, materialized views, recursive CTEs) |
| NoSQL DB | MongoDB 8 (survey responses, hash-chained audit log) |
| Backend | Python 3.11, FastAPI, psycopg 3 + pool, pymongo, bcrypt, PyJWT |
| Frontend | React 18 + TypeScript (Vite), taste-skill `charts.js` |
| Jobs | APScheduler (nightly ETL, audit writer, verifier, daily anchor) |
| Test data | Python generator (Faker + NumPy), fixed seed |
| Tests | pytest (API + SQL) against `copo_test`, SQL fixture for the worked example |

## Repository layout (as built)

```
db/
  migrations/        001_schema … 012_early_warning (tables, triggers, views, procedures, indexes, RLS)
  seed/              worked-example fixture (Section 5 of PRD)
api/                 FastAPI app (routers, services, mongo, jobs)
web/                 React + TypeScript app
datagen/             synthetic data generator and root-cause scenario
scripts/             setup_db, migrate, demo, explain_report, evaluate_root_cause
tests/               pytest suites, grouped by PRD test
docs/                ER diagram, EXPLAIN ANALYZE report, root-cause evaluation, test report
```

## Decisions (2 Nov 2026)

Settled in PRD Section 10; the phases below already apply them.

| # | Decision |
| --- | --- |
| S1 | Weights stored as percentages: `direct_weight + indirect_weight = 100`; final = `(dw × direct + iw × indirect) / 100` |
| S5 | CIE/SEE by weighted marks, one direct level per CO. Final mark = (CIE 100 + SEE 100) / 2, so component weights are CIE theory 20, CIE quiz 10, EL 20, SEE 50 |
| S5 | Same scheme for every course in v1; per-course schemes later (keep the weights in data so this is a data change, not a code change) |
| S6 | Absent student scores 0 |
| S10 | Programme-level PO = plain average of offering-level PO values |
| S11 | Student role included, limited to own rows by RLS |
| RC | Root-cause depth penalty: path strength × 0.8 for each level beyond the first (`rc_depth_decay`); see [docs/root-cause-evaluation.md](docs/root-cause-evaluation.md) |

## Decisions (23 Nov 2026) — rescope

Recorded in PRD Section 10 as R1–R8; phases 7–10 below apply them.

| # | Decision |
| --- | --- |
| R1 | Purpose: automate teachers' CO-PO work. Accreditation reports (NBA SAR / NAAC SSR) are not a goal |
| R2 | Novelties: answer-sheet OCR, early-warning prediction, root-cause analysis. What-if, versioned rules and the audit log stay as supporting features |
| R3 | The coordinator role is called Programme coordinator; same rights (`copo_coordinator`) |
| R4 | Surveys are real Google Forms created through the Forms API, shared with a WhatsApp share button (no paid sending) |
| R5 | The form asks college email, USN, name and phone; these match the student, then only a hashed USN is stored |
| R6 | OCR: one PDF per assessment (page 1 question paper, then each student's cover-page marks table); free local OCR; the teacher confirms every value. Superseded by M2: one PDF per sitting |
| R7 | Early warning: logistic regression trained on earlier offerings, re-run after each locked CIE |
| R8 | Course file is generated as a PDF |

## Decisions (23 Nov 2026) — marks entry and the combined question paper

| # | Decision |
| --- | --- |
| M1 | The CSV marks upload (upload endpoint, template endpoint, buttons) is removed. CIE tests, quizzes and the SEE are entered by scanning; experiential learning is typed in the app. One validated save path (`api/services/marks.py`) serves both |
| M2 | One scanned PDF per sitting, picked by the teacher: CIE 1, CIE 2 or SEE. A CIE paper has "Part A - Quiz" and "Part B - Test" headings, numbered on across parts; an SEE paper has no Part A |
| M3 | The cover page has 20 mark rows (two columns of ten); every sheet carries the marks of both parts, each in the row of its paper number |
| M4 | CIE n fills `Quiz n` (Part A, CIE_QUIZ) and `CIE Test n` (Part B, CIE_THEORY); the SEE fills `SEE`. A missing assessment is created from the paper with max marks = the part's sum. Within each assessment the questions are renumbered from Q1 in paper order (chosen over keeping the paper numbers, so every assessment reads Q1.. as the demo data and typed marks do) |
| M5 | EL marks are typed into a per-student table (`PUT /api/assessments/{id}/marks`, all or nothing, row errors returned); an EL assessment is added on the Marks tab with its questions |
| M6 | Confirming scanned marks only saves them; locking and computing stay separate, manual steps |

## Phase 1 — Schema and constraints (week 1) · Member A · ✅ done

Output: approved ER diagram and DDL.

1. ER diagram in `docs/` covering the 25 PRD tables plus the additions below.
2. `db/migrations/001_schema.sql` — all tables with PKs and FKs (FR-1.x, FR-2.x, FR-3.1, FR-4.1).
3. Single-table CHECKs in `001_schema.sql`: CO-PO and dependency strength 1–3; marks ≥ 0;
   `direct_weight + indirect_weight = 100` (NFR-1, S1); range domains for percentages and levels.
   Rules that need another table — marks ≤ the question maximum and the component-weight sum —
   are triggers and ship with Phase 3 (`002_integrity.sql`).
4. Schema additions from the PRD:
   - `attainment_config`: `co_target_level`, `po_target_level` (S2).
   - `config_component_weight (config_id FK, component, weight_pct)`; the deferred trigger that the
     weights of one config sum to 100 ships in Phase 3. v1 seed: `CIE_THEORY` 20, `CIE_QUIZ` 10,
     `EL` 20, `SEE` 50 (S5).
     A nullable `course_id` can be added later for per-course schemes.
   - `assessment.type` restricted to those four components; several assessments of one type (e.g. two
     CIE theory tests) are pooled within the component.
   - `student_question_mark`: `is_absent` flag, `marks_obtained` nullable when absent; scored as 0 (S6).
   - `app_user`: nullable `usn` FK for student logins; CHECK that faculty users have `faculty_id` and
     student users have `usn` (S11).
   - `whatif_scenario`: split `direct_weight` / `indirect_weight`, add `co_target_level` (S4).
   - `whatif_po_result (scenario_id, po_id, attainment)` (S3).
   - `unlock_request (request_id, assessment_id, requested_by, approved_by, reason, ts)` (S7).
   - `audit_outbox` (S8).
5. Unique constraints: `enrollment (offering_id, usn)`; `co_po_map (co_id, po_id)`.

## Phase 2 — Synthetic data (week 2) · Member B · ✅ done

Output: database with 500k+ mark rows.

1. `datagen/` produces departments → programmes → courses (with prerequisites) → offerings over
   3+ academic years → students, enrolments, assessments, questions, marks. Each offering gets CIE
   theory tests, quizzes, an EL assessment and a SEE; a small share of absences.
2. Planted weakness: one upstream CO lowered for a cohort, the dependent CO lowered for the same
   students, plus an unrelated decoy CO (for the FR-6.2 tests).
3. Survey documents into MongoDB with `respondent_hash`, one per (respondent, offering, survey_type) (S12).
4. Deterministic seed so test runs are reproducible.
5. `db/seed/worked_example.sql` — the exact 60-student, 3-CO case from PRD Section 5.

## Phase 3 — Attainment engine (weeks 3–4) · Member A · ✅ done

Output: engine that matches the worked example to two decimals.

1. Trigger `mark_guard` (`trg_check_mark`): reject marks outside 0..max and any write to a locked
   assessment; emit an audit row (FR-3.3, FR-3.5).
2. Deferred constraint trigger: per-question CO weights sum to 1 (FR-3.2).
3. Trigger on `co_dependency`: reject cycles and prereq COs outside the course-prerequisite graph (FR-2.3, S9).
4. Views for the student CO score (PRD Section 5, steps 1–2):
   - `student_component_co_pct` — per (usn, offering, CO, component): weighted marks ÷ weighted max
     × 100, absent marks counted as 0.
   - `student_co_score` — Σ(weight_pct × component %) ÷ Σ weight_pct over the components that test the
     CO, weights from `config_component_weight`.
5. `sp_compute_attainment(p_offering_id, p_config_id, p_persist)`:
   1. `SELECT ... FOR UPDATE` on the offering (NFR-3).
   2. Raise if any assessment is unlocked (FR-4.3).
   3. Direct level per CO from config thresholds.
   4. Indirect level from `indirect_attainment.pct_favourable` with the same thresholds (0 if no
      survey), so a what-if scenario's thresholds apply to it too.
   5. Final level = `(direct_weight × direct + indirect_weight × indirect) / 100`.
   6. PO per offering from `co_po_map` strengths.
   7. `p_persist` → write `co_attainment` / `po_attainment` and refresh views; else write
      `whatif_result` / `whatif_po_result` only (NFR-8).
   8. Insert `improvement_action` for each CO below `co_target_level` (FR-4.4).
6. Programme-level PO = plain average of offering-level PO values (FR-4.5).
7. Indexes: `student_question_mark(question_id)`, `question_co_map(co_id)` and FK-join indexes;
   `enrollment(offering_id)` is already covered by the UNIQUE `(offering_id, usn)` index. Record
   EXPLAIN ANALYZE before/after in `docs/explain/report.md` (NFR-7).
8. Tests: worked example → CO 3.00 / 2.20 / 0.40, PO1 2.30, PO2 1.48; component weighting → a student
   at 70 / 80 / 90 / 60 % (theory / quiz / EL / SEE) scores 70.0%, and 68.9% when no quiz question
   tests the CO.

## Phase 4 — MongoDB, ETL and audit chain (week 5) · Member B · ✅ done

Output: integrated NoSQL layer.

1. Collections `survey_responses` (unique index per S12) and `audit_log`.
2. API reference checks: `offering_id`, `co_id` must exist in PostgreSQL before a survey insert (FR-5.1).
3. Nightly ETL: % rating ≥ the rule version's `favourable_rating` (default 4) per (offering, CO) →
   upsert `indirect_attainment`; the engine derives the level from that % (FR-5.2). Groups without
   responses are removed, and offerings with official results whose survey input changed are
   recomputed.
4. Audit: DB triggers write to `audit_outbox` in the same transaction; a worker moves rows to
   `audit_log` with `hash = SHA256(prev_hash + canonical JSON)` and marks them sent (S8).
5. Daily job copies the chain head into `audit_anchor`; verifier recomputes the chain and reports the
   first broken `seq` (FR-7.2, NFR-6).

## Phase 5 — Innovation features (week 6) · Member A (SQL), Member B (API) · ✅ done

Output: root-cause report, what-if simulator, versioned rules.

1. Root-cause query: recursive CTE over `co_dependency` to depth 3, `corr()` on `student_co_score`
   for the same students, rank by `path_strength × r`; `n` and `r` thresholds from config (FR-6.2).
2. Pre-fill an `improvement_action` from the top-ranked cause; UI labels output as correlational.
3. What-if API: create `whatif_scenario`, call the procedure with `p_persist = false`, return CO and
   PO baseline vs scenario (FR-6.3).
4. Versioned rules: lookup of the config valid for an offering's academic year; re-run test (NFR-4).

## Phase 6 — API, UI, security, demo (week 7) · Member B (UI), both (tests) · ✅ done except step 5's final report

Output: demo-ready system.

1. Auth: bcrypt hashes in `app_user`; each request sets `app.faculty_id` (faculty) or `app.usn`
   (student) (FR-7.1).
2. PostgreSQL roles (admin, faculty, coordinator, student) with GRANTs; RLS policies on marks,
   attainment and survey-derived tables (NFR-5). Student policy: own `enrollment` rows only, read-only;
   student screen shows own CO-wise scores.
3. Screens: marks entry with row errors (CSV upload until 23 Nov 2026; now scanned sheets and typed
   EL marks, see Phase 7), lock/unlock request, compute, CO-PO heatmap, CO trend,
   weakest-CO ranking, root-cause report, what-if side-by-side, audit verification.
4. Run the full PRD Section 8 test suite; record results in `docs/test-report.md`. ✅
5. Demo script (`scripts/demo.py`) ✅ and final report (pending, see [Pending](#pending)).

## Phase 7 — Answer-sheet OCR (novelty)

Status: built on `feat/answer-sheet-ocr` (merged, #12); reworked on `feat/ocr-combined-paper` for
one PDF per sitting with both parts (decisions M1-M6 above). 18 tests; accuracy in
[docs/ocr-evaluation.md](docs/ocr-evaluation.md).

Output: a teacher uploads one PDF and gets the question paper and every student's marks, ready to
confirm. FR-3.7–3.9, NFR-10.

1. Upload endpoint for one PDF per sitting (CIE 1, CIE 2 or SEE, picked by the teacher); split it
   into page images (local, no outside service).
2. Page 1 (question paper, printed): OCR with Tesseract, parse each question's number, max marks,
   CO and Bloom level into draft `assessment_question` and `question_co_map` rows
   (`api/ocr/paper.py`). The page is enlarged and binarised first, and the short codes at the end
   of each line are taken by position and repaired for OCR confusions (i/l/I for 1, O for 0).
   A question line whose Bloom field does not parse (Tesseract can read a clear "L1" as "14"
   inside the line) has that one word read again on its own, so the question is not dropped.
   A CIE paper holds both parts: questions under a "Part A - Quiz" heading and under a "Part B -
   Test" heading (numbered on across parts) are tagged with their part; the heading is matched
   loosely ("PartA", "Part A: Quiz", "Part 8").
3. Pages 2+ (answer-sheet cover pages): locate the printed marks table, read the USN and each
   handwritten per-question mark with a handwritten-digit model; keep a confidence per value.
   The model is an MLP trained on MNIST's first 60,000 digits (`scripts/train_digits.py`,
   98.2 % on the 10,000 held-out digits); the cover-page layout is in `api/ocr/layout.py`:
   20 mark rows (Q1-Q10 and Q11-Q20 in two columns), one per question number on the paper, and
   only the rows of the paper's questions are read.
   The corner squares straighten each scan (`api/ocr/sheet.py`). Values are not read digit by
   digit but chosen (`api/ocr/reader.py`): each mark is the value 0..its maximum that best explains
   the digit probabilities, and USNs are paired with enrolled students so that the whole PDF has the
   highest likelihood and no student gets two sheets (Hungarian algorithm). A value's confidence is
   its share of the probability; the total written on the sheet is checked against the sum.
4. Review screen: every value side by side with its image crop, low-confidence values highlighted;
   it scrolls into view when the scan finishes, and its Save bar (with the "I have checked" box
   and the reason Save is disabled) stays at the bottom of the screen however long the review is;
   nothing is written to the official tables until the teacher confirms. Confirmed marks go through
   the existing validation, triggers and locking. API (`api/routers/ocr.py`): `POST
   /api/offerings/{id}/scan?sitting=CIE1|CIE2|SEE` reads the PDF and returns suggestions only: the
   questions with their part and number within their assessment, both parts' marks per sheet, the
   students without a sheet and which assessments will be created or filled. `POST
   /api/offerings/{id}/scan/confirm` saves in one transaction: it creates a missing `Quiz n`, `CIE
   Test n` or `SEE` (max marks = its part's sum), saves each part's questions renumbered from Q1
   (replaced while no marks exist, only retagged after; equal CO weights; `api/services/questions.py`),
   then the marks through `api/services/marks.py`, with AB for students without a sheet who have
   no marks yet (or all of them, if the teacher opts in). Saving does not lock or compute. The PDF
   and page images are not stored. Experiential-learning marks are typed instead (`PUT
   /api/assessments/{id}/marks`, EL only); the CSV upload was removed.
5. Synthetic test PDFs (typed question paper, handwritten-style marks) generated with known values
   by `datagen/ocr_samples.py`, using MNIST's 10,000 held-out digits as handwriting; accuracy is
   reported against the target still to be agreed. `scripts/evaluate_ocr.py` writes
   [docs/ocr-evaluation.md](docs/ocr-evaluation.md): on 240 synthetic sheets of a CIE sitting (quiz Q1-Q5 and test Q6-Q11 on one
   paper), question papers and parts read exactly, 99.1 % of marks and 100 % of USNs right, and no
   wrong value left unflagged.

## Phase 8 — Google Forms surveys and WhatsApp sharing

Status: built on `feat/google-forms-surveys` (PR open); 7 tests with Google faked. Live use waits
for the Google Cloud project (README: Google Forms surveys).
Decided 23 Nov 2026: the Google Cloud project is on Krrish's personal account (OAuth consent
screen in Testing), each teacher connects their own Google account, responses come in by a
Fetch button and a nightly job.

Output: a teacher clicks once to create the course-exit survey and once to share it. FR-5.1, 5.3–5.5.

1. Google Cloud project + OAuth consent screen (README: Google Forms setup); each teacher connects
   their own account (`/api/google/*`); the refresh token is stored encrypted (Fernet) in
   `google_account`, visible only to its owner (migration 011).
2. Create a form per offering: college email, USN, name, phone, then one 1–5 rating per CO.
3. WhatsApp share button: a `wa.me` link with the form link and a prefilled message.
4. Pull responses through the Forms API; accept only enrolled USNs with a college email, one per
   student; store a hashed USN only (name and phone dropped) in `survey_responses`; the existing
   ETL turns them into indirect attainment.
5. Dashboard: response rate, rating distribution per CO, count yet to respond.
6. Nightly `forms` job at 01:15 (before the 01:30 ETL) fetches every form with its owner's
   connection. Code: `api/google/client.py`, `api/services/survey_forms.py`,
   `api/routers/survey_forms.py`; tests: `tests/test_survey_forms.py` (Google faked).

## Phase 9 — Weak-student lists and early warning (novelty)

Status: built on `feat/early-warning` (PR open); 6 tests; replayed on 2025-26 in
[docs/early-warning-evaluation.md](docs/early-warning-evaluation.md).

Output: teachers see which students need help, during the term. FR-6.4, FR-6.5.

1. Weak-student list per CO: students whose CO score is below `target_pct`, from `student_co_score`
   (`GET /api/offerings/{id}/students`, which also returns the latest early warning).
2. Early warning: logistic regression on the CIE components available so far, trained on
   earlier offerings of the synthetic data; re-run after each locked CIE.
   As built (`api/services/early_warning.py`): the "stage" is the locked CIE, quiz and EL
   assessments (by type and order); training uses earlier finished offerings of the same course
   with the same assessments, labelled by whether the student missed the CO's target at the end.
   Features: CO marks so far, and the student's final scores on prerequisite COs (the root-cause
   links). The whole-stage score was dropped as a feature: it overlaps the CO score and took the
   wrong sign. The flag cut-off is `attainment_config.ew_flag_prob` (default 0.5). Training runs on
   the owner connection (it reads other teachers' finished offerings); only the model leaves it.
   About 0.5 s per run on the demo data. Locking a CIE, quiz or EL re-runs it (best effort).
3. Show each flagged student with the CO, the predicted chance and the marks that drove the flag.
   Advisory only; it never changes official attainment.
4. Evaluate on held-out offerings after CIE-1 and CIE-2 against the recall/precision target still
   to be agreed. `scripts/evaluate_early_warning.py` replays the 64 finished 2025-26 offerings
   ([docs/early-warning-evaluation.md](docs/early-warning-evaluation.md)): AUC 0.79 after CIE Test 1
   and 0.94 after both tests and quizzes; at the 0.5 cut-off, 78 % of flags are right but 35 % of
   the students who end below target are flagged after CIE Test 1 (69 % at a 0.3 cut-off).

## Phase 10 — Course-file PDF

Status: built on `feat/course-file` (PR open); 3 tests. Sections follow PRD FR-6.6 until the
college template (open question) is known; only `render` would change.

Output: a PDF course file per offering. FR-6.6.

1. Sections (to confirm, or a college template): CO and PO attainment tables, charts, weak COs,
   root-cause findings, improvement actions. As built (`api/services/course_file.py`, drawn with
   PyMuPDF, no new dependency): rules used, assessments, CO attainment table and chart, course-exit
   survey, PO attainment table and chart, COs below target with students below target and likely
   upstream causes, improvement actions; page numbers, headers repeat across pages.
   `GET /api/offerings/{id}/course-file.pdf` (any staff role that can see the offering).
2. Every number comes from the database; a test checks the worked-example offering's PDF against it
   (`tests/test_course_file.py`).

## As built vs plan (2 Nov 2026)

Where the build differs from the plan above:

| Area | Plan | As built | Why |
| --- | --- | --- | --- |
| Migration files | `002_constraints.sql`, separate `functions/` and `views/` folders | CHECKs in `001_schema.sql`; triggers in `002_integrity.sql`; views, procedures and RLS in numbered migrations 003–009 | one ordered list to apply, reset and test against |
| Rule-version lookup | join configs by date range | `LATERAL … LIMIT 1` in `v_offering_config` | the planner misestimated the range join and chose nested loops (root-cause query 855 ms → 26 ms) |
| Indexes | include `enrollment(offering_id)` | dropped | already covered by UNIQUE `(offering_id, usn)`; see `docs/explain/report.md` |
| RLS policies | per-row ownership functions | `col IN (SELECT fn_my_x())` set-returning helpers | evaluated once per query; student surveys 7.5 s → 0.05 s |
| Audit capture | `pg_notify` listener | transactional outbox (S8) + `pg_notify` wake-up | no change is lost when MongoDB or the writer is down |
| Course prerequisites | — | acyclic-graph trigger | keeps the CO-dependency check meaningful |
| UI | React + charting library | React + taste-skill `charts.js`, style `framed-sheet` | follows the taste-skill app-screen rules |
| OCR drafts | tables for OCR uploads and draft values | no new tables: the read PDF returns suggestions, the browser holds them until the teacher confirms | scans are never stored on the server; confirmed values reuse the question and marks paths and their audit |
| Marks entry | CSV upload per assessment | scanned sheets per sitting (CIE, SEE) and a typed table for EL; no CSV (M1) | teachers scan anyway; a second hand-made path only added work and errors |
| OCR unit of upload | one PDF per assessment | one PDF per sitting: the quiz and the test of a CIE share a paper and a cover page (M2-M4) | the quiz and the test are sat together; one scan instead of two |
| Assessment max marks | set when the assessment is created | follows the sum of its questions while no marks exist | lock needs them equal; the paper is the source of the maxima |
| OCR question data | question number, max marks, CO, Bloom level | adds `assessment_question.bloom_level` (migration 010) | the Bloom level was stored only per CO |
| OCR USN on the cover page | read the USN | boxes for the year and roll digits only; matched to enrolled USNs | reading handwritten branch letters needs a letter model; the digits identify a student within one offering |
| Course-file fonts | built-in PDF fonts | FiraGO (pymupdf-fonts, open licence) embedded and subset; characters it lacks shown as `?` | base-14 fonts garble symbols and non-Latin text (review of #15) |
| Early-warning features | CIE components so far | CO marks so far and prerequisite-CO scores; one model per course and stage, trained on the owner connection | the whole-stage score overlapped the CO score and took the wrong sign, which made reasons contradictory |
| Early-warning trigger | after each locked CIE | after each lock that changed a CIE, quiz or EL, as a background task once the response is sent; saves of one offering serialised by an advisory lock; also a Run button | a failed prediction must never undo a lock; re-locking must not retrain; concurrent runs must not collide (review of #14) |
| Survey sharing | WhatsApp share button | a `wa.me` link with the form link and a message filled in | free and needs no WhatsApp API; the teacher picks the group |
| Survey responses | Forms API reference checks | the form collects Google-verified emails; every response must come from the email on record for its USN (`student.email`), then goes through the in-app survey checks; only counts are kept about a fetch | a typed email let anyone answer as a classmate (review of #13); email, name and phone never stored |
| Google sign-in | signed state | signed state plus a nonce cookie of the browser that started it; creation under a per-offering lock, a half-made form deleted (`drive.file`) | OAuth login CSRF and orphan forms (review of #13) |
| OCR review threshold | setting | `attainment_config.ocr_review_confidence` (default 0.90, migration 010) | thresholds are data in the rules, not `.env` (review of #12) |
| OCR pairing and saving | rows by position; every student without a sheet saved as AB | rows by question number; unreadable pages typed in or skipped; AB only for students with no marks yet unless the teacher opts in | a missing question line shifted marks; a second PDF of the same class overwrote the first (review of #12) |
| OCR value choice | read digit by digit | marks chosen within 0..max, USNs paired across the PDF (Hungarian algorithm) | uses what is known about the paper and the class; on 240 synthetic sheets no wrong value went unflagged |

## Test map

Results of the last run: [docs/test-report.md](docs/test-report.md).

| PRD test | Location |
| --- | --- |
| Correctness | `tests/test_worked_example.py`, `tests/test_component_weights.py` |
| Constraints | `tests/test_constraints.py` |
| Access control | `tests/test_rls.py` (faculty A vs B; student sees only own rows), `tests/test_api.py` |
| Audit tamper | `tests/test_audit_chain.py` |
| Performance | `docs/explain/` reports |
| Root cause | `tests/test_root_cause.py` |
| Simulator isolation | `tests/test_whatif_isolation.py` |
| Concurrency | `tests/test_concurrency.py` |
| Reproducibility | `tests/test_versioned_rules.py` |
| Surveys and ETL | `tests/test_surveys_etl.py` |
| Answer-sheet OCR | `tests/test_ocr.py`; accuracy in `docs/ocr-evaluation.md` |
| Google Forms surveys | `tests/test_survey_forms.py` |
| Weak students, early warning | `tests/test_early_warning.py`; replay in `docs/early-warning-evaluation.md` |
| Course file | `tests/test_course_file.py` |
