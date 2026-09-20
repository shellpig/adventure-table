import { renderToStaticMarkup } from 'react-dom/server'
import type { ComponentProps, ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { LocaleProvider } from '../../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY } from '../../i18n/locale'

import type { RoomCharacterSummary } from '../../api/campaigns'
import type { CampaignSeat } from '../../api/seats'
import type { SessionSnapshot, TableEvent } from '../../api/sessions'
import { SessionTableSurface } from './SessionTableSurface'
import { sessionCopy } from './sessionCopy'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const SESSION_ID = '30000000-0000-4000-8000-000000000001'
const DM_SEAT = '40000000-0000-4000-8000-000000000001'
const MIRA_SEAT = '40000000-0000-4000-8000-000000000002'
const SERENA_SEAT = '40000000-0000-4000-8000-000000000003'
const MIRA_CHARACTER = '50000000-0000-4000-8000-000000000001'
const SERENA_CHARACTER = '50000000-0000-4000-8000-000000000002'
const NOW = '2026-09-09T00:00:00Z'

function renderSurface(element: ReactElement<ComponentProps<typeof SessionTableSurface>>) {
  const client = new QueryClient()
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <LocaleProvider
        storage={{
          getItem: (key) => key === LOCALE_STORAGE_KEY ? element.props.copy.locale : null,
          setItem: () => undefined,
        }}
        documentTarget={null}
      >
        {element}
      </LocaleProvider>
    </QueryClientProvider>,
  )
}

const snapshot: SessionSnapshot = {
  id: SESSION_ID,
  campaign_id: CAMPAIGN_ID,
  status: 'active',
  dm_seat_id: DM_SEAT,
  dm_controller_access_session_id: 'dm-access',
  started_at: NOW,
  ended_at: null,
  participants: [
    {
      id: 'participant-mira',
      seat_id: MIRA_SEAT,
      role: 'player',
      controller_kind_at_join: 'human',
      controller_access_session_id_at_join: 'mira-access',
      active_character_id: MIRA_CHARACTER,
    },
    {
      id: 'participant-serena',
      seat_id: SERENA_SEAT,
      role: 'player',
      controller_kind_at_join: 'human',
      controller_access_session_id_at_join: 'serena-access',
      active_character_id: SERENA_CHARACTER,
    },
  ],
}

function seat(id: string, label: string): CampaignSeat {
  return {
    id,
    campaign_id: CAMPAIGN_ID,
    role: id === DM_SEAT ? 'dm' : 'player',
    label,
    controller_kind: 'human',
    controller_access_session_id: `${label.toLowerCase()}-access`,
    controller_display_name: label,
    controller_authority: id === DM_SEAT ? 'dm' : 'member',
    presence: 'connected',
    selected_character_id: null,
    archived_at: null,
    created_at: NOW,
    updated_at: NOW,
  }
}

const seats = [
  seat(DM_SEAT, 'Dungeon Master'),
  seat(MIRA_SEAT, 'Mira Player'),
  seat(SERENA_SEAT, 'Serena Player'),
]

const characters: RoomCharacterSummary[] = [
  { id: MIRA_CHARACTER, name: 'Mira', level: 3, class_summary: 'Rogue 3', version_no: 1 },
  { id: SERENA_CHARACTER, name: 'Serena', level: 3, class_summary: 'Wizard 3', version_no: 1 },
]

function explorationEvent(
  seq: number,
  kind: 'exploration.ooc' | 'exploration.whisper_dm',
  actingSeatId: string,
  text: string,
): TableEvent {
  return {
    id: `60000000-0000-4000-8000-${String(seq).padStart(12, '0')}`,
    session_id: SESSION_ID,
    seq,
    kind,
    acting_seat_id: actingSeatId,
    subject_seat_id: null,
    subject_character_id: null,
    execution_mode: 'self',
    visibility: kind === 'exploration.whisper_dm' ? 'seat_private' : 'public',
    recipient_seat_ids: kind === 'exploration.whisper_dm' ? [actingSeatId] : [],
    payload_version: 1,
    payload: { text },
    created_at: NOW,
  }
}

