import { describe, expect, it } from 'vitest'

import type { TableEvent } from '../../api/sessions'
import {
  combatLogContentFields,
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
const fallbackContentField = (_reference: string | null | undefined, _field: string | null | undefined, fallback = '') => fallback

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
      expect(text(formatCombatLogEvent(attack, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
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

    expect(text(formatCombatLogEvent(spell, 'zh-TW', resolveEntryLabel, zhNames, fallbackContentField))).toBe(
      'Aria · 法術: 人類定身術 · → Goblin · 開始專注 · 狀態: 麻痺',
    )
    expect(text(formatCombatLogEvent(spell, 'en', resolveEntryLabel, enNames, fallbackContentField))).toBe(
      'Aria · Spell: Hold Person · → Goblin · Concentration started · Condition: Paralyzed',
    )
    expect(text(formatCombatLogEvent(attack, 'zh-TW', resolveEntryLabel, zhNames, fallbackContentField))).toContain(
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

    const rendered = text(formatCombatLogEvent(spell, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField))
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

    const rendered = text(formatCombatLogEvent(spell, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField))
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

    const rendered = text(formatCombatLogEvent(spell, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField))
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

    const rendered = text(formatCombatLogEvent(spell, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField))
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

    const rendered = text(formatCombatLogEvent(spell, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField))
    expect(rendered).toContain('2 targets')
    expect(rendered).toContain('Goblin · Damage 7')
    expect(rendered).toContain('Aria · Damage 3 · HP 9')
    expect(rendered).not.toContain('Goblin · Damage 7 · HP')
  })

  it('formats projected save success and failure bilingually without DC or raw kinds', () => {
    const success = event('combat.save_resolved', {
      target_entry_id: 'hero',
      ability_ref: 'srd5.1:ability:dexterity',
      total: 18,
      succeeded: true,
    })
    const failure = event('combat.save_resolved', {
      target_entry_id: 'enemy',
      ability_ref: 'srd5.1:ability:wisdom',
      total: 7,
      succeeded: false,
    })

    expect(text(formatCombatLogEvent(success, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · 豁免 · 成功 · 總值 18')
    expect(text(formatCombatLogEvent(failure, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · 豁免 · 失敗 · 總值 7')
    expect(text(formatCombatLogEvent(success, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · Saving throw · Success · Total 18')
    expect(text(formatCombatLogEvent(failure, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · Saving throw · Failure · Total 7')

    for (const source of [success, failure]) {
      const rendered = text(formatCombatLogEvent(source, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField))
      expect(rendered).not.toContain(source.kind)
      expect(rendered).not.toContain('DC')
      expect(rendered).not.toContain('srd5.1:ability:')
    }
  })

  it('formats death-save stable dead and natural-20 recovery from projected flags bilingually', () => {
    const stable = event('combat.death_save_resolved', {
      target_entry_id: 'hero',
      d20: 12,
      current_hp: 0,
      successes: 3,
      failures: 1,
      stable: true,
      dead: false,
      natural_20_recovery: false,
    })
    const dead = event('combat.death_save_resolved', {
      target_entry_id: 'hero',
      d20: 4,
      current_hp: 0,
      successes: 1,
      failures: 3,
      stable: false,
      dead: true,
      natural_20_recovery: false,
    })
    const recovered = event('combat.death_save_resolved', {
      target_entry_id: 'hero',
      d20: 20,
      current_hp: 1,
      successes: 0,
      failures: 0,
      stable: false,
      dead: false,
      natural_20_recovery: true,
    })

    expect(text(formatCombatLogEvent(stable, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · 死亡豁免 · d20 12 · HP 0 · 成功 3 · 失敗 1 · 穩定')
    expect(text(formatCombatLogEvent(stable, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · Death save · d20 12 · HP 0 · Successes 3 · Failures 1 · Stable')
    expect(text(formatCombatLogEvent(dead, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · 死亡豁免 · d20 4 · HP 0 · 成功 1 · 失敗 3 · 死亡')
    expect(text(formatCombatLogEvent(dead, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · Death save · d20 4 · HP 0 · Successes 1 · Failures 3 · Dead')
    expect(text(formatCombatLogEvent(recovered, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · 死亡豁免 · d20 20 · HP 1 · 成功 0 · 失敗 0 · 自然 20 恢復')
    expect(text(formatCombatLogEvent(recovered, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · Death save · d20 20 · HP 1 · Successes 0 · Failures 0 · Natural 20 recovery')

    for (const source of [stable, dead, recovered]) {
      const rendered = text(formatCombatLogEvent(source, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField))
      expect(rendered).not.toContain(source.kind)
      expect(rendered).not.toContain('DC')
    }
  })

  it('omits missing save fields and never falls back to raw target identifiers', () => {
    const hiddenId = '123e4567-e89b-12d3-a456-426614174000'
    const save = event('combat.save_resolved', {
      target_entry_id: hiddenId,
      ability_ref: 'srd5.1:ability:wisdom',
    })
    const deathSave = event('combat.death_save_resolved', {
      target_entry_id: hiddenId,
      stable: false,
      dead: false,
      natural_20_recovery: false,
    })

    expect(text(formatCombatLogEvent(save, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Saving throw')
    expect(text(formatCombatLogEvent(deathSave, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Death save')

    for (const source of [save, deathSave]) {
      const rendered = text(formatCombatLogEvent(source, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField))
      expect(rendered).not.toContain(hiddenId)
      expect(rendered).not.toContain(source.kind)
      expect(rendered).not.toContain('DC')
      expect(rendered).not.toContain('?')
    }
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

    const spellText = text(formatCombatLogEvent(spell, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField))
    const canonicalAttackText = text(
      formatCombatLogEvent(canonicalAttack, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField),
    )
    const customAttackText = text(
      formatCombatLogEvent(customAttack, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField),
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
      formatCombatLogEvent(characterDamage, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField),
    )
    const monsterText = text(
      formatCombatLogEvent(monsterDamage, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField),
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
      formatCombatLogEvent(attack, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField),
    )
    const concentrationText = text(
      formatCombatLogEvent(concentration, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField),
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

    expect(text(formatCombatLogEvent(attack, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField))).toContain(
      'Total 18 · AC 15 · Damage 7 · HP 5/20',
    )
    expect(text(formatCombatLogEvent(concentration, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField))).toBe(
      'Goblin · Concentration maintained · Total 16 · DC 12',
    )
  })

  it('formats active concentration drop as a bilingual compact outcome', () => {
    const concentrationChanged = event('combat.concentration_changed', {
      entry_id: 'hero',
      dropped: true,
    })

    expect(text(
      formatCombatLogEvent(concentrationChanged, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField),
    )).toBe('Aria · 專注中斷')
    expect(text(
      formatCombatLogEvent(concentrationChanged, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField),
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
        formatCombatLogEvent(source, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField),
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
      formatCombatLogEvent(event('combat.future_event', { safe: true }), 'en', resolveEntryLabel, fallbackContentName, fallbackContentField),
    ).toBeNull()
    expect(
      formatCombatLogEvent(event('stage.updated', {}), 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField),
    ).toBeNull()
  })

  it('localizes canonical weapon and monster attack names using content_ref and presentation_field in both locales', () => {
    const weaponAttack = event('roll.resolved', {
      combat_id: 'combat-1',
      attacker_entry_id: 'hero',
      target_entry_id: 'enemy',
      attack_resolution: {
        attack: {
          source_ref: 'inventory:item-1',
          name: 'Longsword',
          content_ref: 'srd5.1:equipment:longsword',
          presentation_field: 'name',
          hit: true,
          critical: false,
        },
      },
    })
    const monsterAttack = event('roll.resolved', {
      combat_id: 'combat-1',
      attacker_entry_id: 'enemy',
      target_entry_id: 'hero',
      attack_resolution: {
        attack: {
          source_ref: 'monster-action:0',
          name: 'Scimitar',
          content_ref: 'srd5.1:monster:goblin',
          presentation_field: 'data.actions.0.name',
          hit: true,
          critical: false,
        },
      },
    })
    const customAttack = event('roll.resolved', {
      combat_id: 'combat-1',
      attacker_entry_id: 'enemy',
      target_entry_id: 'hero',
      attack_resolution: {
        attack: {
          source_ref: 'monster-action:1',
          name: 'Rusty Cleaver',
          content_ref: null,
          presentation_field: null,
          hit: false,
          critical: false,
        },
      },
    })

    const zhFieldResolver = (ref: string | null | undefined, field: string | null | undefined, fb = '') => {
      if (ref === 'srd5.1:equipment:longsword' && field === 'name') return '長劍'
      if (ref === 'srd5.1:monster:goblin' && field === 'data.actions.0.name') return '彎刀'
      return fb
    }
    const enFieldResolver = (ref: string | null | undefined, field: string | null | undefined, fb = '') => {
      if (ref === 'srd5.1:equipment:longsword' && field === 'name') return 'Longsword'
      if (ref === 'srd5.1:monster:goblin' && field === 'data.actions.0.name') return 'Scimitar'
      return fb
    }
    const zhNameResolver = (ref: string | null | undefined, fb = '') => {
      if (ref === 'srd5.1:equipment:longsword') return '長劍'
      return fb
    }
    const enNameResolver = (ref: string | null | undefined, fb = '') => {
      if (ref === 'srd5.1:equipment:longsword') return 'Longsword'
      return fb
    }

    // zh-TW localized
    expect(text(formatCombatLogEvent(weaponAttack, 'zh-TW', resolveEntryLabel, zhNameResolver, zhFieldResolver)))
      .toContain('Aria · 長劍 · → Goblin · 命中')
    expect(text(formatCombatLogEvent(monsterAttack, 'zh-TW', resolveEntryLabel, zhNameResolver, zhFieldResolver)))
      .toContain('Goblin · 彎刀 · → Aria · 命中')
    expect(text(formatCombatLogEvent(customAttack, 'zh-TW', resolveEntryLabel, zhNameResolver, zhFieldResolver)))
      .toContain('Goblin · Rusty Cleaver · → Aria · 未命中')

    // en localized
    expect(text(formatCombatLogEvent(weaponAttack, 'en', resolveEntryLabel, enNameResolver, enFieldResolver)))
      .toContain('Aria · Longsword · → Goblin · Hit')
    expect(text(formatCombatLogEvent(monsterAttack, 'en', resolveEntryLabel, enNameResolver, enFieldResolver)))
      .toContain('Goblin · Scimitar · → Aria · Hit')
    expect(text(formatCombatLogEvent(customAttack, 'en', resolveEntryLabel, enNameResolver, enFieldResolver)))
      .toContain('Goblin · Rusty Cleaver · → Aria · Miss')
  })

  it('extracts extra presentation fields for monster actions via combatLogContentFields', () => {
    const events = [
      event('roll.resolved', {
        combat_id: 'combat-1',
        attack_resolution: {
          attack: {
            content_ref: 'srd5.1:monster:goblin',
            presentation_field: 'data.actions.0.name',
          },
        },
      }),
      event('roll.resolved', {
        combat_id: 'combat-1',
        attack_resolution: {
          attack: {
            content_ref: 'srd5.1:equipment:longsword',
            presentation_field: 'name',
          },
        },
      }),
      event('combat.turn_advanced', { round: 1 }),
    ]

    expect(combatLogContentFields(events)).toEqual({
      'srd5.1:monster:goblin': ['data.actions.0.name'],
      'srd5.1:equipment:longsword': ['name'],
    })
    expect(combatLogContentReferences(events)).toEqual([
      'srd5.1:monster:goblin',
      'srd5.1:equipment:longsword',
    ])
  })

  it('formats all lifecycle, action, reaction, adjudication, and save events in zh-TW and en', () => {
    const entryAdded = event('combat.entry_added', {
      entry_id: 'enemy',
      display_name: 'Goblin',
    })
    const entryWithdrawn = event('combat.entry_withdrawn', {
      entry_id: 'enemy',
    })
    const entryRemoved = event('combat.entry_removed', {
      entry_id: 'enemy',
    })
    const initiativeReordered = event('combat.initiative_reordered', {
      ordered_entry_ids: ['hero', 'enemy'],
    })
    const actionUsed = event('combat.action_used', {
      entry_id: 'hero',
      action_kind: 'dash',
    })
    const reactionWindowOpen = event('combat.reaction_window', {
      entry_id: 'hero',
      open: true,
    })
    const reactionWindowClosed = event('combat.reaction_window', {
      entry_id: 'hero',
      open: false,
    })
    const specialAdjReq = event('combat.special_attack_adjudication_requested', {
      attacker_entry_id: 'hero',
      target_entry_id: 'enemy',
      kind: 'grapple',
    })
    const specialAdjReach = event('combat.special_attack_adjudicated', {
      attacker_entry_id: 'hero',
      target_entry_id: 'enemy',
      kind: 'grapple',
      in_reach: true,
    })
    const specialAdjOutOfReach = event('combat.special_attack_adjudicated', {
      attacker_entry_id: 'hero',
      target_entry_id: 'enemy',
      kind: 'shove_push',
      in_reach: false,
    })
    const escapeReq = event('combat.escape_grapple_requested', {
      attacker_entry_id: 'hero',
      target_entry_id: 'enemy',
      kind: 'escape_grapple',
    })
    const savesReq = event('combat.saves_requested', {
      target_entry_ids: ['enemy'],
      ability_ref: 'DEX',
    })

    // zh-TW checks
    expect(text(formatCombatLogEvent(entryAdded, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · 加入戰鬥')
    expect(text(formatCombatLogEvent(entryWithdrawn, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · 脫離戰鬥')
    expect(text(formatCombatLogEvent(entryRemoved, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · 移出戰鬥')
    expect(text(formatCombatLogEvent(initiativeReordered, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('先攻順序調整 · Aria → Goblin')
    expect(text(formatCombatLogEvent(actionUsed, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · 疾走')
    expect(text(formatCombatLogEvent(reactionWindowOpen, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · 反應窗口開啟')
    expect(text(formatCombatLogEvent(reactionWindowClosed, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · 反應窗口關閉')
    expect(text(formatCombatLogEvent(specialAdjReq, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · 裁定: 擒抱 · → Goblin · 等待 DM 裁定')
    expect(text(formatCombatLogEvent(specialAdjReach, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · 裁定: 擒抱 · 在觸及範圍內 · → Goblin')
    expect(text(formatCombatLogEvent(specialAdjOutOfReach, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · 裁定: 推開 · 超出觸及範圍 · → Goblin')
    expect(text(formatCombatLogEvent(escapeReq, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · 脫離擒抱 → Goblin · 等待對抗擲骰')
    expect(text(formatCombatLogEvent(savesReq, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · 豁免 · 等待豁免檢定 · DEX')

    // en checks
    expect(text(formatCombatLogEvent(entryAdded, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · Joined combat')
    expect(text(formatCombatLogEvent(entryWithdrawn, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · Withdrawn')
    expect(text(formatCombatLogEvent(entryRemoved, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · Removed from combat')
    expect(text(formatCombatLogEvent(initiativeReordered, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Initiative reordered · Aria → Goblin')
    expect(text(formatCombatLogEvent(actionUsed, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · Dash')
    expect(text(formatCombatLogEvent(reactionWindowOpen, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · Reaction window opened')
    expect(text(formatCombatLogEvent(reactionWindowClosed, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · Reaction window closed')
    expect(text(formatCombatLogEvent(specialAdjReq, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · Adjudication: Grapple · → Goblin · Awaiting DM adjudication')
    expect(text(formatCombatLogEvent(specialAdjReach, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · Adjudication: Grapple · In reach · → Goblin')
    expect(text(formatCombatLogEvent(specialAdjOutOfReach, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · Adjudication: Shove push · Out of reach · → Goblin')
    expect(text(formatCombatLogEvent(escapeReq, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Aria · Escape grapple → Goblin · Awaiting contest roll')
    expect(text(formatCombatLogEvent(savesReq, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · Saving throw · Saving throws requested · DEX')
  })

  it('formats special_attack_roll_resolved for both waiting and resolved outcomes with conditions and distance', () => {
    const waiting = event('combat.special_attack_roll_resolved', {
      target_entry_id: 'enemy',
      total: 14,
      status: 'waiting_for_roll',
      resolution_result: null,
    })
    const resolvedGrappleSuccess = event('combat.special_attack_roll_resolved', {
      target_entry_id: 'enemy',
      total: 12,
      status: 'resolved',
      resolution_result: {
        kind: 'grapple',
        status: 'success',
        attacker_total: 18,
        target_total: 12,
        condition_to_apply: 'grappled',
      },
    })
    const resolvedShovePush = event('combat.special_attack_roll_resolved', {
      target_entry_id: 'enemy',
      total: 10,
      status: 'resolved',
      resolution_result: {
        kind: 'shove_push',
        status: 'success',
        attacker_total: 16,
        target_total: 10,
        push_distance_ft: 5,
      },
    })
    const resolvedFailure = event('combat.special_attack_roll_resolved', {
      target_entry_id: 'enemy',
      total: 19,
      status: 'resolved',
      resolution_result: {
        kind: 'grapple',
        status: 'failure',
        attacker_total: 11,
        target_total: 19,
      },
    })
    const resolvedEscapeSuccess = event('combat.special_attack_roll_resolved', {
      target_entry_id: 'enemy',
      total: 15,
      status: 'resolved',
      resolution_result: {
        kind: 'escape_grapple',
        status: 'success',
        attacker_total: 17,
        target_total: 13,
        condition_to_remove: 'grappled',
      },
    })

    const zhConditionResolver = contentNameResolver({
      'srd5.1:condition:grappled': '擒抱',
    })
    const enConditionResolver = contentNameResolver({
      'srd5.1:condition:grappled': 'Grappled',
    })

    // zh-TW
    expect(text(formatCombatLogEvent(waiting, 'zh-TW', resolveEntryLabel, zhConditionResolver, fallbackContentField)))
      .toBe('Goblin · 特殊攻擊 · 等待對抗擲骰 · 總值 14')
    expect(text(formatCombatLogEvent(resolvedGrappleSuccess, 'zh-TW', resolveEntryLabel, zhConditionResolver, fallbackContentField)))
      .toBe('Goblin · 擒抱 · 成功 · 攻擊方總值 18 · 目標總值 12 · 狀態: 擒抱')
    expect(text(formatCombatLogEvent(resolvedShovePush, 'zh-TW', resolveEntryLabel, zhConditionResolver, fallbackContentField)))
      .toBe('Goblin · 推開 · 成功 · 攻擊方總值 16 · 目標總值 10 · 5 ft')
    expect(text(formatCombatLogEvent(resolvedFailure, 'zh-TW', resolveEntryLabel, zhConditionResolver, fallbackContentField)))
      .toBe('Goblin · 擒抱 · 失敗 · 攻擊方總值 11 · 目標總值 19')
    expect(
      text(formatCombatLogEvent(resolvedEscapeSuccess, 'zh-TW', resolveEntryLabel, zhConditionResolver, fallbackContentField)),
    ).toBe('Goblin · 脫離擒抱 · 成功 · 攻擊方總值 17 · 目標總值 13 · 移除狀態: 擒抱')

    // en
    expect(text(formatCombatLogEvent(waiting, 'en', resolveEntryLabel, enConditionResolver, fallbackContentField)))
      .toBe('Goblin · Special attack · Awaiting contest roll · Total 14')
    expect(text(formatCombatLogEvent(resolvedGrappleSuccess, 'en', resolveEntryLabel, enConditionResolver, fallbackContentField)))
      .toBe('Goblin · Grapple · Success · Attacker total 18 · Target total 12 · Condition: Grappled')
    expect(text(formatCombatLogEvent(resolvedShovePush, 'en', resolveEntryLabel, enConditionResolver, fallbackContentField)))
      .toBe('Goblin · Shove push · Success · Attacker total 16 · Target total 10 · 5 ft')
    expect(text(formatCombatLogEvent(resolvedFailure, 'en', resolveEntryLabel, enConditionResolver, fallbackContentField)))
      .toBe('Goblin · Grapple · Failure · Attacker total 11 · Target total 19')
    expect(
      text(formatCombatLogEvent(resolvedEscapeSuccess, 'en', resolveEntryLabel, enConditionResolver, fallbackContentField)),
    ).toBe('Goblin · Escape grapple · Success · Attacker total 17 · Target total 13 · Condition removed: Grappled')
  })

  it('formats combat.monster_outcome_set and combat.monster_instance_updated events in en and zh-TW', () => {
    const outcomeDead = event('combat.monster_outcome_set', {
      combat_id: 'combat-1',
      entry_id: 'enemy',
      outcome: 'dead',
    })
    const outcomeUnconscious = event('combat.monster_outcome_set', {
      combat_id: 'combat-1',
      entry_id: 'enemy',
      outcome: 'unconscious',
    })
    const outcomeSurrendered = event('combat.monster_outcome_set', {
      combat_id: 'combat-1',
      entry_id: 'enemy',
      outcome: 'surrendered',
    })
    const outcomeFled = event('combat.monster_outcome_set', {
      combat_id: 'combat-1',
      entry_id: 'enemy',
      outcome: 'fled',
    })
    const outcomeOtherWithNote = event('combat.monster_outcome_set', {
      combat_id: 'combat-1',
      entry_id: 'enemy',
      outcome: 'other',
      note: 'Trapped under heavy rubble',
    })
    const outcomeOtherNoNote = event('combat.monster_outcome_set', {
      combat_id: 'combat-1',
      entry_id: 'enemy',
      outcome: 'other',
      note: '',
    })
    const updatedNameAndReveal = event('combat.monster_instance_updated', {
      monster_instance_id: 'inst-1',
      combat_entry_id: 'entry-1',
      name: 'Goblin Chieftain',
      changed: ['name', 'reveal'],
    })
    const updatedEmptyChanged = event('combat.monster_instance_updated', {
      monster_instance_id: 'inst-1',
      combat_entry_id: 'entry-1',
      name: 'Goblin Chieftain',
      changed: [],
    })
    const updatedAllFields = event('combat.monster_instance_updated', {
      monster_instance_id: 'inst-1',
      name: 'Goblin Chieftain',
      changed: ['name', 'visibility', 'position_note', 'reveal'],
    })

    // en
    expect(text(formatCombatLogEvent(outcomeDead, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · Dead')
    expect(text(formatCombatLogEvent(outcomeUnconscious, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · Unconscious')
    expect(text(formatCombatLogEvent(outcomeSurrendered, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · Surrendered')
    expect(text(formatCombatLogEvent(outcomeFled, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · Fled')
    expect(text(formatCombatLogEvent(outcomeOtherWithNote, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · Other outcome · Trapped under heavy rubble')
    expect(text(formatCombatLogEvent(outcomeOtherNoNote, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · Other outcome')
    expect(text(formatCombatLogEvent(updatedNameAndReveal, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin Chieftain · Enemy updated · Name, Revealed info')
    expect(text(formatCombatLogEvent(updatedEmptyChanged, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin Chieftain · Enemy updated')
    expect(text(formatCombatLogEvent(updatedAllFields, 'en', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin Chieftain · Enemy updated · Name, Visibility, Position note, Revealed info')

    // zh-TW
    expect(text(formatCombatLogEvent(outcomeDead, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · 死亡')
    expect(text(formatCombatLogEvent(outcomeUnconscious, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · 昏迷')
    expect(text(formatCombatLogEvent(outcomeSurrendered, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · 投降')
    expect(text(formatCombatLogEvent(outcomeFled, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · 逃離')
    expect(text(formatCombatLogEvent(outcomeOtherWithNote, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · 其他結果 · Trapped under heavy rubble')
    expect(text(formatCombatLogEvent(outcomeOtherNoNote, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin · 其他結果')
    expect(text(formatCombatLogEvent(updatedNameAndReveal, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin Chieftain · 敵人資訊已更新 · 名稱, 公開資訊')
    expect(text(formatCombatLogEvent(updatedEmptyChanged, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin Chieftain · 敵人資訊已更新')
    expect(text(formatCombatLogEvent(updatedAllFields, 'zh-TW', resolveEntryLabel, fallbackContentName, fallbackContentField)))
      .toBe('Goblin Chieftain · 敵人資訊已更新 · 名稱, 能見度, 位置備註, 公開資訊')
  })
})
