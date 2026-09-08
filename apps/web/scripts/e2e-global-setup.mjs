// Puts the database into a known state before the suite runs.
//
// This setup is intentionally destructive. CI always runs against a disposable
// Docker volume. Local runs must opt in explicitly with
// ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1 so a developer's real Character
// data can never be silently claimed into or deleted with the Playwright Room.
//
// Three steps, all required:
//
//   1. Clear Character/Draft/Room state in the dedicated E2E database.
//   2. Re-seed the deterministic P0 fixture character used by legacy specs.
//   3. Create one deterministic P2-B baseline Room. With a clean database this
//      zero-Room bootstrap claims only that known P0 fixture.
import { mkdirSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = resolve(webRoot, '..', '..')
const roomContextPath = resolve(webRoot, 'test-results', 'p2-room-context.json')

const E2E_ROOM_PASSWORD = 'p2-e2e-room-pass'

// Order matters. Session history RESTRICTs the Campaign and Seats it references,
// and participant/controller references keep access sessions alive. Clear the
// live lease + participant + Session graph before the older Campaign-owned rows;
// then clear Room access/workspace state and finally Character/Draft state.
// rooms.active_campaign_id is SET NULL and needs no separate step.
const SQL = `
DELETE FROM active_character_session_leases;
DELETE FROM session_participants;
DELETE FROM sessions;
DELETE FROM campaign_seats;
DELETE FROM campaign_roster_entries;
DELETE FROM campaigns;
DELETE FROM room_access_sessions;
DELETE FROM room_builder_drafts;
DELETE FROM room_characters;
DELETE FROM rooms;
DELETE FROM characters;
DELETE FROM character_build_drafts;
SELECT count(*) AS remaining_characters FROM characters;
SELECT count(*) AS remaining_drafts FROM character_build_drafts;
SELECT count(*) AS remaining_rooms FROM rooms;
SELECT count(*) AS remaining_campaigns FROM campaigns;
SELECT count(*) AS remaining_seats FROM campaign_seats;
SELECT count(*) AS remaining_sessions FROM sessions;
SELECT count(*) AS remaining_participants FROM session_participants;
SELECT count(*) AS remaining_active_leases FROM active_character_session_leases;
`

// The SQL goes in on stdin rather than through -c: it is multi-line, and a
// shell-quoted argument arrives at psql with the newlines still escaped, which
// psql then reads as backslash commands.
const run = (command, args, input) => {
  const result = spawnSync(command, args, {
    cwd: repoRoot,
    input,
    stdio: [input === undefined ? 'inherit' : 'pipe', 'inherit', 'inherit'],
    shell: true,
  })
  if (result.status !== 0) process.exit(result.status ?? 1)
}

function requireDisposableDatabase() {
  const explicitlyAllowed = process.env.ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET === '1'
  const githubActions = process.env.CI === 'true' && process.env.GITHUB_ACTIONS === 'true'
  if (explicitlyAllowed || githubActions) return
  throw new Error(
    'Refusing destructive Playwright database reset. Run against a disposable database and set ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1.',
  )
}

async function createBaselineRoom() {
  const apiBaseUrl = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000'
  const response = await fetch(`${apiBaseUrl}/api/rooms`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: 'P2-B E2E Baseline Room',
      password: E2E_ROOM_PASSWORD,
      display_name: 'Playwright Owner',
    }),
  })
  if (!response.ok) {
    throw new Error(`P2-B baseline Room creation failed: ${response.status} ${await response.text()}`)
  }
  const grant = await response.json()
  const context = {
    roomId: grant.room.id,
    code: grant.room.code,
    name: grant.room.name,
    accessToken: grant.access_token,
    authority: grant.authority,
  }
  mkdirSync(dirname(roomContextPath), { recursive: true })
  writeFileSync(roomContextPath, JSON.stringify(context, null, 2), 'utf8')
  console.log(`[e2e-setup] baseline Room ${context.roomId} is ready`)
}

export default async function globalSetup() {
  requireDisposableDatabase()

  console.log('[e2e-setup] clearing Character, Draft and Room state in the disposable E2E database')
  run('docker', ['compose', 'exec', '-T', 'db', 'psql', '-U', 'adventure', '-d', 'adventure_table'], SQL)

  console.log('[e2e-setup] re-seeding the P0 fixture character')
  run('docker', ['compose', 'exec', '-T', 'server', 'python', '-m', 'app.scripts.seed_p0_fighter_wizard'])

  console.log('[e2e-setup] creating the shared P2-B Room and claiming the known fixture')
  await createBaselineRoom()
}