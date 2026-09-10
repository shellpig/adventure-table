import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import type { CampaignSeat } from '../../api/seats'
import type { SessionSnapshot } from '../../api/sessions'
import { LocaleProvider } from '../../i18n/LocaleProvider'
import { RECENT_ROOMS_STORAGE_KEY } from './roomStorage'
import {
  mergeSessionSeatTruth,
  RoomSessionPage,
  roomSessionRouteFromPath,
  sessionTableSnapshotWithCurrentControllers,
  SessionEventConnectionBanner,
} from './RoomSessionPage'
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

function seat(id: string, label: string, archivedAt: string | null = null): CampaignSeat {
  return {
    id,
    campaign_id: CAMPAIGN_ID,
    role: 'player',
    label,
    controller_kind: 'none',
    controller_access_session_id: null,
    controller_display_name: null,
    controller_authority: null,
    presence: 'not_applicable',
    selected_character_id: null,
    archived_at: archivedAt,
    created_at: '2026-09-07T00:00:00Z',
    updated_at: '2026-09-07T00:00:00Z',
  }
}

describe('Session route and presentation', () => {
  it('recognizes the Room/Campaign/Session route only', () => {
    expect(roomSessionRouteFromPath(
      `/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}`,
    )).toEqual({ roomId: ROOM_ID, campaignId: CAMPAIGN_ID, sessionId: SESSION_ID })
    expect(roomSessionRouteFromPath(
      `/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/lobby`,
    )).toBeNull()
    expect(roomSessionRouteFromPath(`/sessions/${SESSION_ID}`)).toBeNull()
  })

  it('unions Resume and Lobby Seat truth while fresh Lobby fields win overlaps', () => {
    const liveLobbySeat = seat('40000000-0000-4000-8000-000000000001', 'Live Seat')
    const archivedParticipant = seat(
      '40000000-0000-4000-8000-000000000002',
      'Archived Mira Seat',
      '2026-09-07T01:00:00Z',
    )
    const resumeSnapshot = seat(liveLobbySeat.id, 'Resume Current Truth')

    const merged = mergeSessionSeatTruth(
      [liveLobbySeat],
      [resumeSnapshot, archivedParticipant],
    )
    expect(merged).toHaveLength(2)
    expect(merged.find((item) => item.id === liveLobbySeat.id)?.label).toBe('Live Seat')
    expect(merged.find((item) => item.id === archivedParticipant.id)?.archived_at).not.toBeNull()
    expect(merged.find((item) => item.id === archivedParticipant.id)?.label).toBe('Archived Mira Seat')
  })

  it('projects table composer control from current Seat truth, not join history', () => {
    const seatId = '40000000-0000-4000-8000-000000000010'
    const snapshot: SessionSnapshot = {
      id: SESSION_ID,
      campaign_id: CAMPAIGN_ID,
      status: 'active',
      dm_seat_id: '40000000-0000-4000-8000-000000000099',
      dm_controller_access_session_id: null,
      started_at: '2026-09-10T00:00:00Z',
      ended_at: null,
      participants: [{
        id: '70000000-0000-4000-8000-000000000001',
        seat_id: seatId,
        role: 'player',
        controller_kind_at_join: 'human',
        controller_access_session_id_at_join: 'old-human',
        active_character_id: '60000000-0000-4000-8000-000000000001',
      }],
    }
    const currentSeat = seat(seatId, 'Mira')
    currentSeat.controller_kind = 'human'
    currentSeat.controller_access_session_id = 'new-human'

    const projected = sessionTableSnapshotWithCurrentControllers(snapshot, [currentSeat])
    expect(projected.participants[0].controller_access_session_id_at_join).toBe('new-human')
    expect(snapshot.participants[0].controller_access_session_id_at_join).toBe('old-human')

    currentSeat.controller_kind = 'ai'
    currentSeat.controller_access_session_id = null
    expect(
      sessionTableSnapshotWithCurrentControllers(snapshot, [currentSeat])
        .participants[0].controller_access_session_id_at_join,
    ).toBeNull()
  })

  it('renders persistent reconnect and fatal connection status in both locales', () => {
    for (const locale of ['zh-TW', 'en'] as const) {
      const copy = sessionCopy(locale)
      const reconnecting = renderToStaticMarkup(createElement(SessionEventConnectionBanner, {
        status: 'reconnecting',
        copy,
      }))
      const fatal = renderToStaticMarkup(createElement(SessionEventConnectionBanner, {
        status: 'fatal',
        copy,
      }))

      expect(reconnecting).toContain(copy.eventReconnecting)
      expect(reconnecting).toContain('data-session-event-connection="reconnecting"')
      expect(fatal).toContain(copy.eventDisconnected)
      expect(fatal).toContain('data-session-event-connection="fatal"')
      expect(reconnecting).toContain('class="notice-banner"')
      expect(reconnecting).toContain('role="status"')
      expect(fatal).toContain('class="error-banner"')
      expect(fatal).toContain('role="alert"')
    }
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

  it('uses one initial Resume then incremental events for Stage and exploration updates', () => {
    const source = readFileSync(new URL('./RoomSessionPage.tsx', import.meta.url), 'utf8')
    expect(source).toContain('startRoomHeartbeat')
    expect(source).toContain('heartbeatRoom(roomId, token)')
    expect(source.match(/getActiveSession\(roomId, campaignId, token\)/g) ?? []).toHaveLength(1)
    expect(source).toContain('runSessionEventPoll({')
    expect(source).toContain('waitSessionEvents(')
    expect(source).toContain('applySessionEventPage(')
    expect(source).toContain('eventStreamFromResume(nextResume)')
    expect(source).toContain('setInitialStage(nextResume.active_session?.id === sessionId')
    expect(source).toContain('<SessionTableSurface')
    expect(source).toContain('mergeSessionSeatTruth(')
    expect(source).toContain('sessionTableSnapshotWithCurrentControllers(')
    expect(source).toContain('<PlayerAIControlPanel')
    expect(source).toContain('lateJoinSession(')
    expect(source).toContain('endSession(roomId, campaignId, sessionId, token)')
    expect(source).toContain('abandonSession(roomId, campaignId, sessionId, token)')
    expect(source).toContain("snapshot.dm_controller_access_session_id === callerAccessSessionId")
    expect(source).not.toContain('ready')
    expect(source).not.toContain('spawn')
    expect(source).not.toContain('combat')
  })

  it('keeps the Session table error callback stable across parent renders', () => {
    const source = readFileSync(new URL('./RoomSessionPage.tsx', import.meta.url), 'utf8')
    expect(source).toContain('const handleSessionTableError = useCallback(')
    expect(source).toContain('onError={handleSessionTableError}')
    expect(source).not.toContain('onError={(cause)')
  })

  it('keeps the desktop Session table wider than the legacy Room workspace card', () => {
    const source = readFileSync(new URL('./sessionTable.css', import.meta.url), 'utf8')
    expect(source).toContain('.room-workspace-card.session-table-card')
    expect(source).toContain('width: min(1180px, 100%);')
    expect(source).toContain('@media (max-width: 1080px)')
  })

  it('does not let a missing Lobby take down the Session surface', () => {
    const source = readFileSync(new URL('./RoomSessionPage.tsx', import.meta.url), 'utf8')
    expect(source).toContain('getLobby(roomId, campaignId, token).catch(() => null)')
    expect(source.match(/optionalLobby\(\)/g) ?? []).toHaveLength(2)
    expect(source).not.toContain('getLobby(roomId, campaignId, token),')
    expect(source).toContain('if (!snapshot) {')
    expect(source).not.toContain('if (!snapshot || !lobby)')
    expect(source).toContain('nextResume.caller_access_session_id')
    expect(source).not.toContain('lobby.caller_access_session_id')
    expect(source).not.toContain('ready')
    expect(source).not.toContain('spawn')
    expect(source).not.toContain('combat')
  })
})
