import { defineConfig } from '@playwright/test'

import type { RoomSource } from './e2e/support/roomTest'

const externalBaseURL = process.env.PLAYWRIGHT_BASE_URL

if (!externalBaseURL && process.platform === 'win32' && !process.env.ALLOW_WINDOWS_VITE_E2E) {
  throw new Error(
    [
      'Refusing to host vite from Playwright on Windows (KI-ENV-001).',
      'The Windows vite dev server stops accepting connections partway through a run,',
      'producing dozens of net::ERR_CONNECTION_REFUSED failures at random points.',
      '',
      'Run the suite against the Linux container instead:',
      '  cd apps/web && npm run test:e2e:docker',
      'The --build in that script is not optional; the web service has no bind mount.',
      '',
      'To reproduce the dev server problem on purpose, set ALLOW_WINDOWS_VITE_E2E=1.',
      'See 已知問題.md, KI-ENV-001.',
    ].join('\n'),
  )
}

const baseURL = externalBaseURL ?? 'http://127.0.0.1:4173'
const localeOrigin = new URL(baseURL).origin

// Specs that expect the seeded P0 fixture character (by id or by name). Only the first Room
// created after a reset adopts it, so these share the global-setup baseline Room
// and must not run alongside each other.
const BASELINE_ROOM_SPECS = [
  'character-builder.spec.ts',
  'character-sheet.spec.ts',
  'm01n-character-sheet-html-export.spec.ts',
  'm02b-ui-copy.spec.ts',
  'm02h-bilingual-site-smoke.spec.ts',
  'm02h-localization-state-integrity.spec.ts',
  'm03b-character-export.spec.ts',
  'p2f-cross-campaign.spec.ts',
]
// Restarts server-e2e mid-test, which would kill every other worker's run.
const RESTART_SPECS = ['p4f-full-combat-journey.spec.ts', 'p6g-restart-continuity.spec.ts']

export default defineConfig<{}, { roomSource: RoomSource }>({
  testDir: './e2e',
  globalSetup: './scripts/e2e-global-setup.mjs',
  fullyParallel: false,
  // Serial by default so an ad-hoc run behaves as before; e2e-docker.mjs passes
  // --workers for the 'parallel' project and keeps the other two at one.
  workers: 1,
  projects: [
    { name: 'parallel', testIgnore: [...BASELINE_ROOM_SPECS, ...RESTART_SPECS] },
    { name: 'baseline-room', testMatch: BASELINE_ROOM_SPECS, use: { roomSource: 'baseline' } },
    { name: 'serial-restart', testMatch: RESTART_SPECS },
  ],
  // The Builder specs drive one option at a time and wait for the draft revision
  // after each, so the heaviest of them (a level 8 Wizard) needs a little over
  // 30 seconds on a GitHub runner. The default 30 s cut them off mid-sweep and
  // the truncated revision poll read as a save that never landed.
  timeout: 60_000,
  use: {
    baseURL,
    browserName: 'chromium',
    storageState: {
      cookies: [],
      origins: [
        {
          origin: localeOrigin,
          localStorage: [{ name: 'adventure-table.locale', value: 'en' }],
        },
      ],
    },
  },
  ...(externalBaseURL
    ? {}
    : {
        webServer: {
          command: 'npm run dev:e2e',
          url: 'http://127.0.0.1:4173',
          reuseExistingServer: !process.env.CI,
        },
      }),
})
