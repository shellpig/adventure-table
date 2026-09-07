import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { LocaleProvider } from '../../i18n/LocaleProvider'
import { RECENT_ROOMS_STORAGE_KEY } from './roomStorage'
import { RoomSessionPage, roomSessionRouteFromPath } from './RoomSessionPage'
import { sessionCopy } from './sessionCopy'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const SESSION_ID = '30000000-0000-4000-8000-000000000001'

function renderSessionPage() {
  return renderToStaticMarkup(
    createElement(
      LocaleProvider,
      { storage: null, documentTarget: null },
      createElement(RoomSessionPage, {
        roomId: ROOM_ID,
        campaignId: CAMPAIGN_ID,
        sessionId: SESSION_ID,
      }),
    ),
  )
}

describe('P2-E Session route and presentation', () => {
  it('recognizes the Room/Campaign/Session route only', () => {
    expect(roomSessionRouteFromPath(
      `/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}`,
    )).toEqual({ roomId: ROOM_ID, campaignId: CAMPAIGN_ID, sessionId: SESSION_ID })
    expect(roomSessionRouteFromPath(
      `/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/lobby`,
    )).toBeNull()
    expect(roomSessionRouteFromPath(`/sessions/${SESSION_ID}`)).toBeNull()
  })

  it('keeps internal phase labels out of both locales', () => {
    for (const locale of ['zh-TW', 'en'] as const) {
      const rendered = JSON.stringify(sessionCopy(locale))
      for (const phase of ['P2-E', 'P2E', 'P3', 'P4']) {
        expect(rendered).not.toContain(phase)
      }
    }
  })

  it('renders the missing-access state without browser storage', () => {
    const html = renderSessionPage()
    expect(html).toContain(sessionCopy('zh-TW').title)
    expect(html).toContain(sessionCopy('zh-TW').missingAccess)
  })

  it('renders a loading state and Lobby return path for a persisted Room grant', () => {
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
      const html = renderSessionPage()
      expect(html).toContain(sessionCopy('zh-TW').title)
      expect(html).toContain(
        `href="/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/lobby"`,
      )
      expect(html).not.toContain(sessionCopy('zh-TW').missingAccess)
    } finally {
      if (previousWindow === undefined) {
        Reflect.deleteProperty(target, 'window')
      } else {
        Object.defineProperty(target, 'window', { value: previousWindow, configurable: true })
      }
    }
  })

  it('uses heartbeat truth and exposes only explicit P2-E lifecycle calls', () => {
    const source = readFileSync(new URL('./RoomSessionPage.tsx', import.meta.url), 'utf8')
    expect(source).toContain('startRoomHeartbeat')
    expect(source).toContain('heartbeatRoom(roomId, token)')
    expect(source).toContain('lateJoinSession(')
    expect(source).toContain('endSession(roomId, campaignId, sessionId, token)')
    expect(source).toContain('abandonSession(roomId, campaignId, sessionId, token)')
    expect(source).toContain("snapshot.dm_controller_access_session_id === callerAccessSessionId")
    expect(source).not.toContain('ready')
    expect(source).not.toContain('spawn')
    expect(source).not.toContain('combat')
  })
})
