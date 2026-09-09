import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

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

describe('SessionTableSurface message presentation', () => {
  it('renders acting-seat speakers for OOC and Whisper events without subjects', () => {
    const markup = renderToStaticMarkup(
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
        copy={sessionCopy('en')}
        onError={() => undefined}
      />,
    )

    expect(markup).toContain('<strong>Mira Player</strong><span>OOC</span>')
    expect(markup).toContain('Mira OOC line')
    expect(markup).toContain('<strong>Serena Player</strong><span>You + DM only</span>')
    expect(markup).toContain('Serena secret')
  })
})
