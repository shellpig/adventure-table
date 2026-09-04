import { defineConfig } from '@playwright/test'

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

export default defineConfig({
  testDir: './e2e',
  globalSetup: './scripts/e2e-global-setup.mjs',
  fullyParallel: false,
  workers: 1,
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
