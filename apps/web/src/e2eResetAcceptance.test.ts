import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'scripts/e2e-reset-acceptance.mjs'), 'utf8')

describe('U01-A real E2E reset acceptance harness', () => {
  it('creates real disposable Room and OAuth data through the E2E API', () => {
    expect(source).toContain("`${E2E_API_BASE_URL}/api/rooms`")
    expect(source).toContain("`${E2E_API_BASE_URL}/mcp/oauth/register`")
    expect(source).toContain('U01-A E2E Reset Garbage Room')
    expect(source).toContain('U01-A E2E Reset Garbage Client')
  })

  it('uses the canonical E2E database and the production reset helper', () => {
    expect(source).toContain('E2E_DATABASE')
    expect(source).toContain('resetE2EDatabase({ env: resetEnv })')
    expect(source).toContain("ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET: '1'")
    expect(source).toContain('afterReset.characters !== 0')
    expect(source).toContain('afterReset.rooms !== 0')
    expect(source).toContain('afterReset.oauthClients !== 0')
  })

  it('rebuilds and verifies the deterministic Character and Room baseline', () => {
    expect(source).toContain('app.scripts.seed_p0_fighter_wizard')
    expect(source).toContain("const BASELINE_ROOM_NAME = 'P2-B E2E Baseline Room'")
    expect(source).toContain('recovered.characters !== 1')
    expect(source).toContain('recovered.rooms !== 1')
    expect(source).toContain('recovered.oauthClients !== 0')
  })
})
