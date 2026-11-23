# Test report

Run on 23 Nov 2026: `python -m pytest`, PostgreSQL 16, MongoDB 8.0.6, Python 3.11, Tesseract 5.4.
**179 passed, 0 failed** (166 before phase 7, plus 13 for answer-sheet OCR); the run before OCR took 5 min 54 s. The one warning is a Starlette deprecation in the test
client.

## PRD Section 8 tests

| PRD test | Tests | Result | What it shows |
| --- | ---: | --- | --- |
| Correctness | 16 | pass | Worked example gives CO 3.00 / 2.20 / 0.40, PO1 2.30, PO2 1.48. Component weights: 70 / 80 / 90 / 60 % gives 70.0 %, and 68.9 % without a quiz question on the CO. Absent counts as 0. The level follows the stored percentage, and the view uses the offering's rule version. |
| Improvement actions | 5 | pass | A recompute closes the action of a CO now at target and updates the text of one still below it. Follow-ups link to the next offering of the same course and section within 18 months, whichever is computed first. |
| Constraints | 27 | pass | Marks outside 0..max, edits/deletes/inserts on locked assessments, question weights ≠ 1, component weights ≠ 100, strengths outside 1–3, cross-course and cross-programme mappings, prerequisite cycles, lock with missing marks, unlock without an approved request, duplicate enrolment: all rejected with their own SQLSTATE. |
| Access control | 27 | pass | Faculty B sees and changes none of faculty A's rows and cannot compute or analyse A's offerings. The Programme coordinator reads everything and writes nothing. Students see only their own marks and scores. Only the admin refreshes dashboards or computes everything, and setting `app.role` alone grants nothing. API checks cover login, CSV upload, lock, unlock approval, survey submission, audit verification and student pages. |
| Audit tamper | 16 | pass | Edited, deleted or rewritten audit documents are reported with the first broken `seq`, including deletion of the newest documents. The writer recovers without duplicates and stops rather than writing over a gap. Refused edits are recorded as `DENIED`. |
| Performance | — | see report | `docs/explain/report.md`: the 006 indexes make the per-CO path 2.2× faster (185 → 83 ms). The per-offering computation already uses constraint indexes. |
| Root cause | 15 | pass | Planted cause ranks first and the decoy is excluded; random data gives no cause; small cohorts are not reported; deeper levels are weighted down by `rc_depth_decay`. Detection rates by cohort size and effect are in `docs/root-cause-evaluation.md`. |
| Simulator isolation | 14 | pass | What-if runs leave official tables unchanged, show which POs cross the target, run on another rule version, and cannot be persisted. |
| Concurrency | 8 | pass | A second compute on the same offering waits or is refused; a failed run leaves the previous results; a lock waits for uncommitted mark edits; an unlock waits for a running compute; dashboards stay readable during a compute. |
| Reproducibility | 4 | pass | Re-running with the old rule version reproduces the old numbers; later rule changes do not alter past results; versions cannot overlap. |
| Surveys and ETL | 24 | pass | Reference checks against PostgreSQL, one response per student, keyed-hash respondent, malformed answers rejected, idempotent ETL that recomputes affected offerings. |
| Answer-sheet OCR | 13 | pass | Question lines are read through OCR confusions and unreadable lines are reported. Marks are chosen within each question's maximum and USNs among enrolled students. A synthetic 15-sheet PDF is read end to end: questions exact, every wrong value flagged for review; confirmed questions and marks are saved through the usual checks. Questions can only be retagged once marks exist; locked assessments, other faculty and non-PDFs are refused. Marks are taken from each question's own row even when a question line on page 1 is unreadable; an unreadable page gets one empty input per question; questions beyond Q10 are not offered; students with no sheet who already have marks are reported, not overwritten; the review threshold comes from the rule version. Needs Tesseract and the digit model. |
| Synthetic data | 10 | pass | Same seed gives the same data, the dataset has the planned size, the planted cause stands out and the decoy does not, every PO is mapped, one login per person. |

| PRD test | Files |
| --- | --- |
| Correctness | `test_worked_example.py` (12), `test_component_weights.py` (4) |
| Improvement actions | `test_improvement_actions.py` (5) |
| Access control | `test_rls.py` (9), `test_api.py` (14), `test_compute_access.py` (4) |
| Simulator isolation | `test_whatif_isolation.py` (12), `test_whatif.py` (2) |
| Answer-sheet OCR | `test_ocr.py` (13) |
| Others | one file each: `test_constraints.py`, `test_audit_chain.py`, `test_root_cause.py`, `test_concurrency.py`, `test_versioned_rules.py`, `test_surveys_etl.py`, `test_datagen.py` |

## Phases 7–10

Answer-sheet OCR (phase 7) is tested above; its accuracy on synthetic scans is in
[ocr-evaluation.md](ocr-evaluation.md). The tests for Google Forms surveys, early warning,
weak-student lists and the course-file PDF (PRD Section 8) will be added with phases 8–10.

## Demo data run

Last run on 2 Nov 2026 (not rerun for this report): `python -m scripts.demo` gave 556,800 marks,
11,965 surveys, 248 offerings computed, and 573,223 audit records chained, anchored and verified
intact.
