import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { CombatDetailView, CombatEntryView } from '../../api/combat'
import type { SearchOption } from '../../components/SearchableSelect'
import { LocaleProvider } from '../../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type LocaleStorage } from '../../i18n/locale'
import { SessionCombatDmControls } from './SessionCombatDmControls'
import { sessionCopy } from './sessionCopy'

function testStorage(): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? 'en' : null),
    setItem: () => undefined,
  }
}

function renderControls(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <LocaleProvider storage={testStorage()} documentTarget={null}>
        {ui}
      </LocaleProvider>
    </QueryClientProvider>,
  )
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
    initiative_total: null,
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

function makeCombat(status: 'initiative_pending' | 'running' | 'ended', entries: CombatEntryView[]): CombatDetailView {
  return {
    id: 'combat-test-1',
    campaign_id: 'camp-test-1',
    mode: 'quick',
    status,
    round_number: status === 'running' ? 1 : 0,
    current_turn_entry_id: status === 'running' ? entries[0]?.id ?? null : null,
    revision: 1,
    entries,
    combatants: [],
  }
}

const sampleMonsterOptions: SearchOption[] = [
  { value: 'srd5.1:monster:goblin', label: 'Goblin', description: 'CR 1/4' },
  { value: 'srd5.1:monster:orc', label: 'Orc', description: 'CR 1/2' },
]

describe('SessionCombatDmControls', () => {
  it('renders add-enemy form with mode tabs and monster options', () => {
    const copy = sessionCopy('en')
    const combat = makeCombat('initiative_pending', [
      makeEntry('e1', 'Mira', 'c1', null),
    ])

    const markup = renderControls(
      <SessionCombatDmControls
        combat={combat}
        copy={copy}
        monsterOptions={sampleMonsterOptions}
        roomId="room" campaignId="campaign" sessionId="session" token="token" onError={() => undefined} refresh={() => undefined}
      />,
    )

    expect(markup).toContain('data-combat-dm-controls="true"')
    expect(markup).toContain(copy.combatAddEnemyHeading)
    expect(markup).toContain(copy.combatModeSrdMonster)
    expect(markup).toContain(copy.combatModeQuickEnemy)
    expect(markup).toContain(copy.combatMonsterPickerLabel)
    expect(markup).toContain(copy.combatDisplayName)
    expect(markup).toContain(copy.combatPositionNote)
    expect(markup).toContain(copy.combatAddEnemyButton)
  })

  it('renders "Request initiative" enabled and "Finalize" disabled when an entry lacks initiative', () => {
    const copy = sessionCopy('en')
    const entries = [
      makeEntry('e1', 'Mira', 'c1', null, { initiative_total: 15 }),
      makeEntry('e2', 'Goblin', null, null, { initiative_total: null, initiative_roll_request_id: null }),
    ]
    const combat = makeCombat('initiative_pending', entries)

    const markup = renderControls(
      <SessionCombatDmControls combat={combat} copy={copy} monsterOptions={[]} roomId="room" campaignId="campaign" sessionId="session" token="token" onError={() => undefined} refresh={() => undefined} />,
    )

    // Request initiative button should NOT be disabled
    expect(markup).toContain(`<button type="button" class="button secondary compact">${copy.combatRequestInitiative}</button>`)
    // Finalize initiative button SHOULD be disabled
    expect(markup).toContain(`class="button primary compact" disabled="">${copy.combatFinalizeInitiative}</button>`)
    // Hint should be rendered
    expect(markup).toContain(copy.combatAwaitingRollHint)
  })

  it('renders "Finalize initiative" enabled and "Request" disabled when all active entries have initiative_total', () => {
    const copy = sessionCopy('en')
    const entries = [
      makeEntry('e1', 'Mira', 'c1', 1, { initiative_total: 18 }),
      makeEntry('e2', 'Goblin', null, 2, { initiative_total: 12 }),
    ]
    const combat = makeCombat('initiative_pending', entries)

    const markup = renderControls(
      <SessionCombatDmControls combat={combat} copy={copy} monsterOptions={[]} roomId="room" campaignId="campaign" sessionId="session" token="token" onError={() => undefined} refresh={() => undefined} />,
    )

    // Finalize initiative button should NOT be disabled
    expect(markup).toContain(`<button type="button" class="button primary compact">${copy.combatFinalizeInitiative}</button>`)
    // Request initiative button SHOULD be disabled
    expect(markup).toContain(`class="button secondary compact" disabled="">${copy.combatRequestInitiative}</button>`)
    // Hint should NOT be rendered
    expect(markup).not.toContain(copy.combatAwaitingRollHint)
  })

  it('renders "Advance turn" button when combat status is "running" and omits initiative controls', () => {
    const copy = sessionCopy('en')
    const entries = [
      makeEntry('e1', 'Mira', 'c1', 1, { initiative_total: 18 }),
      makeEntry('e2', 'Goblin', null, 2, { initiative_total: 12 }),
    ]
    const combat = makeCombat('running', entries)

    const markup = renderControls(
      <SessionCombatDmControls combat={combat} copy={copy} monsterOptions={[]} roomId="room" campaignId="campaign" sessionId="session" token="token" onError={() => undefined} refresh={() => undefined} />,
    )

    expect(markup).toContain(copy.combatAdvanceTurn)
    expect(markup).not.toContain(copy.combatRequestInitiative)
    expect(markup).not.toContain(copy.combatFinalizeInitiative)
  })

  it('does not render "Advance turn" button when combat status is "initiative_pending"', () => {
    const copy = sessionCopy('en')
    const entries = [
      makeEntry('e1', 'Mira', 'c1', null),
    ]
    const combat = makeCombat('initiative_pending', entries)

    const markup = renderControls(
      <SessionCombatDmControls combat={combat} copy={copy} monsterOptions={[]} roomId="room" campaignId="campaign" sessionId="session" token="token" onError={() => undefined} refresh={() => undefined} />,
    )

    expect(markup).not.toContain(copy.combatAdvanceTurn)
  })
})
