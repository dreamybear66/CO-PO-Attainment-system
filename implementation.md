# Implementation Plan

How the CO-PO Attainment Management System gets built. Requirement IDs (FR-x, NFR-x) and suggested
changes (S1–S13) refer to the [PRD](https://claude.ai/artifact/G8HdvxVTjQ47XZ6AeEhard).

## Progress (23 Nov 2026)

Phases 1–6 are built and merged; phase 7 is built (PR open); 176 tests pass. On 23 Nov 2026 the project was rescoped from
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
| 8 — Google Forms surveys | Not started | — | See [Phase 8](#phase-8--google-forms-surveys-and-whatsapp-sharing) |
| 9 — Weak students, early warning | Not started | — | See [Phase 9](#phase-9--weak-student-lists-and-early-warning-novelty) |
| 10 — Course-file PDF | Not started | — | See [Phase 10](#phase-10--course-file-pdf) |

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
- [ ] Who owns the Google Cloud project and OAuth consent screen for the Forms API?
- [ ] Early-warning target: what recall and precision, and what predicted chance flags a student?
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
  migrations/        001_schema … 010_question_bloom (tables, triggers, views, procedures, indexes, RLS)
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
| R6 | OCR: one PDF per assessment (page 1 question paper, then each student's cover-page marks table); free local OCR; the teacher confirms every value |
| R7 | Early warning: logistic regression trained on earlier offerings, re-run after each locked CIE |
| R8 | Course file is generated as a PDF |

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
3. Screens: CSV marks upload with row errors, lock/unlock request, compute, CO-PO heatmap, CO trend,
   weakest-CO ranking, root-cause report, what-if side-by-side, audit verification.
4. Run the full PRD Section 8 test suite; record results in `docs/test-report.md`. ✅
5. Demo script (`scripts/demo.py`) ✅ and final report (pending, see [Pending](#pending)).

## Phase 7 — Answer-sheet OCR (novelty)

Status: built on `feat/answer-sheet-ocr` (PR open). 10 tests; accuracy in
[docs/ocr-evaluation.md](docs/ocr-evaluation.md).

Output: a teacher uploads one PDF and gets the question paper and every student's marks, ready to
confirm. FR-3.7–3.9, NFR-10.

1. Upload endpoint for one PDF per assessment; split it into page images (local, no outside service).
2. Page 1 (question paper, printed): OCR with Tesseract, parse each question's number, max marks,
   CO and Bloom level into draft `assessment_question` and `question_co_map` rows
   (`api/ocr/paper.py`). The page is enlarged and binarised first, and the short codes at the end
   of each line are taken by position and repaired for OCR confusions (i/l/I for 1, O for 0).
3. Pages 2+ (answer-sheet cover pages): locate the printed marks table, read the USN and each
   handwritten per-question mark with a handwritten-digit model; keep a confidence per value.
   The model is an MLP trained on MNIST's first 60,000 digits (`scripts/train_digits.py`,
   98.2 % on the 10,000 held-out digits); the cover-page layout is in `api/ocr/layout.py`.
   The corner squares straighten each scan (`api/ocr/sheet.py`). Values are not read digit by
   digit but chosen (`api/ocr/reader.py`): each mark is the value 0..its maximum that best explains
   the digit probabilities, and USNs are paired with enrolled students so that the whole PDF has the
   highest likelihood and no student gets two sheets (Hungarian algorithm). A value's confidence is
   its share of the probability; the total written on the sheet is checked against the sum.
4. Review screen: every value side by side with its image crop, low-confidence values highlighted;
   nothing is written to the official tables until the teacher confirms. Confirmed marks go through
   the existing validation, triggers and locking. API (`api/routers/ocr.py`): `POST
   /api/assessments/{id}/ocr` reads the PDF and returns suggestions only; `PUT
   /api/assessments/{id}/questions` saves the confirmed questions (replaced while no marks exist,
   only retagged after), with equal CO weights; confirmed marks go to the existing CSV endpoint.
   The PDF and page images are not stored.
5. Synthetic test PDFs (typed question paper, handwritten-style marks) generated with known values
   by `datagen/ocr_samples.py`, using MNIST's 10,000 held-out digits as handwriting; accuracy is
   reported against the target still to be agreed. `scripts/evaluate_ocr.py` writes
   [docs/ocr-evaluation.md](docs/ocr-evaluation.md): on 240 synthetic sheets, question papers read
   exactly, 97.6-97.8 % of marks and 100 % of USNs right, and no wrong value left unflagged.

## Phase 8 — Google Forms surveys and WhatsApp sharing

Status: not started.

Output: a teacher clicks once to create the course-exit survey and once to share it. FR-5.1, 5.3–5.5.

1. Google Cloud project + OAuth consent screen (owner to be decided); store the teacher's token.
2. Create a form per offering: college email, USN, name, phone, then one 1–5 rating per CO.
3. WhatsApp share button: a `wa.me` link with the form link and a prefilled message.
4. Pull responses through the Forms API; accept only enrolled USNs with a college email, one per
   student; store a hashed USN only (name and phone dropped) in `survey_responses`; the existing
   ETL turns them into indirect attainment.
5. Dashboard: response rate, rating distribution per CO, count yet to respond.

## Phase 9 — Weak-student lists and early warning (novelty)

Status: not started.

Output: teachers see which students need help, during the term. FR-6.4, FR-6.5.

1. Weak-student list per CO: students whose CO score is below `target_pct`, from `student_co_score`.
2. Early warning: logistic regression per CO on the CIE components available so far, trained on
   earlier offerings of the synthetic data; re-run after each locked CIE.
3. Show each flagged student with the CO, the predicted chance and the marks that drove the flag.
   Advisory only; it never changes official attainment.
4. Evaluate on held-out offerings after CIE-1 and CIE-2 against the recall/precision target still
   to be agreed.

## Phase 10 — Course-file PDF

Status: not started.

Output: a PDF course file per offering. FR-6.6.

1. Sections (to confirm, or a college template): CO and PO attainment tables, charts, weak COs,
   root-cause findings, improvement actions.
2. Every number comes from the database; a test checks the worked-example offering's PDF against it.

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
| OCR drafts | tables for OCR uploads and draft values | no new tables: the read PDF returns suggestions, the browser holds them until the teacher confirms | scans are never stored on the server; confirmed values reuse the question and CSV paths and their audit |
| OCR question data | question number, max marks, CO, Bloom level | adds `assessment_question.bloom_level` (migration 010) | the Bloom level was stored only per CO |
| OCR USN on the cover page | read the USN | boxes for the year and roll digits only; matched to enrolled USNs | reading handwritten branch letters needs a letter model; the digits identify a student within one offering |
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
