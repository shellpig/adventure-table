import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'scripts/e2e-reset-db.mjs'), 'utf8')
const envSource = readFileSync(resolve(process.cwd(), 'scripts/e2e-env.mjs'), 'utf8')

describe('U01-A destructive E2E database guard', () => {
  it('checks the real PostgreSQL database identity before the truncate in one SQL payload', () => {
    const guardIndex = source.indexOf("IF current_database() <> 'adventure_table_e2e'")
    const truncateIndex = source.indexOf('TRUNCATE TABLE rooms, characters, ai_oauth_clients')

    expect(guardIndex).toBeGreaterThanOrEqual(0)
    expect(truncateIndex).toBeGreaterThan(guardIndex)
    expect(source).toContain("RAISE EXCEPTION 'refusing destructive E2E reset: current database is %'")
    expect(source).toContain("'-v',")
    expect(source).toContain("'ON_ERROR_STOP=1'")
    expect(source).toContain("'--single-transaction'")
  })

  it('pins the allowed database name as a constant with no environment override', () => {
    expect(envSource).toContain("E2E_DATABASE = 'adventure_table_e2e'")
    expect(source).not.toContain('ADVENTURE_TABLE_E2E_DATABASE')
    expect(source).toContain("arg === '--database'")
  })

  it('keeps the explicit local opt-in while allowing GitHub Actions to use the same hard guard', () => {
    expect(source).toContain("ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET === '1'")
    expect(source).toContain("env.CI === 'true' && env.GITHUB_ACTIONS === 'true'")
  })
})
