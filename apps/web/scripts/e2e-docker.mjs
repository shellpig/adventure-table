// Runs the Playwright suite against the containerised dev server instead of a
// local one. The Windows vite dev server drops out mid-run (see KI-ENV-001 in
// 已知問題.md), so 4173 is not usable for a full-suite invocation on Windows.
//
// The rebuild is not optional: the web service bakes apps/web into its image
// with no bind mount, so skipping it silently tests the previous frontend.
//
// Usage: npm run test:e2e:docker [-- <playwright args>]
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = resolve(webDir, '..', '..')
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:5173'

const run = (command, args, cwd) => {
  const result = spawnSync(command, args, { cwd, stdio: 'inherit', shell: true })
  if (result.status !== 0) process.exit(result.status ?? 1)
}

console.log(`[e2e-docker] rebuilding the web service so it serves the current apps/web`)
run('docker', ['compose', 'up', '-d', '--build', 'web'], repoRoot)

console.log(`[e2e-docker] waiting for ${baseURL}`)
const deadline = Date.now() + 60_000
for (;;) {
  try {
    const response = await fetch(baseURL, { signal: AbortSignal.timeout(3000) })
    if (response.ok) break
  } catch {
    // not up yet
  }
  if (Date.now() > deadline) {
    console.error(`[e2e-docker] ${baseURL} did not become available within 60s`)
    process.exit(1)
  }
  await new Promise((r) => setTimeout(r, 1000))
}

console.log(`[e2e-docker] running Playwright against ${baseURL}`)
process.env.PLAYWRIGHT_BASE_URL = baseURL
run('npx', ['playwright', 'test', ...process.argv.slice(2)], webDir)
