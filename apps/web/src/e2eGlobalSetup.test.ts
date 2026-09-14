import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'scripts/e2e-global-setup.mjs'), 'utf8')

describe('E2E global setup', () => {
  it('delegates destructive reset to the guarded dedicated reset script', () => {
    expect(source).toContain("from './e2e-reset-db.mjs'")
    expect(source).toContain('resetE2EDatabase()')
    expect(source).not.toContain('TRUNCATE TABLE')
    expect(source).not.toContain("'-d', 'adventure_table'")
  })

  it('seeds through server-e2e and creates the baseline Room on the E2E API', () => {
    expect(source).toContain('E2E_SERVER_SERVICE')
    expect(source).toContain('E2E_COMPOSE_PROFILE')
    expect(source).toContain('E2E_API_BASE_URL')
    expect(source).toContain('app.scripts.seed_p0_fighter_wizard')
  })
})
