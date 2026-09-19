import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type {
  CastableSpellView,
  CombatAdjudicationView,
  CombatDetailView,
  CombatEntryView,
  CombatPendingRollView,
  ReactionWindowView,
} from '../../api/combat'
import {
  SessionCombatActionBar,
  SpellActionFields,
  spellTargetEntries,
} from './SessionCombatActionBar'
import { sessionCopy } from './sessionCopy'

vi.mock('../../api/combat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/combat')>()
  return {
    ...actual,
    castSpell: vi.fn(),
    listAttacks: vi.fn().mockResolvedValue([]),
    listCastableSpells: vi.fn().mockResolvedValue([]),
    proposeAoeSpell: vi.fn(),
    requestAttack: vi.fn(),
    requestSpecialAttack: vi.fn(),
    resolveReaction: vi.fn(),
    rollAttack: vi.fn(),
    rollSavingThrow: vi.fn(),
    rollDeathSave: vi.fn(),
    rollConcentration: vi.fn(),
    rollSpecialAttack: vi.fn(),
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
    dodging: false,
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

function pendingRoll(
  id: string,
  requestType: string,
  options?: Partial<CombatPendingRollView>,
): CombatPendingRollView {
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
    auto_fail: false,
    status: 'pending',
    ...options,
  }
}

