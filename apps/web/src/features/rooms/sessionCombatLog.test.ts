import { describe, expect, it } from 'vitest'

import type { TableEvent } from '../../api/sessions'
import {
  combatLogContentReferences,
  formatCombatLogEvent,
} from './sessionCombatLog'
import { isSessionChatEvent } from './sessionExploration'

const ENTRY_LABELS: Record<string, string> = {
  hero: 'Aria',
  enemy: 'Goblin',
}

const resolveEntryLabel = (entryId: string) => ENTRY_LABELS[entryId] ?? null
const fallbackContentName = (_reference: string | null | undefined, fallback = '') => fallback

function contentNameResolver(names: Record<string, string>) {
  return (reference: string | null | undefined, fallback = '') =>
    reference ? names[reference] ?? fallback : fallback
}

function event(kind: string, payload: Record<string, unknown> = {}): TableEvent {
  return {
    id: `event-${kind}`,
    session_id: 'session-1',
    seq: 1,
    kind,
    acting_seat_id: null,
    subject_seat_id: null,
    subject_character_id: null,
    execution_mode: null,
    visibility: 'public',
    recipient_seat_ids: [],
    payload_version: 1,
    payload,
    created_at: '2026-09-17T10:00:00Z',
  }
}

function text(presentation: ReturnType<typeof formatCombatLogEvent>): string {
  if (!presentation) return ''
  return [presentation.summary, presentation.detail].filter(Boolean).join(' · ')
}

