// U01-A acceptance helper: prove the dedicated E2E database can contain real
// data, is actually cleared by the production reset helper, and can recover the
// deterministic Character + Room baseline without touching the daily database.
import { spawnSync } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  E2E_API_BASE_URL,
  E2E_COMPOSE_PROFILE,
  E2E_DATABASE,
  E2E_SERVER_SERVICE,
} from './e2e-env.mjs'
import { resetE2EDatabase } from './e2e-reset-db.mjs'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = resolve(webRoot, '..', '..')
const P0_FIXTURE_ID = '00000000-0000-4000-8000-0000000000e0'
const BASELINE_ROOM_NAME = 'P2-B E2E Baseline Room'
const BASELINE_ROOM_PASSWORD = 'p2-e2e-room-pass'

function run(command, args, { input, capture = false, env = process.env } = {}) {
  const result = spawnSync(command, args, {
    cwd: repoRoot,
    env,
    input,
    encoding: 'utf8',
    stdio: capture ? ['pipe', 'pipe', 'pipe'] : ['pipe', 'inherit', 'inherit'],
  })
  if (result.error) throw result.error
  return result
}

function runOrThrow(command, args, options = {}) {
  const result = run(command, args, options)
  if (result.status !== 0) {
    const detail = [result.stdout, result.stderr].filter(Boolean).join('\n').trim()
    throw new Error(`${command} exited with ${result.status ?? 1}${detail ? `\n${detail}` : ''}`)
  }
  return result
}

function psql(sql) {
  const postgresUser = process.env.POSTGRES_USER ?? 'adventure'
  return runOrThrow(
    'docker',
    [
      'compose',
      'exec',
      '-T',
      'db',
      'psql',
      '-v',
      'ON_ERROR_STOP=1',
      '-U',
      postgresUser,
      '-d',
      E2E_DATABASE,
      '-tA',
    ],
    { input: `${sql}\n`, capture: true },
  ).stdout.trim()
}

function counts() {
  const output = psql(`
SELECT concat_ws('|',
  (SELECT count(*) FROM characters),
  (SELECT count(*) FROM rooms),
  (SELECT count(*) FROM ai_oauth_clients)
);
`)
  const values = output.split('|').map((value) => Number.parseInt(value, 10))
  if (values.length !== 3 || values.some((value) => !Number.isInteger(value))) {
    throw new Error(`could not parse E2E database counts: ${output}`)
  }
  return { characters: values[0], rooms: values[1], oauthClients: values[2] }
}

async function createRoom(name, password, displayName) {
  const response = await fetch(`${E2E_API_BASE_URL}/api/rooms`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, password, display_name: displayName }),
  })
  if (!response.ok) {
    throw new Error(`E2E Room creation failed: ${response.status} ${await response.text()}`)
  }
  return response.json()
}

async function createGarbageOAuthClient() {
  const response = await fetch(`${E2E_API_BASE_URL}/mcp/oauth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      redirect_uris: ['https://u01a-e2e-reset.invalid/callback'],
      client_name: 'U01-A E2E Reset Garbage Client',
      grant_types: ['authorization_code', 'refresh_token'],
      response_types: ['code'],
      token_endpoint_auth_method: 'none',
    }),
  })
  if (response.status !== 201) {
    throw new Error(`E2E OAuth garbage creation failed: ${response.status} ${await response.text()}`)
  }
  return response.json()
}

function seedFixture() {
  runOrThrow('docker', [
    'compose',
    '--profile',
    E2E_COMPOSE_PROFILE,
    'exec',
    '-T',
    E2E_SERVER_SERVICE,
    'python',
    '-m',
    'app.scripts.seed_p0_fighter_wizard',
  ])
}

async function main() {
  const ready = await fetch(`${E2E_API_BASE_URL}/ready`, { signal: AbortSignal.timeout(5000) })
  if (!ready.ok) throw new Error(`E2E server is not ready: HTTP ${ready.status}`)

  await createRoom('U01-A E2E Reset Garbage Room', 'u01-a-e2e-reset-garbage-pass', 'U01-A Reset Probe')
  await createGarbageOAuthClient()

  const before = counts()
  if (before.characters < 1 || before.rooms < 1 || before.oauthClients < 1) {
    throw new Error(`expected real E2E data before reset, got ${JSON.stringify(before)}`)
  }
  console.log(`[u01-a] E2E database contains real pre-reset data: ${JSON.stringify(before)}`)

  const resetEnv = {
    ...process.env,
    ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET: '1',
  }
  const resetStatus = resetE2EDatabase({ env: resetEnv })
  if (resetStatus !== 0) {
    throw new Error(`dedicated E2E database reset failed with exit code ${resetStatus}`)
  }

  const afterReset = counts()
  if (afterReset.characters !== 0 || afterReset.rooms !== 0 || afterReset.oauthClients !== 0) {
    throw new Error(`E2E destructive reset left data behind: ${JSON.stringify(afterReset)}`)
  }
  console.log('[u01-a] dedicated E2E database reset removed Character, Room, and OAuth test data')

  seedFixture()
  await createRoom(BASELINE_ROOM_NAME, BASELINE_ROOM_PASSWORD, 'Playwright Owner')

  const recovered = counts()
  if (recovered.characters !== 1 || recovered.rooms !== 1 || recovered.oauthClients !== 0) {
    throw new Error(`deterministic E2E baseline did not recover cleanly: ${JSON.stringify(recovered)}`)
  }
  const fixtureCount = Number.parseInt(
    psql(`SELECT count(*) FROM characters WHERE id = '${P0_FIXTURE_ID}';`),
    10,
  )
  if (fixtureCount !== 1) throw new Error('P0 fixture character was not restored after destructive reset')

  console.log('[u01-a] deterministic E2E baseline recovered: 1 fixture Character, 1 baseline Room, 0 OAuth clients')
}

try {
  await main()
} catch (error) {
  console.error(`[u01-a] ${error instanceof Error ? error.message : String(error)}`)
  process.exitCode = 1
}
