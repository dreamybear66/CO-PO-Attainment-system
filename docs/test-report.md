# Test report

Run on 2 Nov 2026: `python -m pytest`, PostgreSQL 16.15, MongoDB 8.0.6, Python 3.11.
**84 passed, 0 failed** in 66 s. The one warning is a Starlette deprecation in the test client.

## PRD Section 8 tests

| PRD test | Tests | Result | What it shows |
| --- | ---: | --- | --- |
| Correctness | 13 | pass | Worked example gives CO 3.00 / 2.20 / 0.40, PO1 2.30, PO2 1.48. Component weights: 70 / 80 / 90 / 60 % gives 70.0 %, and 68.9 % without a quiz question on the CO. Absent counts as 0. |
| Constraints | 23 | pass | Marks outside 0..max, edits/deletes/inserts on locked assessments, question weights ≠ 1, component weights ≠ 100, strengths outside 1–3, cross-course and cross-programme mappings, prerequisite cycles, lock with missing marks, unlock without an approved request: all rejected with their own SQLSTATE. |
| Access control | 18 | pass | Faculty B sees and changes none of faculty A's rows and cannot compute or analyse A's offerings. Coordinator reads everything and writes nothing. Students see only their own marks and scores. Password hashes and dashboard views are hidden. The API login alone reads nothing. API checks cover login, CSV upload, lock, unlock approval and student pages. |
| Audit tamper | 7 | pass | Edited, deleted or rewritten audit documents are reported with the first broken `seq`. The writer recovers without duplicates. Refused edits are recorded as `DENIED`. |
| Performance | — | see report | `docs/explain/report.md`: the 006 indexes make the per-CO path 2.2× faster (185 → 83 ms). The per-offering computation already uses constraint indexes. |
| Root cause | 6 | pass | Planted cause ranks first and the decoy is excluded; random data gives no cause; small cohorts are not reported. Detection rates by cohort size and effect are in `docs/root-cause-evaluation.md`. |
| Simulator isolation | 4 | pass | What-if runs leave official tables unchanged, show which POs cross the target, and cannot be persisted. |
| Concurrency | 2 | pass | A second compute on the same offering waits or is refused; a failed run leaves the previous results. |
| Reproducibility | 4 | pass | Re-running with the old rule version reproduces the old numbers; later rule changes do not alter past results; versions cannot overlap. |
| Surveys and ETL | 7 | pass | Reference checks against PostgreSQL, one response per student, hashed respondent, idempotent ETL feeding the engine. |

Correctness = `test_worked_example.py` (9) + `test_component_weights.py` (4). Access control = `test_rls.py` (9) + `test_api.py` (9).

## Demo data run

`python -m scripts.demo`: 556,800 marks, 11,965 surveys, 248 offerings computed, 573,223 audit records chained, anchored and verified intact.

## Open

Root-cause ranking does not penalise depth when every link has strength 3. In 20–40 student cohorts a depth-2 ancestor sometimes outranks the direct cause. See `docs/root-cause-evaluation.md`; this is waiting on a decision.
