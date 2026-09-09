import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'scripts/e2e-docker.mjs'), 'utf8')

describe('Docker E2E wrapper', () => {
  it('rebuilds both backend and frontend before real-backend browser journeys', () => {
    expect(source).toContain("['compose', 'up', '-d', '--build', 'server', 'web']")
    expect(source).not.toContain("['compose', 'up', '-d', '--build', 'web']")
  })

  it('restarts both services for the xge subset and restore passes', () => {
    expect(source.match(/\['compose', 'up', '-d', 'server', 'web'\]/g)?.length).toBe(2)
  })
})
