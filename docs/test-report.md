# Test report

Run on 28 Nov 2026: `python -m pytest`, PostgreSQL 16, MongoDB 8.0.6, Python 3.11, Tesseract 5.4.
**222 passed, 0 failed** (166 before phase 7, plus 19 for answer-sheet OCR, 9 for Google Forms
surveys, 7 for weak students and early warning, 4 for the course file and 16 for the simple flow:
12 in `test_simple_flow.py`, 2 more component-weight and 2 more synthetic-data tests). The one warning is a Starlette deprecation in the test
client.

## PRD Section 8 tests

| PRD test | Tests | Result | What it shows |
| --- | ---: | --- | --- |
| Correctness | 18 | pass | Worked example gives CO 3.00 / 2.20 / 0.40, PO1 2.30, PO2 1.48. Component weights (test 30, quiz 20, SEE 50): 70 / 80 / 60 % gives 67.0 %, and 63.75 % without a quiz question on the CO; changing the weights in the rule version changes the score. EL never counts towards a CO and cannot be tagged to one (CP017). Absent counts as 0. The level follows the stored percentage, and the view uses the offering's rule version. |
| Improvement actions | 5 | pass | A recompute closes the action of a CO now at target and updates the text of one still below it. Follow-ups link to the next offering of the same course and section within 18 months, whichever is computed first. |
| Constraints | 27 | pass | Marks outside 0..max, edits/deletes/inserts on locked assessments, question weights ≠ 1, component weights ≠ 100, strengths outside 1–3, cross-course and cross-programme mappings, prerequisite cycles, lock with missing marks, unlock without an approved request, duplicate enrolment: all rejected with their own SQLSTATE. |
| Access control | 28 | pass | Faculty B sees and changes none of faculty A's rows and cannot compute or analyse A's offerings. The Programme coordinator reads everything and writes nothing. Students see only their own marks and scores. Only the admin refreshes dashboards or computes everything, and setting `app.role` alone grants nothing. API checks cover login, typed marks (EL only; all or nothing, row errors listed, a locked assessment refused and logged; the old CSV upload and template endpoints answer 405/404), lock, unlock approval, survey submission, audit verification and student pages. |
| Audit tamper | 16 | pass | Edited, deleted or rewritten audit documents are reported with the first broken `seq`, including deletion of the newest documents. The writer recovers without duplicates and stops rather than writing over a gap. Refused edits are recorded as `DENIED`. |
| Performance | — | see report | `docs/explain/report.md`: the 006 indexes make the per-CO path 2.2× faster (185 → 83 ms). The per-offering computation already uses constraint indexes. |
| Root cause | 15 | pass | Planted cause ranks first and the decoy is excluded; random data gives no cause; small cohorts are not reported; deeper levels are weighted down by `rc_depth_decay`. Detection rates by cohort size and effect are in `docs/root-cause-evaluation.md`. |
| Simulator isolation | 14 | pass | What-if runs leave official tables unchanged, show which POs cross the target, run on another rule version, and cannot be persisted. |
| Concurrency | 8 | pass | A second compute on the same offering waits or is refused; a failed run leaves the previous results; a lock waits for uncommitted mark edits; an unlock waits for a running compute; dashboards stay readable during a compute. |
| Reproducibility | 4 | pass | Re-running with the old rule version reproduces the old numbers; later rule changes do not alter past results; versions cannot overlap. |
| Surveys and ETL | 24 | pass | Reference checks against PostgreSQL, one response per student, keyed-hash respondent, malformed answers rejected, idempotent ETL that recomputes affected offerings. |
| Answer-sheet OCR | 19 | pass | The cover page's 20 mark rows (two columns of ten), USN and total fit inside the corner squares without overlapping. Question lines are read through OCR confusions (a stray mark turning Q10 into Q1i0 gives back Q10; a Bloom field re-read as "Lt" is level 1) and unreadable lines are reported; "Part A - Quiz" and "Part B - Test" headings tag each question with its part, also when read as "PartA" or "Part 8:". Marks are chosen within each question's maximum and USNs among enrolled students. A synthetic CIE 1 PDF (quiz Q1-Q3, test Q4-Q6, 15 sheets) is scanned end to end: questions and parts exact, renumbered per assessment, every wrong value flagged; confirming creates Quiz 1 and CIE Test 1 with the right maxima, saves every mark (paper Q6 lands in the test's Q3) and AB for students without a sheet, and leaves locking to the teacher. A confirm with any row error saves and creates nothing. An existing CIE Test 1 is filled, not recreated, and a student with no sheet who already has marks keeps them unless the teacher opts in. Locked assessments (logged as denied), other faculty, the coordinator, unknown sittings and non-PDFs are refused; the old per-assessment reader is gone. Questions can only be retagged once marks exist, and an assessment's maximum follows its questions. A CIE 3 scan creates Quiz 3 and CIE Test 3 with CIE number 3. Marks are taken from each question's own row; an unreadable page gets one empty input per question; questions beyond Q20 are not offered and missing part headings are reported; the review threshold comes from the rule version. Needs Tesseract and the digit model. |
| Google Forms surveys | 9 | pass | Connecting Google stores only an encrypted refresh token that no other user (not even the HoD) can see and that never reaches the audit chain; a sign-in link finished in another browser is refused. The form collects the verified email, then USN, name, phone and one 1-5 scale per CO; a failed creation deletes the half-made form. Fetched responses are rejected when the verified email is missing, not a college email or not the one on record for the USN (no answering as a classmate), for a malformed or non-enrolled USN or a missing rating; a student's second response is counted, not stored; accepted ones keep only a hashed USN. Repeated fetches are safe. The sign-in state cannot be used as a login or to redirect off the site. Google is faked. |
| Weak students and early warning | 7 | pass | Early warning needs a locked CIE and a running term. Trained on six earlier offerings, weaker CIE marks give a higher chance of missing the CO (training AUC above 0.75) and every flag gives its reason. The flag cut-off comes from the rule version. Locking a CIE runs the warning and leaves the official results unchanged. Weak-student lists are exactly the students below target. Locking an already locked assessment does not retrain, and simultaneous saves of one offering queue instead of colliding. Other teachers cannot see it; the coordinator reads but cannot run it. |
| Course file | 4 | pass | The PDF needs computed results. For the worked example every CO and PO figure in it equals the database (CO 3.00 / 2.20 / 0.40, PO1 2.30, PO2 1.48), with the rules used, the students below target, the automatic action and each student's final marks. Symbols, curly quotes, Devanagari and the rupee sign in a CO statement come out as written. Other teachers cannot download it; the coordinator can. |
| Synthetic data | 12 | pass | Same seed gives the same data, the dataset has the planned size, the planted cause stands out and the decoy does not (CO scores from each student's best two CIEs), every PO is mapped, one login per person. Every finished offering has CIE 1-3, a single-mark EL with no CO and the SEE; weights are test 30, quiz 20, SEE 50; every current offering keeps an assessment open. |
| Simple flow | 12 | pass | Best 2 of 3 CIEs per student: the weakest CIE's marks leave that student's CO scores (a CO tested only there falls back to the SEE), a tie keeps the earlier CIE, two CIEs are both kept; attainment counts only kept CIEs and a locked assessment keeps its CIE number. Final total = best-two CIE average × 30 + EL × 20 + SEE × 50 (AB = 0), partial with what exists; the best-of count and the split come from the rule version. EL is added from its maximum alone, typed one mark per student, locks without a CO and leaves CO attainment unchanged. CIE numbers sit only on quizzes and tests, once per CIE. Per-student root cause lists the prerequisite COs with each student's earlier score (the planted cause is weak more often than the decoy) and is refused to other faculty; the weak-students endpoint gives missed COs and the questions that cost most. Offerings filter by semester. The What-if tab, Trends and Improvement actions menu items and the rule-versions section are not on screen, while their code and routes remain. |

| PRD test | Files |
| --- | --- |
| Correctness | `test_worked_example.py` (12), `test_component_weights.py` (6) |
| Improvement actions | `test_improvement_actions.py` (5) |
| Access control | `test_rls.py` (9), `test_api.py` (15), `test_compute_access.py` (4) |
| Simulator isolation | `test_whatif_isolation.py` (12), `test_whatif.py` (2) |
| Answer-sheet OCR | `test_ocr.py` (18) |
| Google Forms surveys | `test_survey_forms.py` (9) |
| Weak students and early warning | `test_early_warning.py` (7) |
| Course file | `test_course_file.py` (4) |
| Simple flow | `test_simple_flow.py` (12) |
| Others | one file each: `test_constraints.py`, `test_audit_chain.py`, `test_root_cause.py`, `test_concurrency.py`, `test_versioned_rules.py`, `test_surveys_etl.py`, `test_datagen.py` |

## Phases 7–10

Answer-sheet OCR (phase 7), Google Forms surveys (phase 8, with Google faked), weak students with
early warning (phase 9) and the course file (phase 10) are tested above. Accuracy reports: [ocr-evaluation.md](ocr-evaluation.md)
and [early-warning-evaluation.md](early-warning-evaluation.md). The course file (phase 10) is tested
above against the worked example.

## Demo data run

Last run on 2 Nov 2026 (not rerun for this report): `python -m scripts.demo` gave 556,800 marks,
11,965 surveys, 248 offerings computed, and 573,223 audit records chained, anchored and verified
intact.
