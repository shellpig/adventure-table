import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type { CombatAdjudicationView, CombatDetailView, CombatEntryView } from '../../api/combat'
import { SessionCombatAdjudicationPanel } from './SessionCombatAdjudicationPanel'
import { sessionCopy } from './sessionCopy'

vi.mock('../../api/combat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/combat')>()
  return {
    ...actual,
    adjudicateAttackRange: vi.fn(),
    adjudicateSpecialAttack: vi.fn(),
    resolveAdjudication: vi.fn(),
  }
})

function entry(id: string, name: string): CombatEntryView {
  return {
    id,
    subject_kind: id === 'entry-player' ? 'character' : 'monster',
    character_id: id === 'entry-player' ? 'char-player' : null,
    monster_instance_id: id === 'entry-player' ? null : `monster-${id}`,
    display_name: name,
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
  }
}

const detail: CombatDetailView = {
  id: 'combat-1',
  campaign_id: 'campaign-1',
  mode: 'quick',
  status: 'running',
  round_number: 1,
  current_turn_entry_id: 'entry-player',
  revision: 1,
  entries: [entry('entry-player', 'Mira'), entry('entry-enemy', 'Goblin')],
  combatants: [],
}

function item(
  actionId: string,
  kind: CombatAdjudicationView['kind'],
  options?: Partial<CombatAdjudicationView>,
): CombatAdjudicationView {
  return {
    action_id: actionId,
    kind,
    status: 'pending',
    subject_entry_id: 'entry-player',
    subject_seat_id: 'seat-player',
    proposed_target_entry_ids: ['entry-enemy'],
    question: null,
    decision: null,
    note: null,
    dm_hints: null,
    created_at: '2026-09-17T00:00:00Z',
    ...options,
  }
}

function renderPanel(adjudications: CombatAdjudicationView[]): string {
  return renderToStaticMarkup(
    <SessionCombatAdjudicationPanel
      combat={detail}
      adjudications={adjudications}
      copy={sessionCopy('en')}
      roomId="room"
      campaignId="campaign"
      sessionId="session"
      token="token"
      onError={() => undefined}
      refresh={() => undefined}
    />,
  )
}

describe('SessionCombatAdjudicationPanel', () => {
  it('renders range controls and DM hints', () => {
    const copy = sessionCopy('en')
    const markup = renderPanel([
      item('range-1', 'range', { dm_hints: { target_ac: 15 } }),
    ])

    expect(markup).toContain('data-adjudication-kind="range"')
    expect(markup).toContain(copy.combatInRange)
    expect(markup).toContain(copy.combatOutOfRange)
    expect(markup).toContain('target_ac')
    expect(markup).toContain('15')
  })

  it('renders reach adjudication with in-reach and out-of-reach controls', () => {
    const copy = sessionCopy('en')
    const markup = renderPanel([item('reach-1', 'reach')])

    expect(markup).toContain('data-adjudication-kind="reach"')
    expect(markup).toContain(copy.combatInReach)
    expect(markup).toContain(copy.combatOutOfReach)
  })

  it('renders opportunity attack trigger controls', () => {
    const copy = sessionCopy('en')
    const markup = renderPanel([
      item('oa-1', 'opportunity_attack', { question: 'Does movement trigger the reaction?' }),
    ])

    expect(markup).toContain('data-adjudication-kind="opportunity_attack"')
    expect(markup).toContain(copy.combatTrigger)
    expect(markup).toContain(copy.combatNoTrigger)
  })

  it('renders a required ruling textarea for special adjudication', () => {
    const copy = sessionCopy('en')
    const markup = renderPanel([
      item('special-1', 'special', { question: 'How does the improvised action resolve?' }),
    ])

    expect(markup).toContain('data-adjudication-kind="special"')
    expect(markup).toContain('<textarea')
    expect(markup).toContain('required=""')
    expect(markup).toContain(copy.combatRuling)
  })

  it('leaves affected-target adjudication control-less for E10d', () => {
    const markup = renderPanel([item('aoe-1', 'affected_targets')])

    expect(markup).toContain('data-adjudication-kind="affected_targets"')
    expect(markup).not.toContain('<button')
  })

  it('renders the empty state when there are no pending adjudications', () => {
    const copy = sessionCopy('en')
    const markup = renderPanel([])

    expect(markup).toContain('data-combat-adjudications="true"')
    expect(markup).toContain(copy.combatAdjudicationEmpty)
  })
})
