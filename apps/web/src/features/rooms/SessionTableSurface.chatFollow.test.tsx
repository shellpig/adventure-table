import { renderToStaticMarkup } from 'react-dom/server'
import type { ComponentProps, ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { LocaleProvider } from '../../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY } from '../../i18n/locale'

import type { RoomCharacterSummary } from '../../api/campaigns'
import type { CampaignSeat } from '../../api/seats'
import type { SessionSnapshot, TableEvent } from '../../api/sessions'
import { ChatJumpButton, SessionTableSurface } from './SessionTableSurface'
import { sessionCopy } from './sessionCopy'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const SESSION_ID = '30000000-0000-4000-8000-000000000001'
const DM_SEAT = '40000000-0000-4000-8000-000000000001'
const MIRA_SEAT = '40000000-0000-4000-8000-000000000002'
const MIRA_CHARACTER = '50000000-0000-4000-8000-000000000001'
const NOW = '2026-09-09T00:00:00Z'

function renderSurface(element: ReactElement<ComponentProps<typeof SessionTableSurface>>) {
  const client = new QueryClient()
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <LocaleProvider
        storage={{
          getItem: (key) => (key === LOCALE_STORAGE_KEY ? element.props.copy.locale : null),
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
  ],
}

const seats: CampaignSeat[] = [
  {
    id: DM_SEAT,
    campaign_id: CAMPAIGN_ID,
    role: 'dm',
    label: 'Dungeon Master',
    controller_kind: 'human',
    controller_access_session_id: 'dm-access',
    controller_display_name: 'Dungeon Master',
    controller_authority: 'dm',
    presence: 'connected',
    selected_character_id: null,
    archived_at: null,
    created_at: NOW,
    updated_at: NOW,
  },
  {
    id: MIRA_SEAT,
    campaign_id: CAMPAIGN_ID,
    role: 'player',
    label: 'Mira Player',
    controller_kind: 'human',
    controller_access_session_id: 'mira-access',
    controller_display_name: 'Mira Player',
    controller_authority: 'member',
    presence: 'connected',
    selected_character_id: null,
    archived_at: null,
    created_at: NOW,
    updated_at: NOW,
  },
]

const characters: RoomCharacterSummary[] = [
  { id: MIRA_CHARACTER, name: 'Mira', level: 3, class_summary: 'Rogue 3', version_no: 1 },
]

function sampleChatEvent(seq: number, text: string): TableEvent {
  return {
    id: `60000000-0000-4000-8000-${String(seq).padStart(12, '0')}`,
    session_id: SESSION_ID,
    seq,
    kind: 'exploration.dialogue',
    acting_seat_id: MIRA_SEAT,
    subject_seat_id: MIRA_SEAT,
    subject_character_id: MIRA_CHARACTER,
    execution_mode: 'self',
    visibility: 'public',
    recipient_seat_ids: [],
    payload_version: 1,
    payload: { text },
    created_at: NOW,
  }
}

describe('SessionTableSurface chat follow & jump control', () => {
  it('does not render the jump button on initial render when followChat is true', () => {
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
          callerAccessSessionId="mira-access"
          isCurrentDm={false}
          initialStage={null}
          events={[sampleChatEvent(1, 'Hello table'), sampleChatEvent(2, 'Second message')]}
          hasOlderHistory={false}
          historyLoading={false}
          onLoadOlder={() => undefined}
          copy={sessionCopy(locale)}
          onError={() => undefined}
        />,
      )

      expect(markup).not.toContain('data-chat-jump')
      expect(markup).not.toContain('session-chat__jump')
    }
  })

  it('renders ChatJumpButton with count and localized label', () => {
    const enMarkup = renderToStaticMarkup(
      <ChatJumpButton
        count={3}
        copy={sessionCopy('en')}
        onClick={() => undefined}
      />,
    )
    expect(enMarkup).toContain('data-chat-jump')
    expect(enMarkup).toContain('session-chat__jump')
    expect(enMarkup).toContain('3 new messages ↓')

    const zhMarkup = renderToStaticMarkup(
      <ChatJumpButton
        count={3}
        copy={sessionCopy('zh-TW')}
        onClick={() => undefined}
      />,
    )
    expect(zhMarkup).toContain('data-chat-jump')
    expect(zhMarkup).toContain('session-chat__jump')
    expect(zhMarkup).toContain('3 則新訊息 ↓')
  })
})
