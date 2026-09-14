import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

import { E2E_DATABASE } from './e2e-env.mjs'

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = resolve(webDir, '..', '..')

export const RESET_SQL = `
DO $$
BEGIN
  IF current_database() <> 'adventure_table_e2e' THEN
    RAISE EXCEPTION 'refusing destructive E2E reset: current database is %', current_database();
  END IF;
END $$;

TRUNCATE TABLE rooms, characters, ai_oauth_clients RESTART IDENTITY CASCADE;
SELECT count(*) AS remaining_characters FROM characters;
SELECT count(*) AS remaining_drafts FROM character_build_drafts;
SELECT count(*) AS remaining_rooms FROM rooms;
SELECT count(*) AS remaining_campaigns FROM campaigns;
SELECT count(*) AS remaining_seats FROM campaign_seats;
SELECT count(*) AS remaining_sessions FROM sessions;
SELECT count(*) AS remaining_participants FROM session_participants;
SELECT count(*) AS remaining_active_leases FROM active_character_session_leases;
SELECT count(*) AS remaining_events FROM session_events;
SELECT count(*) AS remaining_ai_grants FROM ai_controller_grants;
SELECT count(*) AS remaining_oauth_clients FROM ai_oauth_clients;
`

export function requireDisposableDatabase(env = process.env) {
  const explicitlyAllowed = env.ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET === '1'
  const githubActions = env.CI === 'true' && env.GITHUB_ACTIONS === 'true'
  if (explicitlyAllowed || githubActions) return
  throw new Error(
    'Refusing destructive Playwright database reset. Set ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1; the database identity guard is enforced separately.',
  )
}

export function resetE2EDatabase({ database = E2E_DATABASE, env = process.env } = {}) {
  requireDisposableDatabase(env)
  const postgresUser = env.POSTGRES_USER ?? 'adventure'
  const result = spawnSync(
    'docker',
    [
      'compose',
      'exec',
      '-T',
      'db',
      'psql',
      '-v',
      'ON_ERROR_STOP=1',
      '--single-transaction',
      '-U',
      postgresUser,
      '-d',
      database,
    ],
    {
      cwd: repoRoot,
      env,
      input: RESET_SQL,
      stdio: ['pipe', 'inherit', 'inherit'],
      shell: true,
    },
  )
  return result.status ?? 1
}

function parseDatabaseArg(argv) {
  let database = E2E_DATABASE
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === '--database') {
      const value = argv[index + 1]
      if (!value || value.startsWith('--')) {
        throw new Error('--database requires a database name')
      }
      database = value
      index += 1
      continue
    }
    throw new Error(`unknown argument: ${arg}`)
  }
  return database
}

const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)
if (isMain) {
  try {
    const database = parseDatabaseArg(process.argv.slice(2))
    const status = resetE2EDatabase({ database })
    process.exitCode = status
  } catch (error) {
    console.error(`[e2e-reset-db] ${error instanceof Error ? error.message : String(error)}`)
    process.exitCode = 1
  }
}
