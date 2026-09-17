import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { CombatDetailView, CombatEntryView } from '../../api/combat'
import { SessionCombatStage } from './SessionCombatStage'
import { sessionCopy } from './sessionCopy'

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

const entryMira = makeEntry('entry-mira', 'Mira', 'char-mira', 1)
const entryGoblin = makeEntry('entry-goblin', 'Goblin Scout', null, 2)
const entryHidden = makeEntry('entry-lurker', 'Ambush Lurker', null, 3)

const sharedEntries = [entryMira, entryGoblin, entryHidden]

const dmCombatDetail: CombatDetailView = {
  id: 'combat-1',
  campaign_id: 'camp-1',
  mode: 'quick',
  status: 'running',
  round_number: 2,
  current_turn_entry_id: 'entry-goblin',
  revision: 3,
  entries: sharedEntries,
  combatants: [
    {
      entry_id: 'entry-mira',
      subject_kind: 'character',
      is_hostile: false,
      projection: {
        id: 'char-mira',
        kind: 'character',
        name: 'Mira',
        current_hp: 24,
        max_hp: 24,
        temp_hp: 0,
        armor_class: 14,
        combat_status: 'active',
        conditions: [],
        effects: [],
      },
    },
    {
      entry_id: 'entry-goblin',
      subject_kind: 'monster',
      is_hostile: true,
      projection: {
        id: 'inst-goblin',
        kind: 'monster',
        name: 'Goblin Scout',
        current_hp: 7,
        max_hp: 7,
        temp_hp: 0,
        armor_class: 15,
        combat_status: 'active',
        dm_notes: 'Secretly carrying a magical key',
        position_note: 'Behind barrels',
        conditions: ['frightened'],
        effects: [],
      },
    },
    {
      entry_id: 'entry-lurker',
      subject_kind: 'monster',
      is_hostile: true,
      projection: {
        id: 'inst-hidden',
        kind: 'monster',
        name: 'Ambush Lurker',
        current_hp: 11,
        max_hp: 11,
        armor_class: 13,
        combat_status: 'active',
        conditions: [],
        effects: [],
      },
    },
  ],
}

const playerCombatDetail: CombatDetailView = {
  id: 'combat-1',
  campaign_id: 'camp-1',
  mode: 'quick',
  status: 'running',
  round_number: 2,
  current_turn_entry_id: 'entry-goblin',
  revision: 3,
  entries: sharedEntries,
  combatants: [
    {
      entry_id: 'entry-mira',
      subject_kind: 'character',
      is_hostile: false,
      projection: {
        id: 'char-mira',
        kind: 'character',
        name: 'Mira',
        current_hp: 24,
        max_hp: 24,
        temp_hp: 0,
        armor_class: 14,
        combat_status: 'active',
        conditions: [],
        effects: [],
      },
    },
    {
      entry_id: 'entry-goblin',
      subject_kind: 'monster',
      is_hostile: true,
      projection: {
        id: 'inst-goblin',
        kind: 'monster',
        name: 'Goblin Scout',
        combat_status: 'active',
        injury_level: 'wounded',
        conditions: ['frightened'],
        effects: [],
      },
    },
    // entry-hidden is omitted from player combatants because it is a hidden enemy
  ],
}

describe('SessionCombatStage component', () => {
  const copyZh = sessionCopy('zh-TW')
  const copyEn = sessionCopy('en')

  it('(a) renders full DM view with exact HP, AC, round number, and current turn name', () => {
    const markup = renderToStaticMarkup(
      <SessionCombatStage combat={dmCombatDetail} myEntryIds={['entry-mira']} copy={copyEn} />,
    )

    expect(markup).toContain('Round 2')
    expect(markup).toContain('Goblin Scout')
    expect(markup).toContain('7/7')
    expect(markup).toContain('15')
    expect(markup).toContain('Secretly carrying a magical key')
    expect(markup).toContain('Behind barrels')
    expect(markup).toContain('data-combat-round="2"')
    expect(markup).toContain('data-combat-current-turn="Goblin Scout"')
  })

  it('(b) renders Player view with enemy secrecy (wounded label, own HP, no enemy HP/AC, no dm_notes, no ?)', () => {
    const markup = renderToStaticMarkup(
      <SessionCombatStage combat={playerCombatDetail} myEntryIds={['entry-mira']} copy={copyEn} />,
    )

    // Player's own character has exact HP and AC
    expect(markup).toContain('24/24')
    expect(markup).toContain('14')

    // Enemy shows wounded injury level
    expect(markup).toContain(copyEn.combatInjuryWounded)

    // Enemy exact numbers and secrets are NOT present
    expect(markup).not.toContain('7/7')
    expect(markup).not.toContain('Secretly carrying a magical key')
    expect(markup).not.toContain('dm_notes')
    expect(markup).not.toContain('DM Notes')

    // No fake precision or unknown placeholders
    expect(markup).not.toContain('?')
    expect(markup).not.toContain('unknown')
    expect(markup).not.toContain('hidden')
  })

  it('(c) shows position note only when present and non-empty', () => {
    const withoutNote = renderToStaticMarkup(
      <SessionCombatStage combat={playerCombatDetail} myEntryIds={['entry-mira']} copy={copyZh} />,
    )
    expect(withoutNote).not.toContain(copyZh.combatPositionNote)

    const withNote = renderToStaticMarkup(
      <SessionCombatStage combat={dmCombatDetail} myEntryIds={['entry-mira']} copy={copyZh} />,
    )
    expect(withNote).toContain(copyZh.combatPositionNote)
    expect(withNote).toContain('Behind barrels')
  })

  it('(d) shows your-turn badge when current turn is in myEntryIds, and omits it otherwise', () => {
    const notMyTurn = renderToStaticMarkup(
      <SessionCombatStage combat={dmCombatDetail} myEntryIds={['entry-mira']} copy={copyEn} />,
    )
    expect(notMyTurn).not.toContain(copyEn.combatYourTurn)

    const myTurnCombat: CombatDetailView = {
      ...dmCombatDetail,
      current_turn_entry_id: 'entry-mira',
    }
    const isMyTurn = renderToStaticMarkup(
      <SessionCombatStage combat={myTurnCombat} myEntryIds={['entry-mira']} copy={copyEn} />,
    )
    expect(isMyTurn).toContain(copyEn.combatYourTurn)
  })

  it('(e) renders display_name row in initiative list even when entry has no combatant detail', () => {
    const markup = renderToStaticMarkup(
      <SessionCombatStage combat={playerCombatDetail} myEntryIds={['entry-mira']} copy={copyEn} />,
    )
    // entry-hidden is omitted from playerCombatDetail.combatants, but in initiative list:
    expect(markup).toContain('Ambush Lurker')
  })
})