function rollRequestedEvent(): TableEvent {
  return {
    id: '60000000-0000-4000-8000-000000000003',
    session_id: SESSION_ID,
    seq: 3,
    kind: 'roll.requested',
    acting_seat_id: DM_SEAT,
    subject_seat_id: null,
    subject_character_id: null,
    execution_mode: 'self',
    visibility: 'seat_private',
    recipient_seat_ids: [MIRA_SEAT, SERENA_SEAT],
    payload_version: 1,
    payload: {
      roll_group_id: '70000000-0000-4000-8000-000000000001',
      roll_request_ids: [
        '80000000-0000-4000-8000-000000000001',
        '80000000-0000-4000-8000-000000000002',
      ],
      request_type: 'skill',
      ability_ref: null,
      skill_ref: 'srd5.1:skill:investigation',
      modifier_mode: 'advantage',
      flat_adjustment: -1,
      visibility: 'roller_and_dm',
      label: 'Search the door',
      dc: 12,
    },
    created_at: NOW,
  }
}

describe('SessionTableSurface message presentation', () => {
  it('renders one structured roll.requested prompt in chat without exposing DC', () => {
    for (const locale of ['zh-TW', 'en'] as const) {
      const markup = renderSurface(
        <SessionTableSurface
          roomId={ROOM_ID}
          campaignId={CAMPAIGN_ID}
          sessionId={SESSION_ID}
          token="room-token"
          snapshot={snapshot}
          seats={seats}
          characters={characters}
          callerAccessSessionId="dm-access"
          isCurrentDm={true}
          initialStage={null}
          events={[rollRequestedEvent()]}
          olderSessions={[]}
          historyExhausted={false}
          hasOlderHistory={false}
          historyLoading={false}
          onLoadOlder={() => undefined}
          copy={sessionCopy(locale)}
          onError={() => undefined}
        />,
      )

      expect(markup).toContain('session-chat__message--system')
      expect(markup).toContain('Mira')
      expect(markup).toContain('Serena')
      expect(markup).toContain('Investigation')
      expect(markup).toContain('Search the door')
      expect(markup.match(/Search the door/g)).toHaveLength(1)
      expect(markup).not.toContain('DC 12')
    }
  })

  it('renders acting-seat speakers for OOC and Whisper events without subjects', () => {
    const markup = renderSurface(
      <SessionTableSurface
        roomId={ROOM_ID}
        campaignId={CAMPAIGN_ID}
        sessionId={SESSION_ID}
        token="room-token"
        snapshot={snapshot}
        seats={seats}
        characters={characters}
        callerAccessSessionId="dm-access"
        isCurrentDm={true}
        initialStage={null}
        events={[
          explorationEvent(1, 'exploration.ooc', MIRA_SEAT, 'Mira OOC line'),
          explorationEvent(2, 'exploration.whisper_dm', SERENA_SEAT, 'Serena secret'),
        ]}
        olderSessions={[]}
        historyExhausted={false}
        hasOlderHistory={false}
        historyLoading={false}
        onLoadOlder={() => undefined}
        copy={sessionCopy('en')}
        onError={() => undefined}
      />,
    )

    expect(markup).toContain('<strong>Mira Player</strong><span>OOC</span>')
    expect(markup).toContain('Mira OOC line')
    expect(markup).toContain('<strong>Serena Player</strong><span>You + DM only</span>')
    expect(markup).toContain('Serena secret')
  })

  it('renders chat color selector controls and applies stored speaker color to message text and speaker name', () => {
    const originalLocalStorage = globalThis.localStorage
    const store: Record<string, string> = {
      'adventure-table.chat-speaker-colors': JSON.stringify({
        [MIRA_SEAT]: '#38bdf8',
      }),
    }
    Object.defineProperty(globalThis, 'localStorage', {
      value: {
        getItem: (key: string) => store[key] ?? null,
        setItem: (key: string, val: string) => {
          store[key] = val
        },
        removeItem: (key: string) => {
          delete store[key]
        },
        clear: () => {
          for (const k in store) delete store[k]
        },
      },
      configurable: true,
      writable: true,
    })

    try {
      const markup = renderSurface(
        <SessionTableSurface
          roomId={ROOM_ID}
          campaignId={CAMPAIGN_ID}
          sessionId={SESSION_ID}
          token="room-token"
          snapshot={snapshot}
          seats={seats}
          characters={characters}
          callerAccessSessionId="dm-access"
          isCurrentDm={true}
          initialStage={null}
          events={[
            explorationEvent(1, 'exploration.ooc', MIRA_SEAT, 'Mira colored line'),
          ]}
          olderSessions={[]}
          historyExhausted={false}
          hasOlderHistory={false}
          historyLoading={false}
          onLoadOlder={() => undefined}
          copy={sessionCopy('zh-TW')}
          onError={() => undefined}
        />,
      )

      expect(markup).toContain('class="session-chat__color-dot-btn"')
      expect(markup).toContain('class="session-composer__color-btn"')
      expect(markup).toContain('style="color:#38bdf8"')
      expect(markup).toContain('Mira colored line')
    } finally {
      Object.defineProperty(globalThis, 'localStorage', {
        value: originalLocalStorage,
        configurable: true,
        writable: true,
      })
    }
  })
})

