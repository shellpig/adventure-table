import { describe, expect, it } from 'vitest'

import {
  conditionLabel,
  type CombatDetailView,
  type CombatEntryView,
  type ReactionWindowView,
} from '../../api/combat'
import type { TableEvent } from '../../api/sessions'
import {
  actingEntryId,
  combatantFor,
  combatEntryDisplayName,
  eligibleReactionEntry,
  isCombatEvent,
  latestCombatEventSeq,
  myEntryIds,
  orderedEntries,
  pendingCombatRollHandler,
} from './sessionCombat'

function makeEvent(seq: number, kind: string, payload: Record<string, unknown> = {}): TableEvent {
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
    payload,
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
    dodging: false,
    pending_reaction_state: {},
    ...options,
  }
}

function makeDetail(status: string, currentTurnEntryId: string | null): CombatDetailView {
  return {
    id: 'combat-1',
    campaign_id: 'camp-1',
    mode: 'quick',
    status,
    round_number: status === 'running' ? 1 : null,
    current_turn_entry_id: currentTurnEntryId,
    revision: 1,
    entries: [
      makeEntry('entry-mira', 'Mira', 'char-mira', 1),
      makeEntry('entry-goblin', 'Goblin', null, 2),
    ],
    combatants: [],
  }
}

function reactionWindow(eligibleEntryIds: string[]): ReactionWindowView {
  return {
    window_id: 'reaction-1',
    entry_id: 'entry-owner',
    kind: 'opportunity_attack',
    reason: 'Enemy leaves reach',
    source_entry_id: 'entry-goblin',
    status: 'open',
    eligible_entry_ids: eligibleEntryIds,
    target_entry_id: 'entry-goblin',
    safe_payload: null,
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
    // Initiative / attack rolls stay P3 roll.* events but carry combat_id, so they must refetch Combat state.
    expect(isCombatEvent(makeEvent(7, 'roll.requested', { combat_id: 'combat-1' }))).toBe(true)
    expect(isCombatEvent(makeEvent(8, 'roll.resolved', { combat_id: 'combat-1' }))).toBe(true)
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
    expect(latestCombatEventSeq([
      makeEvent(10, 'exploration.action'),
      makeEvent(20, 'stage.updated'),
    ])).toBe(0)
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
    expect(orderedEntries(detail).map((entry) => entry.id)).toEqual([
      'entry-1', 'entry-2', 'entry-3', 'entry-wait-1', 'entry-wait-2',
    ])
    expect(orderedEntries(null)).toEqual([])
  })

  it('extracts myEntryIds according to controlled character IDs', () => {
    const detail: CombatDetailView = {
      id: 'combat-1',
      campaign_id: 'camp-1',
      mode: 'quick',
      status: 'running',
      round_number: 1,
      current_turn_entry_id: 'entry-mira',
      revision: 1,
      entries: [
        makeEntry('entry-mira', 'Mira', 'char-mira', 1),
        makeEntry('entry-serena', 'Serena', 'char-serena', 2),
        makeEntry('entry-goblin', 'Goblin', null, 3),
      ],
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
      combatants: [{
        entry_id: 'entry-1',
        subject_kind: 'character',
        is_hostile: false,
        projection: {
          id: 'proj-1', kind: 'character', name: 'Mira', combat_status: 'active', conditions: [], effects: [],
        },
      }],
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

  it('dispatches every pending combat roll type and rejects initiative or unknown types', () => {
    const handlers = {
      attack: async () => undefined,
      saving_throw: async () => undefined,
      death_save: async () => undefined,
      concentration: async () => undefined,
      grapple: async () => undefined,
      shove: async () => undefined,
      escape_grapple: async () => undefined,
    }
    expect(pendingCombatRollHandler('attack', handlers)).toBe(handlers.attack)
    expect(pendingCombatRollHandler('saving_throw', handlers)).toBe(handlers.saving_throw)
    expect(pendingCombatRollHandler('death_save', handlers)).toBe(handlers.death_save)
    expect(pendingCombatRollHandler('concentration', handlers)).toBe(handlers.concentration)
    expect(pendingCombatRollHandler('grapple', handlers)).toBe(handlers.grapple)
    expect(pendingCombatRollHandler('shove', handlers)).toBe(handlers.shove)
    expect(pendingCombatRollHandler('escape_grapple', handlers)).toBe(handlers.escape_grapple)
    expect(pendingCombatRollHandler('initiative', handlers)).toBeUndefined()
    expect(pendingCombatRollHandler('other', handlers)).toBeUndefined()
  })

  it('selects the first caller-controlled eligible reaction entry', () => {
    const window = reactionWindow(['entry-goblin', 'entry-mira', 'entry-serena'])
    expect(eligibleReactionEntry(window, ['entry-mira', 'entry-serena'])).toBe('entry-mira')
    expect(eligibleReactionEntry(window, ['entry-goblin', 'entry-mira'])).toBe('entry-goblin')
    expect(eligibleReactionEntry(window, ['entry-other'])).toBeNull()
    expect(eligibleReactionEntry(reactionWindow([]), ['entry-mira'])).toBeNull()
  })

  it('returns own current turn entry for a running Player combat', () => {
    expect(actingEntryId(makeDetail('running', 'entry-mira'), ['entry-mira'], false)).toBe('entry-mira')
  })

  it('returns any current turn entry for the current DM', () => {
    expect(actingEntryId(makeDetail('running', 'entry-goblin'), ['entry-mira'], true)).toBe('entry-goblin')
  })

  it('returns null when the running turn belongs to another entry', () => {
    expect(actingEntryId(makeDetail('running', 'entry-goblin'), ['entry-mira'], false)).toBeNull()
  })

  it('returns null before initiative is finalized', () => {
    expect(actingEntryId(makeDetail('initiative_pending', null), ['entry-mira'], true)).toBeNull()
  })
})

describe('M07-C combatEntryDisplayName (name_presentation)', () => {
  function detailWithPresentation(
    presentation: Record<string, unknown> | undefined,
    projectionName: string,
  ): { detail: CombatDetailView; entry: CombatEntryView } {
    const entry = makeEntry('entry-goblin', 'Goblin', null, 2)
    const detail: CombatDetailView = {
      ...makeDetail('running', 'entry-goblin'),
      combatants: [
        {
          entry_id: 'entry-goblin',
          subject_kind: 'monster',
          is_hostile: true,
          projection: {
            id: 'inst-goblin',
            kind: 'monster',
            name: projectionName,
            combat_status: 'active',
            conditions: [],
            effects: [],
            ...(presentation === undefined ? {} : { name_presentation: presentation }),
          },
        },
      ],
    }
    return { detail, entry }
  }

  it('uses the current locale snapshot name, then en, then the projection name', () => {
    const { detail, entry } = detailWithPresentation(
      { names: { en: 'Goblin', 'zh-TW': '地精' }, name_is_custom: false },
      'Goblin',
    )
    expect(combatEntryDisplayName(detail, entry, 'zh-TW')).toBe('地精')
    expect(combatEntryDisplayName(detail, entry, 'en')).toBe('Goblin')
    // An unsupported locale falls back to en before the stored name.
    expect(combatEntryDisplayName(detail, entry, 'ja')).toBe('Goblin')
  })

  it('a custom name always wins over any snapshot names', () => {
    const { detail, entry } = detailWithPresentation(
      { names: { en: 'Goblin', 'zh-TW': '地精' }, name_is_custom: true },
      'Boss Goblin',
    )
    expect(combatEntryDisplayName(detail, entry, 'zh-TW')).toBe('Boss Goblin')
    expect(combatEntryDisplayName(detail, entry, 'en')).toBe('Boss Goblin')
  })

  it('falls back to the projection name when the locale snapshot is missing', () => {
    const { detail, entry } = detailWithPresentation(
      { names: {}, name_is_custom: false },
      'Goblin Scout',
    )
    expect(combatEntryDisplayName(detail, entry, 'zh-TW')).toBe('Goblin Scout')
  })

  it('legacy combatants without name_presentation keep existing behaviour', () => {
    const { detail, entry } = detailWithPresentation(undefined, 'Old Goblin')
    expect(combatEntryDisplayName(detail, entry, 'zh-TW')).toBe('Old Goblin')
    // No combatant detail at all (e.g. hidden from this audience): entry name.
    const bare = makeDetail('running', 'entry-goblin')
    const bareEntry = bare.entries.find((e) => e.id === 'entry-goblin')!
    expect(combatEntryDisplayName(bare, bareEntry, 'zh-TW')).toBe('Goblin')
  })
})
