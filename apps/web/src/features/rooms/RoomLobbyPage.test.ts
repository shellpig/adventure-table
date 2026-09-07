import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { LocaleProvider } from '../../i18n/LocaleProvider'
import { RoomLobbyPage, roomLobbyRouteFromPath } from './RoomLobbyPage'
import { lobbyCopy } from './lobbyCopy'
import { RECENT_ROOMS_STORAGE_KEY } from './roomStorage'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'

function renderLobbyPage() {
  return renderToStaticMarkup(
    createElement(
      LocaleProvider,
      { storage: null, documentTarget: null },
      createElement(RoomLobbyPage, { roomId: ROOM_ID, campaignId: CAMPAIGN_ID }),
    ),
  )
}

describe('P2-D Lobby route and presentation', () => {
  it('recognizes only the Campaign Lobby route', () => {
    expect(roomLobbyRouteFromPath(`/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/lobby`)).toEqual({
      roomId: ROOM_ID,
      campaignId: CAMPAIGN_ID,
    })
    expect(roomLobbyRouteFromPath(`/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}`)).toBeNull()
    expect(roomLobbyRouteFromPath(`/rooms/${ROOM_ID}/sessions`)).toBeNull()
  })

  it('keeps internal phase names out of user-visible copy', () => {
    for (const locale of ['zh-TW', 'en'] as const) {
      const rendered = JSON.stringify(lobbyCopy(locale))
      for (const phase of ['P2-D', 'P2D', 'P3']) {
        expect(rendered).not.toContain(phase)
      }
    }
  })

  it('renders the actual Lobby component missing-access state without a browser DOM', () => {
    const html = renderLobbyPage()
    expect(html).toContain(lobbyCopy('zh-TW').title)
    expect(html).toContain(lobbyCopy('zh-TW').missingAccess)
    expect(html).toContain('href="/"')
  })

  it('renders the actual Lobby component loading state for a persisted Room grant', () => {
    const fakeWindow = {
      localStorage: {
        getItem: (key: string) => key === RECENT_ROOMS_STORAGE_KEY
          ? JSON.stringify([{
              roomId: ROOM_ID,
              code: 'ROOM01',
              name: 'Room',
              accessToken: 'token',
              authority: 'owner',
            }])
          : null,
        setItem: () => undefined,
      },
    }
    const target = globalThis as typeof globalThis & { window?: unknown }
    const previousWindow = target.window
    Object.defineProperty(target, 'window', { value: fakeWindow, configurable: true })
    try {
      const html = renderLobbyPage()
      expect(html).toContain(lobbyCopy('zh-TW').title)
      expect(html).toContain(`href="/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}"`)
      expect(html).not.toContain(lobbyCopy('zh-TW').missingAccess)
    } finally {
      if (previousWindow === undefined) {
        Reflect.deleteProperty(target, 'window')
      } else {
        Object.defineProperty(target, 'window', { value: previousWindow, configurable: true })
      }
    }
  })

  it('keeps Room heartbeat active, refreshes presence, and exposes archive lifecycle', () => {
    const source = readFileSync(new URL('./RoomLobbyPage.tsx', import.meta.url), 'utf8')
    expect(source).toContain('startRoomHeartbeat')
    expect(source).toContain('heartbeatRoom(roomId, token)')
    expect(source).toContain('const [nextLobby, nextResume] = await Promise.all([')
    expect(source).toContain('getLobby(roomId, campaignId, token)')
    expect(source).toContain('getActiveSession(roomId, campaignId, token)')
    expect(source).toContain('setSnapshot(nextLobby)')
    expect(source).toContain('setActiveSession(nextResume.active_session)')
    expect(source).toContain('stopHeartbeat()')
    expect(source).toContain('archiveSeat(roomId, campaignId, seat.id, token)')
  })
})