describe('SessionTableSurface combat toolbar', () => {
  it('renders Start Combat button for DM when combat is null', () => {
    for (const locale of ['zh-TW', 'en'] as const) {
      const copy = sessionCopy(locale)
      const markup = renderSurface(
        <SessionTableSurface
          roomId={ROOM_ID}
          campaignId={CAMPAIGN_ID}
          sessionId={SESSION_ID}
          token="room-token"
          snapshot={snapshot}
          seats={seats}
          characters={characters}
          callerAccessSessionId="dm-access"
          isCurrentDm={true}
          initialStage={null}
          events={[]}
          olderSessions={[]}
          historyExhausted={false}
          hasOlderHistory={false}
          historyLoading={false}
          onLoadOlder={() => undefined}
          copy={copy}
          onError={() => undefined}
        />,
      )

      expect(markup).toContain('class="session-table__combat-toolbar"')
      expect(markup).toContain(copy.combatStart)
    }
  })

  it('does not render combat toolbar or Start Combat button for Player', () => {
    for (const locale of ['zh-TW', 'en'] as const) {
      const copy = sessionCopy(locale)
      const markup = renderSurface(
        <SessionTableSurface
          roomId={ROOM_ID}
          campaignId={CAMPAIGN_ID}
          sessionId={SESSION_ID}
          token="room-token"
          snapshot={snapshot}
          seats={seats}
          characters={characters}
          callerAccessSessionId="mira-access"
          isCurrentDm={false}
          initialStage={null}
          events={[]}
          olderSessions={[]}
          historyExhausted={false}
          hasOlderHistory={false}
          historyLoading={false}
          onLoadOlder={() => undefined}
          copy={copy}
          onError={() => undefined}
        />,
      )

      expect(markup).not.toContain('class="session-table__combat-toolbar"')
      expect(markup).not.toContain(copy.combatStart)
      expect(markup).not.toContain(copy.combatEnd)
    }
  })
})