function reactionWindow(windowId: string, eligibleEntryIds: string[]): ReactionWindowView {
  return {
    window_id: windowId,
    entry_id: 'entry-player',
    kind: 'opportunity_attack',
    reason: 'Enemy leaves reach',
    source_entry_id: 'entry-enemy',
    status: 'open',
    eligible_entry_ids: eligibleEntryIds,
    target_entry_id: 'entry-enemy',
    safe_payload: { trigger: 'movement' },
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

function spell(
  targeting: CastableSpellView['targeting'],
  options?: Partial<CastableSpellView>,
): CastableSpellView {
  return {
    spell_ref: targeting === 'aoe' ? 'srd5.1:spell:fireball' : 'srd5.1:spell:fire-bolt',
    name: targeting === 'aoe' ? 'Fireball' : 'Fire Bolt',
    level: targeting === 'aoe' ? 3 : 0,
    profile_id: 'wizard',
    concentration: false,
    targeting,
    cast_mode: targeting === 'aoe' ? 'save' : 'attack',
    castable_slot_levels: targeting === 'aoe' ? [3, 4] : [0],
    ...options,
  }
}

function renderActionBar(options: {
  detail: CombatDetailView
  isCurrentDm: boolean
  rolls?: CombatPendingRollView[]
  adjudications?: CombatAdjudicationView[]
  reactions?: ReactionWindowView[]
}): string {
  return renderToStaticMarkup(
    <SessionCombatActionBar
      combat={options.detail}
      myEntryIds={['entry-player']}
      pendingRolls={options.rolls ?? []}
      pendingAdjudications={options.adjudications ?? []}
      reactionEntryIds={options.isCurrentDm ? ['entry-player', 'entry-enemy'] : ['entry-player']}
      reactionWindows={options.reactions ?? []}
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

function renderSpellFields(
  item: CastableSpellView,
  targetEntries: CombatEntryView[] = [enemyEntry],
): string {
  return renderToStaticMarkup(
    <SpellActionFields
      spells={[item]}
      spellRef={item.spell_ref}
      slotLevel={item.castable_slot_levels[0]}
      targetEntryId=""
      targetEntries={targetEntries}
      disabled={false}
      copy={sessionCopy('en')}
      onSpellRefChange={() => undefined}
      onSlotLevelChange={() => undefined}
      onTargetEntryIdChange={() => undefined}
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

  it('tells the Player to wait for the DM once the action is spent on their own turn', () => {
    const copy = sessionCopy('en')
    const spent = combat('entry-player')
    spent.entries = spent.entries.map((entry) =>
      entry.id === 'entry-player' ? { ...entry, action_available: false, attacks_used: 1 } : entry,
    )
    const markup = renderActionBar({ detail: spent, isCurrentDm: false })
    expect(markup).toContain('data-combat-action-spent="true"')
    expect(markup).toContain(copy.combatActionSpentWaitingDm)
    expect(markup).not.toContain('<select')

    const fresh = renderActionBar({ detail: combat('entry-player'), isCurrentDm: false })
    expect(fresh).not.toContain(copy.combatActionSpentWaitingDm)
  })

  it('renders the range-confirmed checkbox for the DM on a monster turn', () => {
    const copy = sessionCopy('en')
    const markup = renderActionBar({ detail: combat('entry-enemy'), isCurrentDm: true })
    expect(markup).toContain('data-combat-action-state="ready"')
    expect(markup).toContain('type="checkbox"')
    expect(markup).toContain(copy.combatRangeConfirmed)
  })

  it('renders every E10c pending roll type and omits initiative rolls', () => {
    const markup = renderActionBar({
      detail: combat('entry-player'),
      isCurrentDm: false,
      rolls: [
        pendingRoll('attack-roll-1', 'attack'),
        pendingRoll('save-roll-1', 'saving_throw'),
        pendingRoll('death-roll-1', 'death_save'),
        pendingRoll('concentration-roll-1', 'concentration'),
        pendingRoll('grapple-roll-1', 'grapple'),
        pendingRoll('shove-roll-1', 'shove'),
        pendingRoll('escape-roll-1', 'escape_grapple'),
        pendingRoll('initiative-roll-1', 'initiative'),
      ],
    })
    for (const id of [
      'attack-roll-1',
      'save-roll-1',
      'death-roll-1',
      'concentration-roll-1',
      'grapple-roll-1',
      'shove-roll-1',
      'escape-roll-1',
    ]) {
      expect(markup).toContain(`data-pending-roll="${id}"`)
    }
    expect(markup).not.toContain('data-pending-roll="initiative-roll-1"')
  })

  it('shows save DC to the DM and omits hidden Player DC', () => {
    const dmMarkup = renderActionBar({
      detail: combat('entry-enemy'),
      isCurrentDm: true,
      rolls: [
        pendingRoll('save-dm', 'saving_throw', {
          label: 'Saving Throw',
          ability_ref: 'dexterity',
          dc: 16,
        }),
      ],
    })
    expect(dmMarkup).toContain('dexterity')
    expect(dmMarkup).toContain('DC 16')
    const playerMarkup = renderActionBar({
      detail: combat('entry-player'),
      isCurrentDm: false,
      rolls: [
        pendingRoll('save-player', 'saving_throw', {
          label: 'Saving Throw',
          ability_ref: 'dexterity',
          dc: null,
        }),
      ],
    })
    expect(playerMarkup).toContain('dexterity')
    expect(playerMarkup).not.toContain('DC 16')
    expect(playerMarkup).not.toContain('DC ?')
  })

  it('marks a pending saving throw that auto-fails and omits the marker otherwise', () => {
    const copy = sessionCopy('en')
    const autoFailMarkup = renderActionBar({
      detail: combat('entry-player'),
      isCurrentDm: false,
      rolls: [
        pendingRoll('save-auto', 'saving_throw', {
          label: 'Saving Throw',
          ability_ref: 'strength',
          auto_fail: true,
        }),
      ],
    })
    expect(autoFailMarkup).toContain(copy.combatSaveAutoFail)
    const plainMarkup = renderActionBar({
      detail: combat('entry-player'),
      isCurrentDm: false,
      rolls: [pendingRoll('save-plain', 'saving_throw', { label: 'Saving Throw', ability_ref: 'strength' })],
    })
    expect(plainMarkup).not.toContain(copy.combatSaveAutoFail)
  })

  it('renders an eligible open reaction with accept and decline controls', () => {
    const copy = sessionCopy('en')
    const markup = renderActionBar({
      detail: combat('entry-player'),
      isCurrentDm: false,
      reactions: [reactionWindow('reaction-1', ['entry-player'])],
    })
    expect(markup).toContain('data-reaction-window="reaction-1"')
    expect(markup).toContain(copy.combatReactionAccept)
    expect(markup).toContain(copy.combatReactionDecline)
    expect(markup).toContain('trigger')
    expect(markup).toContain('movement')
  })

  it('does not render a reaction whose eligible entries the Player does not control', () => {
    const markup = renderActionBar({
      detail: combat('entry-player'),
      isCurrentDm: false,
      reactions: [reactionWindow('reaction-other', ['entry-enemy'])],
    })
    expect(markup).not.toContain('data-reaction-window="reaction-other"')
  })

  it('renders action-kind select with grapple, shove (prone), shove (push), and omits escape when not grappled', () => {
    const copy = sessionCopy('en')
    const markup = renderActionBar({ detail: combat('entry-player'), isCurrentDm: false })
    expect(markup).toContain('data-combat-action-kind="true"')
    expect(markup).toContain(copy.combatActionKindGrapple)
    expect(markup).toContain(copy.combatActionKindShoveProne)
    expect(markup).toContain(copy.combatActionKindShovePush)
    expect(markup).not.toContain(copy.combatActionKindEscapeGrapple)
    expect(markup).not.toContain('value="escape_grapple"')
    expect(markup).toContain(copy.combatActionKindSpell)
  })

  it('renders the escape_grapple option when the acting combatant has the grappled condition', () => {
    const copy = sessionCopy('en')
    const detail = combat('entry-player')
    const grappledDetail: CombatDetailView = {
      ...detail,
      combatants: [
        {
          entry_id: 'entry-player',
          subject_kind: 'character',
          is_hostile: false,
          projection: {
            id: 'combatant-player',
            kind: 'character',
            name: 'Mira',
            combat_status: 'active',
            conditions: ['srd5.1:condition:grappled'],
            effects: [],
          },
        },
      ],
    }
    const markup = renderActionBar({ detail: grappledDetail, isCurrentDm: false })
    expect(markup).toContain('data-combat-action-kind="true"')
    expect(markup).toContain('value="escape_grapple"')
    expect(markup).toContain(copy.combatActionKindEscapeGrapple)
  })

  it('renders a pending roll with request_type escape_grapple with escape label and roll button', () => {
    const copy = sessionCopy('en')
    const markup = renderActionBar({
      detail: combat('entry-player'),
      isCurrentDm: false,
      rolls: [pendingRoll('escape-roll-1', 'escape_grapple')],
    })
    expect(markup).toContain('data-pending-roll="escape-roll-1"')
    expect(markup).toContain(copy.combatRollTypeEscapeGrapple)
  })

  it('renders spell and target selects for a single-target spell', () => {
    const markup = renderSpellFields(spell('single'))
    expect(markup).toContain('data-combat-spell="true"')
    expect(markup).toContain('data-combat-spell-target="true"')
    expect(markup).not.toContain('data-combat-spell-slot="true"')
  })

  it('lists the acting combatant first for a single-target heal spell', () => {
    const healSpell = spell('single', {
      spell_ref: 'srd5.1:spell:cure-wounds',
      name: 'Cure Wounds',
      cast_mode: 'heal',
    })
    const entries = spellTargetEntries(healSpell, playerEntry, [enemyEntry])
    expect(entries).toEqual([playerEntry, enemyEntry])
    const markup = renderSpellFields(healSpell, entries)
    expect(markup).toContain('data-combat-spell-target="true"')
    expect(markup).toContain(`value="${playerEntry.id}"`)
    expect(markup).toContain(playerEntry.display_name)
    expect(markup).toContain(`value="${enemyEntry.id}"`)
    expect(markup).toContain(enemyEntry.display_name)
    const playerIndex = markup.indexOf(`value="${playerEntry.id}"`)
    const enemyIndex = markup.indexOf(`value="${enemyEntry.id}"`)
    expect(playerIndex).toBeLessThan(enemyIndex)
  })

  it('omits the acting combatant for a single-target save spell', () => {
    const saveSpell = spell('single', {
      spell_ref: 'srd5.1:spell:sacred-flame',
      name: 'Sacred Flame',
      cast_mode: 'save',
    })
    const entries = spellTargetEntries(saveSpell, playerEntry, [enemyEntry])
    expect(entries).toEqual([enemyEntry])
    const markup = renderSpellFields(saveSpell, entries)
    expect(markup).toContain('data-combat-spell-target="true"')
    expect(markup).not.toContain(`value="${playerEntry.id}"`)
    expect(markup).toContain(`value="${enemyEntry.id}"`)
  })

  it('renders an AoE spell select and slot level without a target select', () => {
    const markup = renderSpellFields(spell('aoe'))
    expect(markup).toContain('data-combat-spell="true"')
    expect(markup).toContain('data-combat-spell-slot="true"')
    expect(markup).not.toContain('data-combat-spell-target="true"')
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
