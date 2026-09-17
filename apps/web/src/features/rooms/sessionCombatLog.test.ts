import { describe, expect, it } from 'vitest'

import type { TableEvent } from '../../api/sessions'
import { formatCombatLogEvent } from './sessionCombatLog'
import { isSessionChatEvent } from './sessionExploration'

const ENTRY_LABELS: Record<string, string> = {
  hero: 'Aria',
  enemy: 'Goblin',
}

const resolveEntryLabel = (entryId: string) => ENTRY_LABELS[entryId] ?? null

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
  it('formats compact zh-TW and en damage logs with projected condition state', () => {
    const damage = event('combat.damage_applied', {
      target_entry_id: 'enemy',
      amount: 7,
      target_injury_level: 'wounded',
      dropped_to_zero: true,
      after: { current_hp: 5, max_hp: 12, temp_hp: 0 },
    })

    expect(text(formatCombatLogEvent(damage, 'zh-TW', resolveEntryLabel))).toBe(
      'Goblin · 傷害 · 7 · HP 5/12 · 傷勢: 受傷 · 狀態: 昏迷, 倒地',
    )
    expect(text(formatCombatLogEvent(damage, 'en', resolveEntryLabel))).toBe(
      'Goblin · Damage · 7 · HP 5/12 · Injury: Wounded · Condition: Unconscious, Prone',
    )
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
          name: 'Longsword',
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

    const attackText = text(formatCombatLogEvent(attack, 'en', resolveEntryLabel))
    const concentrationText = text(formatCombatLogEvent(concentration, 'en', resolveEntryLabel))
    expect(attackText).toContain('Aria · Longsword · → Goblin · Hit')
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
          name: 'Longsword',
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

    expect(text(formatCombatLogEvent(attack, 'en', resolveEntryLabel))).toContain(
      'Total 18 · AC 15 · Damage 7 · HP 5/20',
    )
    expect(text(formatCombatLogEvent(concentration, 'en', resolveEntryLabel))).toBe(
      'Goblin · Concentration maintained · Total 16 · DC 12',
    )
  })

  it('formats turn healing spell condition reaction and adjudication events without raw event kinds', () => {
    const cases: Array<[TableEvent, string]> = [
      [event('combat.turn_advanced', { round: 2, current_turn_entry_id: 'hero' }), 'Turn · Aria · Round 2'],
      [event('combat.healing_applied', { target_entry_id: 'hero', amount: 4 }), 'Aria · Healing · 4'],
      [
        event('combat.spell_cast_resolved', {
          caster_entry_id: 'hero',
          target_entry_id: 'enemy',
          spell_ref: 'srd5.1:spell:hold-person',
          concentration_started: true,
          domain_events: [
            { type: 'condition_applied', tag: 'paralyzed', effect_id: 'spell-effect:1' },
          ],
        }),
        'Aria · Spell: hold person · → Goblin · Concentration started · Condition: paralyzed',
      ],
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
      const rendered = text(formatCombatLogEvent(source, 'en', resolveEntryLabel))
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
    expect(formatCombatLogEvent(event('combat.future_event', { safe: true }), 'en', resolveEntryLabel)).toBeNull()
    expect(formatCombatLogEvent(event('stage.updated', {}), 'zh-TW', resolveEntryLabel)).toBeNull()
  })
})