describe('SessionTableSurface older history & message capacity', () => {
  it('renders load-older button when hasOlderHistory is true, disabled with loading label when historyLoading is true, and no button when false', () => {
    for (const locale of ['zh-TW', 'en'] as const) {
      const copy = sessionCopy(locale)
      const markup = renderSurface(
        <SessionTableSurface
          roomId={ROOM_ID}
          campaignId={CAMPAIGN_ID}
          sessionId={SESSION_ID}
          token="room-token"
          snapshot={snapshot}
          seats={seats}
          characters={characters}
          callerAccessSessionId="dm-access"
          isCurrentDm={true}
          initialStage={null}
          events={[]}
          olderSessions={[]}
          historyExhausted={false}
          hasOlderHistory={true}
          historyLoading={false}
          onLoadOlder={() => undefined}
          copy={copy}
          onError={() => undefined}
        />,
      )
      expect(markup).toContain('data-chat-load-older')
      expect(markup).toContain('session-chat__load-older')
      expect(markup).toContain(copy.loadOlderMessages)
      expect(markup).not.toContain('disabled=""')
    }

    const loadingMarkup = renderSurface(
      <SessionTableSurface
        roomId={ROOM_ID}
        campaignId={CAMPAIGN_ID}
        sessionId={SESSION_ID}
        token="room-token"
        snapshot={snapshot}
        seats={seats}
        characters={characters}
        callerAccessSessionId="dm-access"
        isCurrentDm={true}
        initialStage={null}
        events={[]}
        olderSessions={[]}
        historyExhausted={false}
        hasOlderHistory={true}
        historyLoading={true}
        onLoadOlder={() => undefined}
        copy={sessionCopy('en')}
        onError={() => undefined}
      />,
    )
    expect(loadingMarkup).toContain('data-chat-load-older')
    expect(loadingMarkup).toContain('disabled=""')
    expect(loadingMarkup).toContain(sessionCopy('en').loadingOlderMessages)

    const noOlderMarkup = renderSurface(
      <SessionTableSurface
        roomId={ROOM_ID}
        campaignId={CAMPAIGN_ID}
        sessionId={SESSION_ID}
        token="room-token"
        snapshot={snapshot}
        seats={seats}
        characters={characters}
        callerAccessSessionId="dm-access"
        isCurrentDm={true}
        initialStage={null}
        events={[]}
        olderSessions={[]}
        historyExhausted={false}
        hasOlderHistory={false}
        historyLoading={false}
        onLoadOlder={() => undefined}
        copy={sessionCopy('en')}
        onError={() => undefined}
      />,
    )
    expect(noOlderMarkup).not.toContain('data-chat-load-older')
    expect(noOlderMarkup).not.toContain('session-chat__load-older')
  })

  it('renders all chat events when there are more than 100 chat events', () => {
    const manyEvents: TableEvent[] = Array.from({ length: 120 }, (_, index) => ({
      id: `60000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
      session_id: SESSION_ID,
      seq: index + 1,
      kind: 'exploration.dialogue',
      acting_seat_id: MIRA_SEAT,
      subject_seat_id: MIRA_SEAT,
      subject_character_id: MIRA_CHARACTER,
      execution_mode: 'self',
      visibility: 'public',
      recipient_seat_ids: [],
      payload_version: 1,
      payload: { text: `Message number ${index + 1}` },
      created_at: NOW,
    }))

    const markup = renderSurface(
      <SessionTableSurface
        roomId={ROOM_ID}
        campaignId={CAMPAIGN_ID}
        sessionId={SESSION_ID}
        token="room-token"
        snapshot={snapshot}
        seats={seats}
        characters={characters}
        callerAccessSessionId="mira-access"
        isCurrentDm={false}
        initialStage={null}
        events={manyEvents}
        olderSessions={[]}
        historyExhausted={false}
        hasOlderHistory={false}
        historyLoading={false}
        onLoadOlder={() => undefined}
        copy={sessionCopy('en')}
        onError={() => undefined}
      />,
    )

    const matches = markup.match(/class="session-chat__message"/g)
    expect(matches).toHaveLength(120)
  })
})


// M05-B: earlier Sessions loaded across the Session boundary render before the
// current Session's messages, separated by a divider, and never feed the Stage /
// Combat projections.
describe('SessionTableSurface cross-Session history', () => {
  const OLDER_A = '30000000-0000-4000-8000-00000000000a'
  const OLDER_B = '30000000-0000-4000-8000-00000000000b'
  const KAEL_CHARACTER = '50000000-0000-4000-8000-000000000009'

  function olderEvent(sessionId: string, seq: number, kind: string, text: string, extra: Partial<TableEvent> = {}): TableEvent {
    return {
      id: `61000000-0000-4000-8000-${String(seq).padStart(12, '0')}`,
      session_id: sessionId,
      seq,
      kind,
      acting_seat_id: MIRA_SEAT,
      subject_seat_id: null,
      subject_character_id: null,
      execution_mode: 'self',
      visibility: 'public',
      recipient_seat_ids: [],
      payload_version: 1,
      payload: { text },
      created_at: '2026-09-01T00:00:00Z',
      ...extra,
    }
  }

  function olderSession(id: string, status: 'ended' | 'abandoned', dmKind: 'human' | 'ai', activeCharacterId: string): SessionSnapshot {
    return {
      ...snapshot,
      id,
      status,
      dm_controller_kind: dmKind,
      started_at: '2026-09-01T10:00:00Z',
      ended_at: '2026-09-01T13:00:00Z',
      participants: [{
        id: `participant-${id}`,
        seat_id: MIRA_SEAT,
        role: 'player',
        controller_kind_at_join: 'ai',
        controller_access_session_id_at_join: null,
        active_character_id: activeCharacterId,
      }],
    }
  }

  function renderHistory(locale: 'zh-TW' | 'en', options: { exhausted: boolean; hasOlder: boolean }) {
    return renderSurface(
      <SessionTableSurface
        roomId={ROOM_ID}
        campaignId={CAMPAIGN_ID}
        sessionId={SESSION_ID}
        token="room-token"
        snapshot={snapshot}
        seats={seats}
        characters={[...characters, { id: KAEL_CHARACTER, name: 'Kael', level: 2, class_summary: 'Fighter 2', version_no: 1 }]}
        callerAccessSessionId="dm-access"
        isCurrentDm={true}
        initialStage={{ session_id: SESSION_ID, revision: 3, text: 'Current stage text', image_id: null, image_media_type: null, image_filename: null }}
        events={[explorationEvent(1, 'exploration.ooc', MIRA_SEAT, 'Current session line')]}
        olderSessions={[
          {
            session: olderSession(OLDER_A, 'ended', 'ai', KAEL_CHARACTER),
            lastEventSeq: 9,
            historyFloorSeq: 0,
            events: [
              olderEvent(OLDER_A, 8, 'exploration.ooc', 'Older A line'),
              olderEvent(OLDER_A, 9, 'stage.updated', 'Older stage text', { payload: { text: 'Older stage text', revision: 99 } }),
              olderEvent(OLDER_A, 7, 'roll.requested', 'older roll', {
                payload: { request_type: 'skill', skill_ref: 'srd5.1:skill:athletics', label: 'Older roll label', visibility: 'public', dc: 15 },
                recipient_seat_ids: [MIRA_SEAT],
                visibility: 'public',
              }),
            ],
          },
          {
            session: olderSession(OLDER_B, 'abandoned', 'human', MIRA_CHARACTER),
            lastEventSeq: 2,
            historyFloorSeq: 0,
            events: [olderEvent(OLDER_B, 2, 'exploration.ooc', 'Older B line')],
          },
        ]}
        historyExhausted={options.exhausted}
        hasOlderHistory={options.hasOlder}
        historyLoading={false}
        onLoadOlder={() => undefined}
        copy={sessionCopy(locale)}
        onError={() => undefined}
      />,
    )
  }

  it('renders older Sessions oldest-first with dividers before the current Session, in both locales', () => {
    for (const locale of ['zh-TW', 'en'] as const) {
      const copy = sessionCopy(locale)
      const markup = renderHistory(locale, { exhausted: true, hasOlder: false })

      const dividerB = markup.indexOf(`data-session-divider="${OLDER_B}"`)
      const lineB = markup.indexOf('Older B line')
      const dividerA = markup.indexOf(`data-session-divider="${OLDER_A}"`)
      const lineA = markup.indexOf('Older A line')
      const current = markup.indexOf('Current session line')
      expect(dividerB).toBeGreaterThan(-1)
      expect(dividerB).toBeLessThan(lineB)
      expect(lineB).toBeLessThan(dividerA)
      expect(dividerA).toBeLessThan(lineA)
      expect(lineA).toBeLessThan(current)

      expect(markup).toContain(copy.sessionDividerAbandoned)
      expect(markup).toContain(copy.sessionDividerEnded)
      expect(markup).toContain(`${copy.dm}: ${copy.dmKindAi}`)
      expect(markup).toContain(`${copy.dm}: ${copy.dmKindHuman}`)
      expect(markup).toContain('role="separator"')
      // Exhausted with nothing more to load: the beginning-of-Campaign note replaces the button.
      expect(markup).toContain(copy.historyStart)
      expect(markup).not.toContain('data-chat-load-older')
    }
  })

  it('resolves older-Session character names from that Session\'s participants', () => {
    const markup = renderHistory('en', { exhausted: false, hasOlder: true })
    // The older roll prompt targets Mira's Seat, which in that Session carried Kael.
    expect(markup).toContain('Kael')
    expect(markup).toContain('Older roll label')
    expect(markup).not.toContain('DC 15')
    // Still loading is possible: the button stays and the beginning note is absent.
    expect(markup).toContain('data-chat-load-older')
    expect(markup).not.toContain(sessionCopy('en').historyStart)
  })

  it('keeps Stage and other projections on the current Session only', () => {
    const markup = renderHistory('en', { exhausted: true, hasOlder: false })
    expect(markup).toContain('Current stage text')
    expect(markup).not.toContain('Older stage text')
  })
})
