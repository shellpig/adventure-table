import { defineConfig } from '@playwright/test'

const externalBaseURL = process.env.PLAYWRIGHT_BASE_URL

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  use: {
    baseURL: externalBaseURL ?? 'http://127.0.0.1:4173',
    browserName: 'chromium',
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
