// U01-A acceptance helper for CI. It creates recognizable sentinel data in the
// daily database, snapshots those rows plus the daily server StartedAt value,
// and verifies that isolated E2E work never changes any of them.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { isDeepStrictEqual } from 'node:util'
import { spawnSync } from 'node:child_process'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = resolve(webRoot, '..', '..')
const statePath = resolve(webRoot, 'test-results', 'u01a-daily-sentinel.json')

const DAILY_DATABASE = 'adventure_table'
const DAILY_API_BASE_URL = 'http://127.0.0.1:8000'
const DAILY_WEB_URL = 'http://127.0.0.1:5173'
const P0_FIXTURE_ID = '00000000-0000-4000-8000-0000000000e0'
const SENTINEL_ROOM_NAME = 'U01-A Daily Sentinel Room'
const SENTINEL_ROOM_PASSWORD = 'u01-a-daily-sentinel-pass'
const SENTINEL_OAUTH_NAME = 'U01-A Daily Sentinel Client'

function run(command, args, { env = process.env, input, capture = false } = {}) {
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

async function requireUrl(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(5000) })
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`)
}

function sqlLiteral(value) {
  return `'${String(value).replaceAll("'", "''")}'`
}

function psql(sql) {
  const postgresUser = process.env.POSTGRES_USER ?? 'adventure'
  const result = runOrThrow(
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
      DAILY_DATABASE,
      '-tA',
    ],
    { input: `${sql}\n`, capture: true },
  )
  return result.stdout.trim()
}

function dailyServerStartedAt() {
  const containerId = runOrThrow('docker', ['compose', 'ps', '-q', 'server'], { capture: true }).stdout.trim()
  if (!containerId) throw new Error('daily server container is not running')
  return runOrThrow('docker', ['inspect', '-f', '{{.State.StartedAt}}', containerId], { capture: true }).stdout.trim()
}

function snapshotRows({ roomId, oauthClientId }) {
  const result = psql(`
SELECT json_build_object(
  'room', (
    SELECT row_to_json(room_row)
    FROM (SELECT * FROM rooms WHERE id = ${sqlLiteral(roomId)}) AS room_row
  ),
  'character', (
    SELECT row_to_json(character_row)
    FROM (SELECT * FROM characters WHERE id = ${sqlLiteral(P0_FIXTURE_ID)}) AS character_row
  ),
  'oauth_client', (
    SELECT row_to_json(oauth_row)
    FROM (SELECT * FROM ai_oauth_clients WHERE client_id = ${sqlLiteral(oauthClientId)}) AS oauth_row
  )
)::text;
`)
  const parsed = JSON.parse(result)
  for (const [name, value] of Object.entries(parsed)) {
    if (value === null) throw new Error(`daily sentinel ${name} is missing`)
  }
  return parsed
}

async function prepare() {
  await requireUrl(`${DAILY_API_BASE_URL}/ready`)
  await requireUrl(DAILY_WEB_URL)

  runOrThrow('docker', [
    'compose',
    'exec',
    '-T',
    'server',
    'python',
    '-m',
    'app.scripts.seed_p0_fighter_wizard',
  ])

  const roomResponse = await fetch(`${DAILY_API_BASE_URL}/api/rooms`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: SENTINEL_ROOM_NAME,
      password: SENTINEL_ROOM_PASSWORD,
      display_name: 'U01-A Sentinel Owner',
    }),
  })
  if (!roomResponse.ok) {
    throw new Error(`daily sentinel Room creation failed: ${roomResponse.status} ${await roomResponse.text()}`)
  }
  const roomGrant = await roomResponse.json()

  const oauthResponse = await fetch(`${DAILY_API_BASE_URL}/mcp/oauth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      redirect_uris: ['https://u01a.invalid/callback'],
      client_name: SENTINEL_OAUTH_NAME,
      grant_types: ['authorization_code', 'refresh_token'],
      response_types: ['code'],
      token_endpoint_auth_method: 'none',
    }),
  })
  if (oauthResponse.status !== 201) {
    throw new Error(`daily sentinel OAuth client creation failed: ${oauthResponse.status} ${await oauthResponse.text()}`)
  }
  const oauthClient = await oauthResponse.json()

  const state = {
    roomId: roomGrant.room.id,
    oauthClientId: oauthClient.client_id,
    characterId: P0_FIXTURE_ID,
    serverStartedAt: dailyServerStartedAt(),
  }
  state.snapshot = snapshotRows(state)

  mkdirSync(dirname(statePath), { recursive: true })
  writeFileSync(statePath, JSON.stringify(state, null, 2), 'utf8')
  console.log(`[u01-a] daily sentinel prepared: room=${state.roomId}, character=${state.characterId}, oauth=${state.oauthClientId}`)
  console.log(`[u01-a] daily server StartedAt=${state.serverStartedAt}`)
}

async function verify() {
  const state = JSON.parse(readFileSync(statePath, 'utf8'))
  await requireUrl(`${DAILY_API_BASE_URL}/ready`)
  await requireUrl(DAILY_WEB_URL)

  const currentStartedAt = dailyServerStartedAt()
  if (currentStartedAt !== state.serverStartedAt) {
    throw new Error(`daily server restarted during E2E: before=${state.serverStartedAt}, after=${currentStartedAt}`)
  }

  const currentSnapshot = snapshotRows(state)
  if (!isDeepStrictEqual(currentSnapshot, state.snapshot)) {
    throw new Error(
      `daily sentinel rows changed during E2E\nbefore=${JSON.stringify(state.snapshot)}\nafter=${JSON.stringify(currentSnapshot)}`,
    )
  }
  console.log('[u01-a] daily 8000/5173 remained reachable, server StartedAt is unchanged, and all sentinel rows are byte-for-byte unchanged')
}

async function wrongDatabaseGuard() {
  await verify()
  const resetScript = resolve(webRoot, 'scripts', 'e2e-reset-db.mjs')
  const result = run(
    process.execPath,
    [resetScript, '--database', DAILY_DATABASE],
    {
      capture: true,
      env: {
        ...process.env,
        ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET: '1',
      },
    },
  )
  const output = [result.stdout, result.stderr].filter(Boolean).join('\n')
  process.stdout.write(output)
  if (result.status === 0) throw new Error('wrong-database reset unexpectedly succeeded')
  if (!output.includes('refusing destructive E2E reset: current database is adventure_table')) {
    throw new Error(`wrong-database reset failed for an unexpected reason:\n${output}`)
  }
  await verify()
  console.log('[u01-a] wrong-database hard guard rejected adventure_table and left every daily sentinel unchanged')
}

const command = process.argv[2]
try {
  if (command === 'prepare') await prepare()
  else if (command === 'verify') await verify()
  else if (command === 'wrong-db') await wrongDatabaseGuard()
  else throw new Error('usage: node scripts/e2e-daily-sentinel.mjs <prepare|verify|wrong-db>')
} catch (error) {
  console.error(`[u01-a] ${error instanceof Error ? error.message : String(error)}`)
  process.exitCode = 1
}