describe('P4-E E11a compact combat log presentation', () => {
  it('preserves projected runtime attack names and excludes runtime locators from content requests', () => {
    for (const sourceRef of ['inventory:weapon-1', 'inventory:item:weapon-1', 'monster-action:0']) {
      const attack = event('roll.resolved', {
        combat_id: 'combat-1',
        attacker_entry_id: 'hero',
        target_entry_id: 'enemy',
        attack_resolution: {
          attack: { source_ref: sourceRef, name: 'Custom Slash', hit: true },
        },
      })
      expect(combatLogContentReferences([attack])).toEqual([])
      expect(text(formatCombatLogEvent(attack, 'en', resolveEntryLabel, fallbackContentName)))
        .toBe('Aria · Custom Slash · → Goblin · Hit')
    }
  })

  it('localizes canonical spell condition tags and attack source refs without raw English slugs', () => {
    const spell = event('combat.spell_cast_resolved', {
      caster_entry_id: 'hero',
      target_entry_id: 'enemy',
      spell_ref: 'srd5.1:spell:hold-person',
      concentration_started: true,
      domain_events: [
        {
          type: 'condition_applied',
          tag: 'paralyzed',
          effect_id: 'spell-effect:1',
        },
      ],
    })
    const attack = event('roll.resolved', {
      combat_id: 'combat-1',
      attacker_entry_id: 'hero',
      target_entry_id: 'enemy',
      attack_resolution: {
        attack: {
          source_ref: 'srd5.1:equipment:longsword',
          name: 'Longsword',
          total: 18,
          hit: true,
          critical: false,
        },
      },
    })

    const zhNames = contentNameResolver({
      'srd5.1:spell:hold-person': '人類定身術',
      'srd5.1:condition:paralyzed': '麻痺',
      'srd5.1:equipment:longsword': '長劍',
    })
    const enNames = contentNameResolver({
      'srd5.1:spell:hold-person': 'Hold Person',
      'srd5.1:condition:paralyzed': 'Paralyzed',
      'srd5.1:equipment:longsword': 'Longsword',
    })

    expect(text(formatCombatLogEvent(spell, 'zh-TW', resolveEntryLabel, zhNames))).toBe(
      'Aria · 法術: 人類定身術 · → Goblin · 開始專注 · 狀態: 麻痺',
    )
    expect(text(formatCombatLogEvent(spell, 'en', resolveEntryLabel, enNames))).toBe(
      'Aria · Spell: Hold Person · → Goblin · Concentration started · Condition: Paralyzed',
    )
    expect(text(formatCombatLogEvent(attack, 'zh-TW', resolveEntryLabel, zhNames))).toContain(
      'Aria · 長劍 · → Goblin · 命中',
    )
  })

  it('shows one projected single-target spell damage result without duplicating its domain event', () => {
    const spell = event('combat.spell_cast_resolved', {
      caster_entry_id: 'hero',
      target_entry_id: 'enemy',
      spell_ref: 'srd5.1:spell:magic-missile',
      damage: 7,
      target_current_hp: 5,
      domain_events: [
        { type: 'damage', amount: 7, target_ref: 'enemy' },
      ],
    })

    const rendered = text(formatCombatLogEvent(spell, 'en', resolveEntryLabel, fallbackContentName))
    expect(rendered).toContain('Damage 7 · HP 5')
    expect(rendered.match(/Damage 7/g)).toHaveLength(1)
  })

  it('shows healing only from a projected heal domain event', () => {
    const spell = event('combat.spell_cast_resolved', {
      caster_entry_id: 'hero',
      target_entry_id: 'hero',
      spell_ref: 'srd5.1:spell:cure-wounds',
      damage: 0,
      target_current_hp: 10,
      domain_events: [
        { type: 'heal', requested: 8, restored: 6, target_ref: 'hero' },
      ],
    })

    const rendered = text(formatCombatLogEvent(spell, 'en', resolveEntryLabel, fallbackContentName))
    expect(rendered).toContain('Healing 6')
    expect(rendered).toContain('HP 10')
    expect(rendered).not.toContain('Damage 0')
  })

  it('does not present a utility spell damage=0 field as a damage result', () => {
    const spell = event('combat.spell_cast_resolved', {
      caster_entry_id: 'hero',
      target_entry_id: 'enemy',
      spell_ref: 'srd5.1:spell:hold-person',
      damage: 0,
      domain_events: [
        { type: 'saving_throw', target_ref: 'enemy', succeeded: false },
      ],
    })

    const rendered = text(formatCombatLogEvent(spell, 'en', resolveEntryLabel, fallbackContentName))
    expect(rendered).not.toContain('Damage')
    expect(rendered).not.toContain('Healing')
  })

  it('omits spell target HP when the Player projected payload does not contain it', () => {
    const spell = event('combat.spell_cast_resolved', {
      caster_entry_id: 'hero',
      target_entry_id: 'enemy',
      target_is_hostile: true,
      spell_ref: 'srd5.1:spell:magic-missile',
      damage: 7,
      domain_events: [
        { type: 'damage', amount: 7, target_ref: 'enemy' },
      ],
    })

    const rendered = text(formatCombatLogEvent(spell, 'en', resolveEntryLabel, fallbackContentName))
    expect(rendered).toContain('Damage 7')
    expect(rendered).not.toContain('HP')
    expect(rendered).not.toContain('?')
  })

  it('shows projected AoE target count damage and only present per-target HP fields', () => {
    const spell = event('combat.spell_aoe_resolved', {
      caster_entry_id: 'hero',
      spell_ref: 'srd5.1:spell:burning-hands',
      outcomes: [
        { target_entry_id: 'enemy', damage: 7 },
        { target_entry_id: 'hero', damage: 3, current_hp: 9 },
      ],
      domain_events: [
        { type: 'damage', amount: 7, target_ref: 'enemy' },
        { type: 'damage', amount: 3, target_ref: 'hero' },
      ],
    })

    const rendered = text(formatCombatLogEvent(spell, 'en', resolveEntryLabel, fallbackContentName))
    expect(rendered).toContain('2 targets')
    expect(rendered).toContain('Goblin · Damage 7')
    expect(rendered).toContain('Aria · Damage 3 · HP 9')
    expect(rendered).not.toContain('Goblin · Damage 7 · HP')
  })

  it('uses localized generic categories while content names are unavailable and preserves custom attack names', () => {
    const spell = event('combat.spell_cast_resolved', {
      caster_entry_id: 'hero',
      target_entry_id: 'enemy',
      spell_ref: 'srd5.1:spell:hold-person',
      concentration_started: true,
      domain_events: [
        { type: 'condition_applied', tag: 'paralyzed' },
      ],
    })
    const canonicalAttack = event('roll.resolved', {
      combat_id: 'combat-1',
      attacker_entry_id: 'hero',
      target_entry_id: 'enemy',
      attack_resolution: {
        attack: {
          source_ref: 'srd5.1:equipment:longsword',
          name: 'Longsword',
          hit: true,
          critical: false,
        },
      },
    })
    const customAttack = event('roll.resolved', {
      combat_id: 'combat-1',
      attacker_entry_id: 'hero',
      target_entry_id: 'enemy',
      attack_resolution: {
        attack: {
          name: '媽媽的平底鍋',
          hit: true,
          critical: false,
        },
      },
    })

    const spellText = text(formatCombatLogEvent(spell, 'zh-TW', resolveEntryLabel, fallbackContentName))
    const canonicalAttackText = text(
      formatCombatLogEvent(canonicalAttack, 'zh-TW', resolveEntryLabel, fallbackContentName),
    )
    const customAttackText = text(
      formatCombatLogEvent(customAttack, 'zh-TW', resolveEntryLabel, fallbackContentName),
    )

    expect(spellText).toBe('Aria · 法術 · → Goblin · 開始專注 · 狀態')
    expect(spellText).not.toContain('hold person')
    expect(spellText).not.toContain('paralyzed')
    expect(canonicalAttackText).toContain('Aria · 攻擊 · → Goblin · 命中')
    expect(canonicalAttackText).not.toContain('Longsword')
    expect(customAttackText).toContain('Aria · 媽媽的平底鍋 · → Goblin · 命中')
  })

  it('collects visible canonical content references for one batched presentation request', () => {
    const refs = combatLogContentReferences([
      event('combat.spell_cast_resolved', {
        spell_ref: 'srd5.1:spell:hold-person',
        domain_events: [
          {
            type: 'condition_applied',
            tag: 'paralyzed',
          },
        ],
      }),
      event('roll.resolved', {
        combat_id: 'combat-1',
        attack_resolution: {
          attack: {
            source_ref: 'srd5.1:equipment:longsword',
            name: 'Longsword',
          },
        },
      }),
    ])

    expect(new Set(refs)).toEqual(new Set([
      'srd5.1:spell:hold-person',
      'srd5.1:condition:paralyzed',
      'srd5.1:equipment:longsword',
    ]))
    expect(refs).not.toContain('paralyzed')
  })

  it('does not infer character or monster conditions from dropped_to_zero alone', () => {
    const characterDamage = event('combat.damage_applied', {
      target_entry_id: 'hero',
      amount: 7,
      target_injury_level: 'down',
      dropped_to_zero: true,
      after: { current_hp: 0, max_hp: 12, temp_hp: 0 },
    })
    const monsterDamage = event('combat.damage_applied', {
      target_entry_id: 'enemy',
      amount: 7,
      target_injury_level: 'down',
      dropped_to_zero: true,
      monster_outcome_required: true,
      after: { current_hp: 0, max_hp: 7, temp_hp: 0 },
    })

    const characterText = text(
      formatCombatLogEvent(characterDamage, 'zh-TW', resolveEntryLabel, fallbackContentName),
    )
    const monsterText = text(
      formatCombatLogEvent(monsterDamage, 'zh-TW', resolveEntryLabel, fallbackContentName),
    )
    expect(characterText).toBe('Aria · 傷害 · 7 · HP 0/12 · 傷勢: 倒下')
    expect(monsterText).toBe('Goblin · 傷害 · 7 · HP 0/7 · 傷勢: 倒下')
    expect(characterText).not.toContain('昏迷')
    expect(characterText).not.toContain('倒地')
    expect(monsterText).not.toContain('昏迷')
    expect(monsterText).not.toContain('倒地')
  })

  it('omits hostile exact HP AC and DC when Player projected payloads do not contain them', () => {
    const attack = event('roll.resolved', {
      combat_id: 'combat-1',
      attacker_entry_id: 'hero',
      target_entry_id: 'enemy',
      target_is_hostile: true,
      target_injury_level: 'wounded',
      attack_resolution: {
        attack: {
          name: 'Custom Slash',
          total: 18,
          hit: true,
          critical: false,
        },
        damage: {
          adjusted_total: 7,
        },
      },
    })
    const concentration = event('combat.concentration_resolved', {
      target_entry_id: 'enemy',
      target_is_hostile: true,
      total: 16,
      succeeded: true,
    })

    const attackText = text(
      formatCombatLogEvent(attack, 'en', resolveEntryLabel, fallbackContentName),
    )
    const concentrationText = text(
      formatCombatLogEvent(concentration, 'en', resolveEntryLabel, fallbackContentName),
    )
    expect(attackText).toContain('Aria · Custom Slash · → Goblin · Hit')
    expect(attackText).toContain('Damage 7')
    expect(attackText).not.toContain('AC')
    expect(attackText).not.toContain('HP')
    expect(attackText).not.toContain('?')
    expect(concentrationText).toBe('Goblin · Concentration maintained · Total 16')
    expect(concentrationText).not.toContain('DC')
  })

  it('shows exact AC HP and DC when those fields are present in a DM projected payload', () => {
    const attack = event('roll.resolved', {
      combat_id: 'combat-1',
      attacker_entry_id: 'hero',
      target_entry_id: 'enemy',
      target_is_hostile: true,
      target_injury_level: 'critical',
      attack_resolution: {
        attack: {
          name: 'Custom Slash',
          total: 18,
          target_ac: 15,
          hit: true,
          critical: false,
        },
        damage: {
          adjusted_total: 7,
          after: { current_hp: 5, max_hp: 20, temp_hp: 0 },
        },
      },
    })
    const concentration = event('combat.concentration_resolved', {
      target_entry_id: 'enemy',
      target_is_hostile: true,
      total: 16,
      dc: 12,
      succeeded: true,
    })

    expect(text(formatCombatLogEvent(attack, 'en', resolveEntryLabel, fallbackContentName))).toContain(
      'Total 18 · AC 15 · Damage 7 · HP 5/20',
    )
    expect(text(formatCombatLogEvent(concentration, 'en', resolveEntryLabel, fallbackContentName))).toBe(
      'Goblin · Concentration maintained · Total 16 · DC 12',
    )
  })

  it('formats active concentration drop as a bilingual compact outcome', () => {
    const concentrationChanged = event('combat.concentration_changed', {
      entry_id: 'hero',
      dropped: true,
    })

    expect(text(
      formatCombatLogEvent(concentrationChanged, 'zh-TW', resolveEntryLabel, fallbackContentName),
    )).toBe('Aria · 專注中斷')
    expect(text(
      formatCombatLogEvent(concentrationChanged, 'en', resolveEntryLabel, fallbackContentName),
    )).toBe('Aria · Concentration lost')
  })

  it('formats turn healing reaction and adjudication events without raw event kinds', () => {
    const cases: Array<[TableEvent, string]> = [
      [event('combat.turn_advanced', { round: 2, current_turn_entry_id: 'hero' }), 'Turn · Aria · Round 2'],
      [event('combat.healing_applied', { target_entry_id: 'hero', amount: 4 }), 'Aria · Healing · 4'],
      [
        event('combat.reaction_requested', {
          entry_id: 'hero',
          kind: 'opportunity_attack',
          status: 'open',
        }),
        'Aria · Reaction: Opportunity attack · Reaction requested',
      ],
      [
        event('combat.adjudication_resolved', {
          attacker_entry_id: 'hero',
          target_entry_id: 'enemy',
          kind: 'range',
          status: 'resolved',
        }),
        'Aria · Adjudication: Range · → Goblin · Adjudication resolved',
      ],
    ]

    for (const [source, expected] of cases) {
      const rendered = text(
        formatCombatLogEvent(source, 'en', resolveEntryLabel, fallbackContentName),
      )
      expect(rendered).toBe(expected)
      expect(rendered).not.toContain(source.kind)
    }
  })

  it('keeps combat mechanics out of Chat while preserving narration dialogue and P3 roll requests', () => {
    expect(isSessionChatEvent(event('exploration.narration', { text: 'The door opens.' }))).toBe(true)
    expect(isSessionChatEvent(event('exploration.dialogue', { text: 'Ready.' }))).toBe(true)
    expect(isSessionChatEvent(event('roll.requested', {}))).toBe(true)
    expect(isSessionChatEvent(event('combat.turn_advanced', { round: 1 }))).toBe(false)
    expect(isSessionChatEvent(event('roll.resolved', { combat_id: 'combat-1' }))).toBe(false)
  })

  it('keeps unknown events compatible by returning no combat-specific presentation', () => {
    expect(
      formatCombatLogEvent(event('combat.future_event', { safe: true }), 'en', resolveEntryLabel, fallbackContentName),
    ).toBeNull()
    expect(
      formatCombatLogEvent(event('stage.updated', {}), 'zh-TW', resolveEntryLabel, fallbackContentName),
    ).toBeNull()
  })
})
