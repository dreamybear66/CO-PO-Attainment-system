# Implementation Plan

How the CO-PO Attainment Management System gets built. Requirement IDs (FR-x, NFR-x) and suggested
changes (S1–S13) refer to the [PRD](https://claude.ai/artifact/G8HdvxVTjQ47XZ6AeEhard).

## Progress (2 Nov 2026)

All six phases are built. 84 tests pass ([docs/test-report.md](docs/test-report.md)).

| Phase | Status | Branch · PR | Output |
| --- | --- | --- | --- |
| Planning | Merged | `docs/project-planning` · #1 | PRD, this plan, CLAUDE.md |
| 1 — Schema and constraints | Merged | `feat/schema` · #2 | 29 tables, ER diagram, CHECK/EXCLUDE constraints |
| 2 — Synthetic data | Merged | `feat/datagen` · #3 | 556,800 marks, 1,440 students, 280 offerings, worked-example fixture |
| 3 — Attainment engine | Merged | `feat/attainment-engine` · #4 | Triggers, `sp_compute_attainment`, matches the worked example exactly |
| 4 — MongoDB, ETL, audit | PR open | `feat/mongo-audit` · #5 | 11,965 surveys, ETL, 573,223 audit records chained and verified |
| 5 — Innovation features | PR open | `feat/innovation` · #6 | Root cause (planted cause ranks 1st, decoy excluded), what-if, versioned rules |
| 6 — API, UI, security | PR open | `feat/web-app` · #7 | RLS on 17 tables, FastAPI, React app, demo script, test report |

## Pending

**Needs action**
- [ ] Merge PRs #5 → #6 → #7 in order. PR #5 still targets `feat/attainment-engine`, which is
  already merged, so first retarget it with `gh pr edit 5 --base main`. After each merge, retarget
  the next PR to `main` the same way.

**Needs a decision**
- [ ] Root-cause depth penalty. When every link has strength 3, path strength does not penalise
  depth, so in 20–40 student cohorts a depth-2 ancestor sometimes outranks the direct cause.
  Options: break ties by depth, decay 0.8 per extra level, or keep the PRD formula
  ([docs/root-cause-evaluation.md](docs/root-cause-evaluation.md)).
- [ ] Final report (Phase 6, step 5): format and template from the course.
- [ ] Which NBA / NAAC criteria the report and PRD should cite.

**Later (deferred on purpose)**
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
  migrations/        001_schema … 009_security (tables, triggers, views, procedures, indexes, RLS)
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
