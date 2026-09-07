import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'


describe('P2-E Lobby Session entry', () => {
  it('loads active Session truth and exposes Start only through the assigned DM Seat', () => {
    const source = readFileSync(new URL('./RoomLobbyPage.tsx', import.meta.url), 'utf8')
    expect(source).toContain('getActiveSession(roomId, campaignId, token)')
    expect(source).toContain("seat.role === 'dm'")
    expect(source).toContain("seat.controller_kind === 'human'")
    expect(source).toContain('seat.controller_access_session_id === snapshot.caller_access_session_id')
    expect(source).toContain('startSession(roomId, campaignId, token)')
    expect(source).toContain('window.location.assign(sessionPath(started.id))')
    expect(source).not.toContain('ready')
  })

  it('routes an existing active Session to the dedicated Session page', () => {
    const lobbySource = readFileSync(new URL('./RoomLobbyPage.tsx', import.meta.url), 'utf8')
    expect(lobbySource).toContain('href={sessionPath(activeSession.id)}')

    const appSource = readFileSync(new URL('../../App.tsx', import.meta.url), 'utf8')
    expect(appSource).toContain('const roomSessionRoute = roomSessionRouteFromPath(pathname)')
    expect(appSource).toContain('<RoomSessionPage')
    expect(appSource.indexOf('if (roomSessionRoute)')).toBeLessThan(
      appSource.indexOf('if (roomLobbyRoute)'),
    )
  })
})
