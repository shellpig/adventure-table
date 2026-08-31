# M02-D Closeout

M02-D — SRD 5.1 Names & Structured Text is complete.

## Delivered

- `srd5.1` policy-required names and short structured presentation are available in `zh-TW` and `en` without changing StableKey or mechanics identity.
- Human-reviewable `zh-TW` locale shards cover 1,635 unique StableKeys and 1,662 presentation fields.
- Builder progression, spellcasting, equipment/review, Character Workshop, and Character Sheet resolve rules presentation by StableKey.
- Completeness and zh-TW source-language gates reject missing or avoidably English shipped names while preserving rules notation such as CR, dice, and ft.
- The project owner accepted the completed terminology review on 2026-08-31.
- Docker server images include `data/localization/`, so localization policy and M02-D runtime data are available in full-stack deployments.
- M02-D authoring unit tests run in the main regression workflow.

## Verification

- Backend: 226 pytest tests passed.
- Authoring: 13 unittest tests passed.
- Frontend: 49 Vitest tests passed and the production TypeScript/Vite build passed.
- Docker full stack: PostgreSQL and backend healthy; `/health`, `/ready`, and web startup passed.
- Presentation API: `en` and `zh-TW` resolved canonical/overlay names with zero presentation API HTTP 500 responses after the packaging fix.
- Playwright: 23 of 23 real-browser tests passed against a clean isolated database and deterministic P0 fixture.
- GitHub Actions could not start because the repository account spending limit/billing state blocked runner execution; this is an external CI availability limitation, not a test-body failure.

## Next

Proceed to **M02-E — SRD 5.1 User-Visible Descriptions**. M02-E must translate only long-form fields currently marked user-visible and required by the M02-C field policy.
