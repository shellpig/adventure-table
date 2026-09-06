// Puts the database into a known state before the suite runs.
//
// Three steps, all required:
//
//   1. Delete the characters, standalone drafts and Rooms left behind by earlier
//      runs. Leftovers make specs pass or fail for reasons unrelated to the
//      branch under test. Names beginning with a non-ASCII character are the
//      project owner's own and are kept -- no spec creates one, they all start
//      with "P0 ", "P1-", "M01-" or "M02-".
//   2. Re-seed the P0 fixture character. character-sheet, m02b-ui-copy,
//      m02h-bilingual-site-smoke and m02h-localization-state-integrity all
//      PATCH its state in beforeEach and never create it, so clearing without
//      re-seeding leaves 19 cases failing on a missing fixture -- which reads
//      exactly like a real regression.
//   3. Create one deterministic P2-B baseline Room after the seed. Because the
//      database has zero Rooms at that point, the P2-B bootstrap path claims the
//      still-unscoped P0 fixture into this Room. The single Playwright worker then
//      reuses that Room so the pre-P2 fixed Character ID remains reachable while
//      every browser/API call still exercises the Room-scoped Web contract.
//
// characters cascades to character_versions, character_states and any draft
// bound to it, so a kept character keeps its whole history. Only drafts with no
// character_id need the name check of their own; an unnamed draft has no owner
// to speak of and is treated as leftover.
//
// Rooms take no name check: every prior E2E Room is run residue. It is cleared
// rather than kept because 331 leftover Rooms turned KI-P1D-001 from an
// intermittent failure into a near-certain one. room_access_sessions goes first;
// it holds the FK to rooms.
import { mkdirSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = resolve(webRoot, '..', '..')
const roomContextPath = resolve(webRoot, 'test-results', 'p2-room-context.json')

const KEEP = "^[^[:ascii:]]"
const E2E_ROOM_PASSWORD = 'p2-e2e-room-pass'

const SQL = `
DELETE FROM characters WHERE name !~ '${KEEP}';
DELETE FROM character_build_drafts
 WHERE character_id IS NULL
   AND coalesce(draft_payload->'basic'->>'name', '') !~ '${KEEP}';
SELECT count(*) AS kept_characters FROM characters WHERE name ~ '${KEEP}';
SELECT count(*) AS kept_drafts FROM character_build_drafts
 WHERE character_id IS NULL
   AND coalesce(draft_payload->'basic'->>'name', '') ~ '${KEEP}';
DELETE FROM room_access_sessions;
DELETE FROM rooms;
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
  console.log('[e2e-setup] clearing leftover characters, drafts and Rooms (non-ASCII names are kept)')
  run('docker', ['compose', 'exec', '-T', 'db', 'psql', '-U', 'adventure', '-d', 'adventure_table'], SQL)

  console.log('[e2e-setup] re-seeding the P0 fixture character')
  run('docker', ['compose', 'exec', '-T', 'server', 'python', '-m', 'app.scripts.seed_p0_fighter_wizard'])

  console.log('[e2e-setup] creating the shared P2-B Room and claiming legacy fixtures')
  await createBaselineRoom()
}
