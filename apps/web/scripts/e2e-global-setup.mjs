// Puts the database into a known state before the suite runs.
//
// Two steps, both required:
//
//   1. Delete the characters and standalone drafts left behind by earlier runs.
//      Leftovers make specs pass or fail for reasons unrelated to the branch
//      under test. Names beginning with a non-ASCII character are the project
//      owner's own and are kept -- no spec creates one, they all start with
//      "P0 ", "P1-", "M01-" or "M02-".
//   2. Re-seed the P0 fixture character. character-sheet, m02b-ui-copy,
//      m02h-bilingual-site-smoke and m02h-localization-state-integrity all
//      PATCH its state in beforeEach and never create it, so clearing without
//      re-seeding leaves 19 cases failing on a missing fixture -- which reads
//      exactly like a real regression.
//
// characters cascades to character_versions, character_states and any draft
// bound to it, so a kept character keeps its whole history. Only drafts with no
// character_id need the name check of their own; an unnamed draft has no owner
// to speak of and is treated as leftover.
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

const KEEP = "^[^[:ascii:]]"

const SQL = `
DELETE FROM characters WHERE name !~ '${KEEP}';
DELETE FROM character_build_drafts
 WHERE character_id IS NULL
   AND coalesce(draft_payload->'basic'->>'name', '') !~ '${KEEP}';
SELECT count(*) AS kept_characters FROM characters WHERE name ~ '${KEEP}';
SELECT count(*) AS kept_drafts FROM character_build_drafts
 WHERE character_id IS NULL
   AND coalesce(draft_payload->'basic'->>'name', '') ~ '${KEEP}';
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

export default function globalSetup() {
  console.log('[e2e-setup] clearing leftover characters and drafts (non-ASCII names are kept)')
  run('docker', ['compose', 'exec', '-T', 'db', 'psql', '-U', 'adventure', '-d', 'adventure_table'], SQL)

  console.log('[e2e-setup] re-seeding the P0 fixture character')
  run('docker', ['compose', 'exec', '-T', 'server', 'python', '-m', 'app.scripts.seed_p0_fighter_wizard'])
}
