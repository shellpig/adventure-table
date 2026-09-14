// Puts only the dedicated U01-A E2E database into a known state before the suite.
// The destructive SQL and database identity guard live in e2e-reset-db.mjs so
// the wrong-database rejection can be exercised without running Playwright.
import { mkdirSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

import {
  E2E_API_BASE_URL,
  E2E_COMPOSE_PROFILE,
  E2E_SERVER_SERVICE,
} from './e2e-env.mjs'
import { resetE2EDatabase } from './e2e-reset-db.mjs'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = resolve(webRoot, '..', '..')
const roomContextPath = resolve(webRoot, 'test-results', 'p2-room-context.json')

const E2E_ROOM_PASSWORD = 'p2-e2e-room-pass'

const run = (command, args) => {
  const result = spawnSync(command, args, {
    cwd: repoRoot,
    stdio: 'inherit',
    shell: true,
    env: process.env,
  })
  if (result.status !== 0) throw new Error(`${command} exited with ${result.status ?? 1}`)
}

async function createBaselineRoom() {
  const apiBaseUrl = process.env.PLAYWRIGHT_API_BASE_URL ?? E2E_API_BASE_URL
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
  console.log('[e2e-setup] resetting the dedicated U01-A E2E database')
  const resetStatus = resetE2EDatabase()
  if (resetStatus !== 0) {
    throw new Error(`dedicated E2E database reset failed with exit code ${resetStatus}`)
  }

  console.log('[e2e-setup] re-seeding the P0 fixture character in server-e2e')
  run('docker', [
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

  console.log('[e2e-setup] creating the shared P2-B Room in the dedicated E2E database')
  await createBaselineRoom()
}
