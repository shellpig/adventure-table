// Runs the Playwright suite against the containerised dev server instead of a
// local one. The Windows vite dev server drops out mid-run (see KI-ENV-001 in
// 已知問題.md), so 4173 is not usable for a full-suite invocation on Windows.
//
// The rebuild is not optional: the web service bakes apps/web into its image
// with no bind mount, so skipping it silently tests the previous frontend.
//
// A full invocation runs the suite twice. The second pass restarts the server
// with xge removed from ADVENTURE_TABLE_ENABLED_CONTENT_PACKS and re-runs the
// M03-C import spec, because its unresolved-ref contracts (Draft landing and
// draft_reconstruction_unavailable) can only be observed against a backend that
// is missing a pack. Passing extra Playwright arguments skips that second pass.
//
// Usage: npm run test:e2e:docker [-- <playwright args>]
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = resolve(webDir, '..', '..')
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:5173'
const playwrightArgs = process.argv.slice(2)
const SUBSET_SPEC = 'e2e/m03c-character-import.spec.ts'

const run = (command, args, cwd, env = {}) => {
  const result = spawnSync(command, args, {
    cwd,
    stdio: 'inherit',
    shell: true,
    env: { ...process.env, ...env },
  })
  return result.status ?? 1
}

const runOrExit = (command, args, cwd, env = {}) => {
  const status = run(command, args, cwd, env)
  if (status !== 0) process.exit(status)
}

const waitForWeb = async () => {
  console.log(`[e2e-docker] waiting for ${baseURL}`)
  const deadline = Date.now() + 60_000
  for (;;) {
    try {
      const response = await fetch(baseURL, { signal: AbortSignal.timeout(3000) })
      if (response.ok) return
    } catch {
      // not up yet
    }
    if (Date.now() > deadline) {
      console.error(`[e2e-docker] ${baseURL} did not become available within 60s`)
      process.exit(1)
    }
    await new Promise((r) => setTimeout(r, 1000))
  }
}

// The enabled-pack list lives in app/config.py; ask the running server for it
// rather than restating it here, so the subset stays correct as packs are added.
const enabledPacksWithoutXge = () => {
  const script =
    "from app.config import Settings; " +
    "print(','.join(p for p in Settings().enabled_content_packs if p != 'xge'))"
  const result = spawnSync(
    `docker compose exec -T server python -c "${script}"`,
    [],
    { cwd: repoRoot, shell: true, encoding: 'utf8' },
  )
  if (result.status !== 0) {
    console.error('[e2e-docker] could not read the enabled pack list from the server container')
    process.exit(result.status ?? 1)
  }
  const packs = result.stdout.trim()
  if (!packs || packs.includes('xge')) {
    console.error(`[e2e-docker] unexpected pack subset from the server container: ${packs}`)
    process.exit(1)
  }
  return packs
}

process.env.PLAYWRIGHT_BASE_URL = baseURL

console.log(`[e2e-docker] rebuilding the web service so it serves the current apps/web`)
runOrExit('docker', ['compose', 'up', '-d', '--build', 'web'], repoRoot)
await waitForWeb()

console.log(`[e2e-docker] running Playwright against ${baseURL}`)
runOrExit('npx', ['playwright', 'test', ...playwrightArgs], webDir)

if (playwrightArgs.length > 0) process.exit(0)

const subset = enabledPacksWithoutXge()
console.log(`[e2e-docker] restarting the server without xge (${subset})`)
runOrExit('docker', ['compose', 'up', '-d', 'web'], repoRoot, {
  ADVENTURE_TABLE_ENABLED_CONTENT_PACKS: subset,
})
await waitForWeb()

console.log(`[e2e-docker] re-running ${SUBSET_SPEC} against the xge-less backend`)
const subsetStatus = run('npx', ['playwright', 'test', SUBSET_SPEC], webDir, {
  M03C_E2E_DISABLE_XGE: '1',
})

console.log(`[e2e-docker] restoring the server to the full pack list`)
const restoreStatus = run('docker', ['compose', 'up', '-d', 'web'], repoRoot)

if (subsetStatus !== 0) process.exit(subsetStatus)
process.exit(restoreStatus)
