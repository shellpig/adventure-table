import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'scripts/e2e-docker.mjs'), 'utf8')
const envSource = readFileSync(resolve(process.cwd(), 'scripts/e2e-env.mjs'), 'utf8')

describe('Docker E2E wrapper', () => {
  it('uses a dedicated E2E service pair instead of restarting the daily server and web', () => {
    expect(envSource).toContain("E2E_SERVER_SERVICE = 'server-e2e'")
    expect(envSource).toContain("E2E_WEB_SERVICE = 'web-e2e'")
    expect(source).toContain("composeE2E('up', '-d', '--build', E2E_SERVER_SERVICE, E2E_WEB_SERVICE)")
    expect(source).not.toContain("['compose', 'up', '-d', '--build', 'server', 'web']")
    expect(source).not.toContain("['compose', 'up', '-d', 'server', 'web']")
  })

  it('waits for PostgreSQL health before inspecting or creating the E2E database', () => {
    expect(source).toContain("['compose', 'up', '-d', '--wait', '--wait-timeout', '60', 'db']")
    expect(source.indexOf("'--wait-timeout', '60'")).toBeLessThan(source.indexOf("'psql'"))
  })

  it('targets the isolated E2E database and fixed browser/API ports', () => {
    expect(envSource).toContain("E2E_DATABASE = 'adventure_table_e2e'")
    expect(envSource).toContain('E2E_SERVER_PORT = 8001')
    expect(envSource).toContain('E2E_WEB_PORT = 5174')
    expect(source).toContain("'createdb', '-U', postgresUser, E2E_DATABASE")
  })

  it('keeps the xge subset and restore passes on the isolated services', () => {
    expect(source.match(/composeE2E\('up', '-d', E2E_SERVER_SERVICE, E2E_WEB_SERVICE\)/g)?.length).toBe(2)
    expect(source).toContain('docker compose --profile ${E2E_COMPOSE_PROFILE} exec -T ${E2E_SERVER_SERVICE}')
  })
})
