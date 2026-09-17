import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type {
  CombatAdjudicationView,
  CombatDetailView,
  CombatEntryView,
  CombatPendingRollView,
} from '../../api/combat'
import { SessionCombatActionBar } from './SessionCombatActionBar'
import { sessionCopy } from './sessionCopy'

vi.mock('../../api/combat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/combat')>()
  return {
    ...actual,
    listAttacks: vi.fn().mockResolvedValue([]),
    requestAttack: vi.fn(),
    rollAttack: vi.fn(),
  }
})

function makeEntry(
  id: string,
  displayName: string,
  characterId: string | null,
  options?: Partial<CombatEntryView>,
): CombatEntryView {
  return {
    id,
    subject_kind: characterId ? 'character' : 'monster',
    character_id: characterId,
    monster_instance_id: characterId ? null : `monster-${id}`,
    display_name: displayName,
    status: 'active',
    initiative_group_key: null,
    initiative_roll_request_id: null,
    initiative_roll_result_id: null,
    initiative_total: 10,
    turn_order: 1,
    surprised: false,
    action_available: true,
    bonus_action_available: true,
    reaction_available: true,
    attacks_allowed: 1,
    attacks_used: 0,
    ready_state: {},
    pending_reaction_state: {},
    ...options,
  }
}

const playerEntry = makeEntry('entry-player', 'Mira', 'char-mira')
const enemyEntry = makeEntry('entry-enemy', 'Goblin', null, { turn_order: 2 })

function combat(currentTurnEntryId: string): CombatDetailView {
  return {
    id: 'combat-1',
    campaign_id: 'campaign-1',
    mode: 'quick',
    status: 'running',
    round_number: 1,
    current_turn_entry_id: currentTurnEntryId,
    revision: 1,
    entries: [playerEntry, enemyEntry],
    combatants: [],
  }
}

function pendingRoll(id: string, requestType: string): CombatPendingRollView {
  return {
    id,
    roll_group_id: null,
    label: null,
    request_type: requestType,
    target_entry_id: 'entry-player',
    target_seat_id: 'seat-player',
    ability_ref: null,
    dc: null,
    modifier_mode: 'normal',
    status: 'pending',
  }
}

function adjudication(): CombatAdjudicationView {
  return {
    action_id: 'action-range-1',
    kind: 'range',
    status: 'pending',
    subject_entry_id: 'entry-player',
    subject_seat_id: 'seat-player',
    proposed_target_entry_ids: ['entry-enemy'],
    question: null,
    decision: null,
    note: null,
    dm_hints: null,
    created_at: '2026-09-17T00:00:00Z',
  }
}

function renderActionBar(options: {
  detail: CombatDetailView
  isCurrentDm: boolean
  rolls?: CombatPendingRollView[]
  adjudications?: CombatAdjudicationView[]
}): string {
  return renderToStaticMarkup(
    <SessionCombatActionBar
      combat={options.detail}
      myEntryIds={['entry-player']}
      pendingRolls={options.rolls ?? []}
      pendingAdjudications={options.adjudications ?? []}
      copy={sessionCopy('en')}
      roomId="room"
      campaignId="campaign"
      sessionId="session"
      token="token"
      isCurrentDm={options.isCurrentDm}
      onError={() => undefined}
      refresh={() => undefined}
    />,
  )
}

describe('SessionCombatActionBar', () => {
  it('renders Player attack and target selects on own turn without the DM range checkbox', () => {
    const copy = sessionCopy('en')
    const markup = renderActionBar({ detail: combat('entry-player'), isCurrentDm: false })

    expect(markup).toContain('data-combat-action-state="ready"')
    expect(markup).toContain(copy.combatAttackLabel)
    expect(markup).toContain(copy.combatTargetLabel)
    expect(markup).toContain('<select')
    expect(markup).not.toContain(copy.combatRangeConfirmed)
  })

  it('renders waiting state with no attack selects on an enemy turn', () => {
    const markup = renderActionBar({ detail: combat('entry-enemy'), isCurrentDm: false })

    expect(markup).toContain('data-combat-action-state="waiting"')
    expect(markup).not.toContain('<select')
  })

  it('renders the range-confirmed checkbox for the DM on a monster turn', () => {
    const copy = sessionCopy('en')
    const markup = renderActionBar({ detail: combat('entry-enemy'), isCurrentDm: true })

    expect(markup).toContain('data-combat-action-state="ready"')
    expect(markup).toContain('type="checkbox"')
    expect(markup).toContain(copy.combatRangeConfirmed)
  })

  it('renders only pending attack rolls and leaves save rolls for E10c', () => {
    const markup = renderActionBar({
      detail: combat('entry-player'),
      isCurrentDm: false,
      rolls: [pendingRoll('attack-roll-1', 'attack'), pendingRoll('save-roll-1', 'saving_throw')],
    })

    expect(markup).toContain('data-pending-roll="attack-roll-1"')
    expect(markup).not.toContain('data-pending-roll="save-roll-1"')
  })

  it('renders the Player own pending adjudication as read-only', () => {
    const markup = renderActionBar({
      detail: combat('entry-player'),
      isCurrentDm: false,
      adjudications: [adjudication()],
    })

    expect(markup).toContain('data-adjudication-pending="action-range-1"')
  })
})
