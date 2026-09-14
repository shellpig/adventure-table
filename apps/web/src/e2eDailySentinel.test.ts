import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'scripts/e2e-daily-sentinel.mjs'), 'utf8')

describe('U01-A daily database sentinel harness', () => {
  it('stores its cross-step snapshot outside Playwright test-results', () => {
    expect(source).toContain("from 'node:os'")
    expect(source).toContain('tmpdir()')
    expect(source).toContain("process.env.GITHUB_RUN_ID ?? 'local'")
    expect(source).not.toContain("resolve(webRoot, 'test-results'")
  })

  it('pins the deliberate wrong-database probe to the daily database', () => {
    expect(source).toContain("const DAILY_DATABASE = 'adventure_table'")
    expect(source).toContain("[resetScript, '--database', DAILY_DATABASE]")
    expect(source).toContain("ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET: '1'")
    expect(source).toContain('refusing destructive E2E reset: current database is adventure_table')
  })

  it('keeps the snapshot through ordinary verification and removes it only after the guard passes', () => {
    const verifyIndex = source.indexOf('async function verify()')
    const wrongDbIndex = source.indexOf('async function wrongDatabaseGuard()')
    const unlinkIndex = source.indexOf('unlinkSync(statePath)')

    expect(verifyIndex).toBeGreaterThanOrEqual(0)
    expect(wrongDbIndex).toBeGreaterThan(verifyIndex)
    expect(unlinkIndex).toBeGreaterThan(wrongDbIndex)
  })
})
