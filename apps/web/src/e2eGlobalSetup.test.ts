import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'scripts/e2e-global-setup.mjs'), 'utf8')

describe('E2E global database reset', () => {
  it('truncates every root data graph instead of maintaining a brittle delete order', () => {
    expect(source).toContain('TRUNCATE TABLE')
    expect(source).toContain('rooms,')
    expect(source).toContain('characters,')
    expect(source).toContain('ai_oauth_clients')
    expect(source).toContain('RESTART IDENTITY CASCADE')
    expect(source).not.toContain('DELETE FROM')
  })

  it('fails the setup on the first psql error and rolls the reset back', () => {
    expect(source).toContain("'-v', 'ON_ERROR_STOP=1', '--single-transaction'")
  })
})
