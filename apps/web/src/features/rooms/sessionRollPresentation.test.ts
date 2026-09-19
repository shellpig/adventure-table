import { describe, expect, it } from 'vitest'

import type { TableEvent } from '../../api/sessions'
import { combatLogContentFields, combatLogContentReferences } from './sessionCombatLog'
import { sessionCopy } from './sessionCopy'
import { formatRollRequestPrompt } from './sessionRollPresentation'

const ENTRY_LABELS: Record<string, string> = {
  hero: '灰灰',
  enemy: '哥布林',
}

function event(payload: Record<string, unknown>, recipients: string[] = []): TableEvent {
  return {
    id: 'event-roll-requested',
    session_id: 'session-1',
    seq: 1,
    kind: 'roll.requested',
    acting_seat_id: null,
    subject_seat_id: null,
    subject_character_id: null,
    execution_mode: null,
    visibility: 'public',
    recipient_seat_ids: recipients,
    payload_version: 1,
    payload,
    created_at: '2026-09-19T10:00:00Z',
  }
}

const resolvers = {
  entryLabel: (entryId: string) => ENTRY_LABELS[entryId] ?? null,
  contentName: (reference: string | null | undefined, fallback = '') =>
    reference === 'srd5.1:item:longbow' ? '長弓' : fallback,
  contentField: (reference: string | null | undefined, field: string | null | undefined, fallback = '') =>
    reference === 'srd5.1:monster:goblin' && field === 'data.actions.0.name' ? '彎刀' : fallback,
}

describe('combat roll.requested chat prompts', () => {
  const zh = sessionCopy('zh-TW')
  const en = sessionCopy('en')

  it('presents initiative with localized type and drops the server label', () => {
    const initiative = event({
      request_type: 'initiative',
      label: 'Initiative',
      combat_entry_ids: [['hero'], ['enemy']],
    })
    expect(formatRollRequestPrompt(initiative, ['灰灰'], zh, resolvers)).toBe('DM 要求 灰灰進行先攻檢定。')
    expect(formatRollRequestPrompt(initiative, [], zh, resolvers)).toBe('DM 要求 灰灰、哥布林進行先攻檢定。')
    expect(formatRollRequestPrompt(initiative, [], en, resolvers)).toContain('to make Initiative.')
    expect(formatRollRequestPrompt(initiative, [], zh, resolvers)).not.toContain('initiative')
  })

  it('names a monster attack via the content presentation field and the attacker entry', () => {
    const attack = event({
      request_type: 'attack',
      label: 'Attack: Scimitar',
      attacker_entry_id: 'enemy',
      source_ref: 'monster-action:goblin:0',
      content_ref: 'srd5.1:monster:goblin',
      presentation_field: 'data.actions.0.name',
    })
    expect(formatRollRequestPrompt(attack, [], zh, resolvers)).toBe('DM 要求 哥布林進行攻擊：彎刀。')
    expect(formatRollRequestPrompt(attack, [], zh, {})).toBe('DM 要求 進行攻擊：Scimitar。')
  })

  it('names a character weapon attack via its item content ref', () => {
    const attack = event({
      request_type: 'attack',
      label: 'Attack: Longbow',
      attacker_entry_id: 'hero',
      source_ref: 'inventory:abc',
      content_ref: 'srd5.1:item:longbow',
      presentation_field: 'name',
      modifier_mode: 'advantage',
    }, ['seat-hero'])
    expect(formatRollRequestPrompt(attack, ['灰灰'], zh, resolvers)).toBe('DM 要求 灰灰進行攻擊，優勢：Longbow。')
    expect(formatRollRequestPrompt(attack, ['灰灰'], zh, {
      ...resolvers,
      contentField: (reference, field, fallback = '') =>
        reference === 'srd5.1:item:longbow' && field === 'name' ? '長弓' : fallback,
    })).toBe('DM 要求 灰灰進行攻擊，優勢：長弓。')
  })

  it('presents a death save from the target entry', () => {
    const deathSave = event({ request_type: 'death_save', target_entry_id: 'hero' })
    expect(formatRollRequestPrompt(deathSave, [], zh, resolvers)).toBe('DM 要求 灰灰進行死亡豁免。')
  })

  it('collects attack content refs and fields from roll.requested events', () => {
    const attack = event({
      request_type: 'attack',
      content_ref: 'srd5.1:monster:goblin',
      presentation_field: 'data.actions.0.name',
    })
    const fallback = event({ request_type: 'attack', source_ref: 'srd5.1:item:longbow' })
    expect(combatLogContentReferences([attack, fallback])).toEqual([
      'srd5.1:monster:goblin',
      'srd5.1:item:longbow',
    ])
    expect(combatLogContentFields([attack])).toEqual({
      'srd5.1:monster:goblin': ['data.actions.0.name'],
    })
  })
})
