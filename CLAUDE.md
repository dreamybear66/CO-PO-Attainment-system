# CO-PO Attainment Management System

DBMS (CD252IA) project, Dept. of ISE, RVCE — Team 2. PostgreSQL + MongoDB system that automates a
teacher's CO-PO work: it computes Course Outcome (CO) and Program Outcome (PO) attainment from
question-wise marks and surveys, and (planned) reads marks from scanned answer sheets, runs the
course-exit survey as a Google Form, lists weak students and writes the course file. It is not an
NBA/NAAC accreditation tool.

- Product requirements: PRD (Claude Doc) — https://claude.ai/artifact/G8HdvxVTjQ47XZ6AeEhard
- Build plan: [implementation.md](implementation.md)

## Git workflow

- Commit early and often: one small, logical change per commit, so the history explains how the
  project was built. Prefer many small commits over one large one.
- One branch per feature, not per PR. Keep working on (and opening follow-up PRs from) the existing
  branch for that feature; create a new branch only when starting a different feature.
- Never commit directly to `main`; changes land through a PR.
- Branch names: `<type>/<feature>` (e.g. `docs/project-planning`, `feat/attainment-engine`).
- Commit messages: Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`).
- Keep the docs in step: every commit that changes behaviour, scope, tests or status also updates
  the md files it affects (README.md, implementation.md, docs/*.md, nlp.md) in that same commit.
- No AI attribution in commits or PRs (no `Co-Authored-By` trailer, no "Generated with" footer).
- Identity: commit as the `dreamybear66` GitHub account — repo-local git config
  `user.name = krrish97`, `user.email = krrishagarwal.is24@rvce.edu.in` — and keep `gh` switched
  to `dreamybear66` (`gh auth switch -u dreamybear66`) before pushing or opening PRs.

## Scope guardrails

- Goal: less manual work for teachers. Accreditation reports (NBA SAR / NAAC SSR) are not a goal.
- Novelties: answer-sheet OCR, early-warning prediction and root-cause analysis. The what-if
  simulator, versioned rules and audit log are supporting features.
- Free tools only: local OCR, the free Google Forms API and WhatsApp share links. No paid API
  (WhatsApp Business API, cloud OCR or vision) without asking first.
- OCR and prediction only suggest: no OCR-read value is saved until the teacher confirms it, and
  early-warning output never changes official attainment.
- Survey identity (college email, USN, name, phone) is used only to match the student; store only
  a hashed USN.
- SAP / ERP export is deferred — do not build it unless asked.
- Synthetic data only; never commit real student marks or real answer-sheet scans.
- Thresholds, targets and weights are data in `attainment_config`, never hard-coded.
