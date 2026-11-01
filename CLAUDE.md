# CO-PO Attainment Management System

DBMS (CD252IA) project, Dept. of ISE, RVCE — Team 2. PostgreSQL + MongoDB system that computes
Course Outcome (CO) and Program Outcome (PO) attainment from question-wise marks and surveys.

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
- No AI attribution in commits or PRs (no `Co-Authored-By` trailer, no "Generated with" footer).

## Scope guardrails

- v1 is CO-PO attainment only. SAP / ERP export is deferred — do not build it unless asked.
- Synthetic data only; never commit real student marks.
- Thresholds, targets and weights are data in `attainment_config`, never hard-coded.
