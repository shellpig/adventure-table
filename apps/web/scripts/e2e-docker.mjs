// Runs the Playwright suite against an isolated containerised E2E stack.
// U01-A keeps the daily server/web on 8000/5173 and daily PostgreSQL database
// untouched while browser tests use server-e2e/web-e2e and adventure_table_e2e.
//
// A full invocation runs the suite twice. The second pass restarts only the E2E
// services with xge removed and re-runs the M03-C missing-pack import contract.
// Passing extra Playwright arguments skips that second pass.
//
// Usage: npm run test:e2e:docker [-- <playwright args>]
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

import {
  E2E_API_BASE_URL,
  E2E_BASE_URL,
  E2E_COMPOSE_PROFILE,
  E2E_DATABASE,
  E2E_MCP_URL,
  E2E_SERVER_SERVICE,
  E2E_WEB_SERVICE,
} from './e2e-env.mjs'

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = resolve(webDir, '..', '..')
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

const composeE2E = (...args) => ['compose', '--profile', E2E_COMPOSE_PROFILE, ...args]

const ensureE2EDatabase = () => {
  const postgresUser = process.env.POSTGRES_USER ?? 'adventure'
  console.log('[e2e-docker] ensuring PostgreSQL is running')
  runOrExit('docker', ['compose', 'up', '-d', 'db'], repoRoot)

  const query = `SELECT 1 FROM pg_database WHERE datname = '${E2E_DATABASE}';\n`
  const result = spawnSync(
    'docker',
    ['compose', 'exec', '-T', 'db', 'psql', '-U', postgresUser, '-d', 'postgres', '-tA'],
    {
      cwd: repoRoot,
      shell: true,
      encoding: 'utf8',
      input: query,
    },
  )
  if (result.status !== 0) {
    process.stderr.write(result.stderr ?? '')
    console.error('[e2e-docker] could not inspect PostgreSQL databases')
    process.exit(result.status ?? 1)
  }

  if (result.stdout.trim() === '1') return

  console.log(`[e2e-docker] creating ${E2E_DATABASE}`)
  runOrExit(
    'docker',
    ['compose', 'exec', '-T', 'db', 'createdb', '-U', postgresUser, E2E_DATABASE],
    repoRoot,
  )
}

const waitForWeb = async () => {
  console.log(`[e2e-docker] waiting for ${E2E_BASE_URL}`)
  const deadline = Date.now() + 60_000
  for (;;) {
    try {
      const response = await fetch(E2E_BASE_URL, { signal: AbortSignal.timeout(3000) })
      if (response.ok) return
    } catch {
      // not up yet
    }
    if (Date.now() > deadline) {
      console.error(`[e2e-docker] ${E2E_BASE_URL} did not become available within 60s`)
      process.exit(1)
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 1000))
  }
}

const enabledPacksWithoutXge = () => {
  const script =
    "from app.config import Settings; " +
    "print(','.join(p for p in Settings().enabled_content_packs if p != 'xge'))"
  const command = `docker compose --profile ${E2E_COMPOSE_PROFILE} exec -T ${E2E_SERVER_SERVICE} python -c "${script}"`
  const result = spawnSync(command, [], { cwd: repoRoot, shell: true, encoding: 'utf8' })
  if (result.status !== 0) {
    console.error('[e2e-docker] could not read the enabled pack list from server-e2e')
    process.exit(result.status ?? 1)
  }
  const packs = result.stdout.trim()
  if (!packs || packs.split(',').includes('xge')) {
    console.error(`[e2e-docker] unexpected pack subset from server-e2e: ${packs}`)
    process.exit(1)
  }
  return packs
}

const playwrightEnv = {
  PLAYWRIGHT_BASE_URL: E2E_BASE_URL,
  PLAYWRIGHT_API_BASE_URL: E2E_API_BASE_URL,
  PLAYWRIGHT_MCP_URL: E2E_MCP_URL,
}
Object.assign(process.env, playwrightEnv)

ensureE2EDatabase()

console.log('[e2e-docker] rebuilding isolated server-e2e + web-e2e')
runOrExit(
  'docker',
  composeE2E('up', '-d', '--build', E2E_SERVER_SERVICE, E2E_WEB_SERVICE),
  repoRoot,
)
await waitForWeb()

console.log(`[e2e-docker] running Playwright against ${E2E_BASE_URL}`)
runOrExit('npx', ['playwright', 'test', ...playwrightArgs], webDir, playwrightEnv)

if (playwrightArgs.length > 0) process.exit(0)

const subset = enabledPacksWithoutXge()
console.log(`[e2e-docker] restarting isolated E2E services without xge (${subset})`)
runOrExit(
  'docker',
  composeE2E('up', '-d', E2E_SERVER_SERVICE, E2E_WEB_SERVICE),
  repoRoot,
  { ADVENTURE_TABLE_ENABLED_CONTENT_PACKS: subset },
)
await waitForWeb()

console.log(`[e2e-docker] re-running ${SUBSET_SPEC} against the xge-less backend`)
const subsetStatus = run('npx', ['playwright', 'test', SUBSET_SPEC], webDir, {
  ...playwrightEnv,
  M03C_E2E_DISABLE_XGE: '1',
})

console.log('[e2e-docker] restoring isolated E2E services to the full pack list')
const restoreStatus = run(
  'docker',
  composeE2E('up', '-d', E2E_SERVER_SERVICE, E2E_WEB_SERVICE),
  repoRoot,
)

if (subsetStatus !== 0) process.exit(subsetStatus)
process.exit(restoreStatus)
