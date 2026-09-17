import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type { CombatDetailView, CombatEntryView, CombatantProjection } from '../../api/combat'
import { SessionCombatMonsterControls } from './SessionCombatMonsterControls'
import { sessionCopy } from './sessionCopy'

vi.mock('../../api/combat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/combat')>()
  return {
    ...actual,
    setMonsterOutcome: vi.fn(),
    updateMonsterInstance: vi.fn(),
  }
})

function makeCombat(options?: Partial<CombatDetailView>): CombatDetailView {
  return {
    id: 'combat-1',
    campaign_id: 'camp-1',
    mode: 'quick',
    status: 'running',
    round_number: 1,
    current_turn_entry_id: 'entry-other',
    revision: 1,
    entries: [],
    combatants: [],
    ...options,
  }
}

function makeEntry(options?: Partial<CombatEntryView>): CombatEntryView {
  return {
    id: 'entry-goblin',
    subject_kind: 'monster',
    character_id: null,
    monster_instance_id: 'inst-goblin',
    display_name: 'Goblin Scout',
    status: 'active',
    initiative_group_key: null,
    initiative_roll_request_id: null,
    initiative_roll_result_id: null,
    initiative_total: 12,
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

function makeProjection(options?: Partial<CombatantProjection>): CombatantProjection {
  return {
    id: 'inst-goblin',
    kind: 'monster',
    name: 'Goblin Scout',
    combat_status: 'active',
    conditions: [],
    effects: [],
    visibility: 'public',
    position_note: 'Behind barrels',
    reveal: {
      armor_class: false,
      description: false,
      position_note: false,
    },
    ...options,
  }
}

function renderControls(
  props?: Partial<React.ComponentProps<typeof SessionCombatMonsterControls>>,
  locale: 'en' | 'zh-TW' = 'en',
): string {
  const copy = sessionCopy(locale)
  return renderToStaticMarkup(
    <SessionCombatMonsterControls
      combat={props?.combat ?? makeCombat()}
      entry={props?.entry ?? makeEntry()}
      projection={props?.projection ?? makeProjection()}
      instanceId={props?.instanceId ?? 'inst-goblin'}
      copy={copy}
      roomId="room-1"
      campaignId="camp-1"
      sessionId="sess-1"
      token="test-token"
      onError={() => undefined}
      refresh={() => undefined}
      {...props}
    />,
  )
}

describe('SessionCombatMonsterControls', () => {
  const copyEn = sessionCopy('en')

  it('renders active monster with reveal all false: unchecked checkboxes, hide button, 5 outcome options, submit enabled when not current turn', () => {
    const markup = renderControls({
      combat: makeCombat({ current_turn_entry_id: 'entry-other' }),
      entry: makeEntry({ id: 'entry-goblin', status: 'active' }),
      projection: makeProjection({
        visibility: 'public',
        reveal: { armor_class: false, description: false, position_note: false },
      }),
    })

    expect(markup).toContain('data-monster-controls="entry-goblin"')

    const acMatch = markup.match(/<input[^>]*data-monster-reveal="armor_class"[^>]*>/)
    const descMatch = markup.match(/<input[^>]*data-monster-reveal="description"[^>]*>/)
    const posMatch = markup.match(/<input[^>]*data-monster-reveal="position_note"[^>]*>/)
    expect(acMatch).not.toBeNull()
    expect(acMatch?.[0]).not.toContain('checked')
    expect(descMatch).not.toBeNull()
    expect(descMatch?.[0]).not.toContain('checked')
    expect(posMatch).not.toBeNull()
    expect(posMatch?.[0]).not.toContain('checked')

    expect(markup).toContain('data-monster-visibility')
    expect(markup).toContain(copyEn.combatMonsterSetHidden)

    expect(markup).toContain('data-monster-outcome')
    expect(markup).toContain('value="dead"')
    expect(markup).toContain('value="unconscious"')
    expect(markup).toContain('value="surrendered"')
    expect(markup).toContain('value="fled"')
    expect(markup).toContain('value="other"')

    const submitMatch = markup.match(/<button[^>]*data-monster-outcome-submit[^>]*>/)
    expect(submitMatch).not.toBeNull()
    expect(submitMatch?.[0]).not.toContain('disabled')
  })

  it('checks reveal checkbox when reveal.armor_class is true', () => {
    const markup = renderControls({
      projection: makeProjection({
        reveal: { armor_class: true, description: false, position_note: false },
      }),
    })

    const acMatch = markup.match(/<input[^>]*data-monster-reveal="armor_class"[^>]*>/)
    const descMatch = markup.match(/<input[^>]*data-monster-reveal="description"[^>]*>/)
    const posMatch = markup.match(/<input[^>]*data-monster-reveal="position_note"[^>]*>/)
    expect(acMatch?.[0]).toContain('checked')
    expect(descMatch?.[0]).not.toContain('checked')
    expect(posMatch?.[0]).not.toContain('checked')
  })

  it('disables outcome submit and displays hint text when entry is the current turn in running combat', () => {
    const markup = renderControls({
      combat: makeCombat({ status: 'running', current_turn_entry_id: 'entry-goblin' }),
      entry: makeEntry({ id: 'entry-goblin', status: 'active' }),
    })

    const submitMatch = markup.match(/<button[^>]*data-monster-outcome-submit[^>]*>/)
    expect(submitMatch?.[0]).toContain('disabled')
    expect(markup).toContain(copyEn.combatOutcomeCurrentTurnHint)
  })

  it('omits outcome controls when entry.status is fled, but retains reveal, visibility, and edit form', () => {
    const markup = renderControls({
      entry: makeEntry({ id: 'entry-goblin', status: 'fled' }),
    })

    expect(markup).not.toContain('data-monster-outcome')
    expect(markup).not.toContain('data-monster-outcome-submit')
    expect(markup).toContain('data-monster-reveal')
    expect(markup).toContain('data-monster-visibility')
    expect(markup).toContain('data-monster-save')
  })

  it('shows "Show to Players" on visibility button for hidden monster', () => {
    const markup = renderControls({
      projection: makeProjection({ visibility: 'hidden' }),
    })

    expect(markup).toContain('data-monster-visibility')
    expect(markup).toContain(copyEn.combatMonsterSetPublic)
    expect(markup).not.toContain(copyEn.combatMonsterSetHidden)
  })

  it('renders zh-TW copy containing 結果判定 and 對玩家公開', () => {
    const markup = renderControls(
      {
        copy: sessionCopy('zh-TW'),
        entry: makeEntry({ status: 'active' }),
        projection: makeProjection({
          reveal: { armor_class: false, description: false, position_note: false },
        }),
      },
      'zh-TW',
    )

    expect(markup).toContain('結果判定')
    expect(markup).toContain('對玩家公開')
  })
})
