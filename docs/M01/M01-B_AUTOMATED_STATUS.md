# M01-B Automated Status

This file intentionally separates automated implementation evidence from the mandatory manual Human Gate.

## Automated regression status

Full repository regression is green on the M01-B branch at `de53ebed12cd210c6823284edb5eaf5c4281c208`.

GitHub Actions evidence:

- Workflow: `P1 Full Regression`
- Run: `#475` (`33297019620`)
- Result: `success`
- Backend: `173 passed`, 1 upstream/dependency deprecation warning.
- Alembic fresh-database validation: passed.
- P0 → P1 migration and legacy character compatibility: passed.
- Frontend TypeScript/Vite build: passed.
- Vitest: 5 files, 12 tests passed.
- Docker Compose build/start/readiness: passed with both `srd5.1` and `phb2014` content available in the server image.
- Playwright: 15 tests passed.
- Closeout smoke screenshots: uploaded by the workflow.
- Server restart persistence verification for P0 and P1 data: passed.

M01-B-specific automated coverage also includes complete PHB background roleplay-table coverage, cross-source subrace integration, Variant Human choices/prerequisites, `variant_of` same-kind fail-fast validation, racial spell source isolation, and source-aware multi-pack browser regressions.

## Remaining closeout boundary

Automation is complete, but M01-B is **not closed yet**. The mandatory six-flow real-browser Human Gate in `測試指南.md` must still be completed by a human tester. Playwright evidence must not be used as a substitute for that gate.
