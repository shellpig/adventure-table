import { defineConfig } from '@playwright/test'

const externalBaseURL = process.env.PLAYWRIGHT_BASE_URL
const baseURL = externalBaseURL ?? 'http://127.0.0.1:4173'
const localeOrigin = new URL(baseURL).origin

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
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
