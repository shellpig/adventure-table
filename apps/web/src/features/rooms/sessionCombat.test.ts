import { describe, expect, it } from 'vitest'

import { conditionLabel, type CombatDetailView, type CombatEntryView } from '../../api/combat'
import type { TableEvent } from '../../api/sessions'
import {
  combatantFor,
  isCombatEvent,
  latestCombatEventSeq,
  myEntryIds,
  orderedEntries,
} from './sessionCombat'

function makeEvent(seq: number, kind: string): TableEvent {
  return {
    id: `event-${seq}`,
    session_id: 'sess-1',
    seq,
    kind,
    acting_seat_id: null,
    subject_seat_id: null,
    subject_character_id: null,
    execution_mode: 'self',
    visibility: 'public',
    recipient_seat_ids: [],
    payload_version: 1,
    payload: {},
    created_at: '2026-09-17T00:00:00Z',
  }
}

function makeEntry(
  id: string,
  displayName: string,
  characterId: string | null,
  turnOrder: number | null,
  options?: Partial<CombatEntryView>,
): CombatEntryView {
  return {
    id,
    subject_kind: characterId ? 'character' : 'monster',
    character_id: characterId,
    monster_instance_id: characterId ? null : `monster-inst-${id}`,
    display_name: displayName,
    status: 'active',
    initiative_group_key: null,
    initiative_roll_request_id: null,
    initiative_roll_result_id: null,
    initiative_total: turnOrder !== null ? 10 + turnOrder : null,
    turn_order: turnOrder,
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

describe('sessionCombat helpers', () => {
  it('identifies combat events correctly with isCombatEvent', () => {
    expect(isCombatEvent(makeEvent(1, 'combat.started'))).toBe(true)
    expect(isCombatEvent(makeEvent(2, 'combat.turn_started'))).toBe(true)
    expect(isCombatEvent(makeEvent(3, 'combat.damage_applied'))).toBe(true)
    expect(isCombatEvent(makeEvent(4, 'exploration.action'))).toBe(false)
    expect(isCombatEvent(makeEvent(5, 'roll.requested'))).toBe(false)
    expect(isCombatEvent(makeEvent(6, 'stage.updated'))).toBe(false)
  })

  it('determines the latest combat event sequence number', () => {
    expect(latestCombatEventSeq([])).toBe(0)

    const events = [
      makeEvent(1, 'combat.started'),
      makeEvent(2, 'exploration.action'),
      makeEvent(5, 'combat.turn_started'),
      makeEvent(8, 'exploration.dialogue'),
      makeEvent(4, 'combat.action_declared'),
    ]
    expect(latestCombatEventSeq(events)).toBe(5)

    const nonCombatEvents = [
      makeEvent(10, 'exploration.action'),
      makeEvent(20, 'stage.updated'),
    ]
    expect(latestCombatEventSeq(nonCombatEvents)).toBe(0)
  })

  it('sorts entries by turn_order ascending and appends awaiting entries in original order', () => {
    const entryAwaiting1 = makeEntry('entry-wait-1', 'Awaiting 1', 'char-1', null)
    const entrySecond = makeEntry('entry-2', 'Second', 'char-2', 2)
    const entryFirst = makeEntry('entry-1', 'First', null, 1)
    const entryAwaiting2 = makeEntry('entry-wait-2', 'Awaiting 2', null, null)
    const entryThird = makeEntry('entry-3', 'Third', 'char-3', 3)

    const detail: CombatDetailView = {
      id: 'combat-1',
      campaign_id: 'camp-1',
      mode: 'quick',
      status: 'running',
      round_number: 1,
      current_turn_entry_id: 'entry-1',
      revision: 1,
      entries: [entryAwaiting1, entrySecond, entryFirst, entryAwaiting2, entryThird],
      combatants: [],
    }

    const ordered = orderedEntries(detail)
    expect(ordered.map((e) => e.id)).toEqual([
      'entry-1',
      'entry-2',
      'entry-3',
      'entry-wait-1',
      'entry-wait-2',
    ])
    expect(orderedEntries(null)).toEqual([])
  })

  it('extracts myEntryIds according to controlled character IDs', () => {
    const entryMira = makeEntry('entry-mira', 'Mira', 'char-mira', 1)
    const entrySerena = makeEntry('entry-serena', 'Serena', 'char-serena', 2)
    const entryGoblin = makeEntry('entry-goblin', 'Goblin', null, 3)

    const detail: CombatDetailView = {
      id: 'combat-1',
      campaign_id: 'camp-1',
      mode: 'quick',
      status: 'running',
      round_number: 1,
      current_turn_entry_id: 'entry-mira',
      revision: 1,
      entries: [entryMira, entrySerena, entryGoblin],
      combatants: [],
    }

    expect(myEntryIds(detail, ['char-mira'])).toEqual(['entry-mira'])
    expect(myEntryIds(detail, ['char-mira', 'char-serena'])).toEqual(['entry-mira', 'entry-serena'])
    expect(myEntryIds(detail, ['char-other'])).toEqual([])
    expect(myEntryIds(null, ['char-mira'])).toEqual([])
  })

  it('finds combatant detail by entry ID', () => {
    const detail: CombatDetailView = {
      id: 'combat-1',
      campaign_id: 'camp-1',
      mode: 'quick',
      status: 'running',
      round_number: 1,
      current_turn_entry_id: 'entry-1',
      revision: 1,
      entries: [makeEntry('entry-1', 'Mira', 'char-mira', 1)],
      combatants: [
        {
          entry_id: 'entry-1',
          subject_kind: 'character',
          is_hostile: false,
          projection: {
            id: 'proj-1',
            kind: 'character',
            name: 'Mira',
            combat_status: 'active',
            conditions: [],
            effects: [],
          },
        },
      ],
    }

    expect(combatantFor(detail, 'entry-1')?.projection.name).toBe('Mira')
    expect(combatantFor(detail, 'entry-hidden')).toBeUndefined()
    expect(combatantFor(null, 'entry-1')).toBeUndefined()
  })

  it('extracts label from string or object condition/effect items', () => {
    expect(conditionLabel('poisoned')).toBe('poisoned')
    expect(conditionLabel({ condition_ref: 'blinded' })).toBe('blinded')
    expect(conditionLabel({ tag: 'shield_spell' })).toBe('shield_spell')
    expect(conditionLabel({})).toBe('')
  })

})
