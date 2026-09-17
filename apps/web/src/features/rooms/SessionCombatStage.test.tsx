import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { CombatDetailView, CombatEntryView } from '../../api/combat'
import { LocaleProvider } from '../../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type LocaleStorage } from '../../i18n/locale'
import { SessionCombatStage } from './SessionCombatStage'
import { sessionCopy } from './sessionCopy'

function testStorage(): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? 'en' : null),
    setItem: () => undefined,
  }
}

function renderStage(ui: React.ReactElement) {
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
    const markup = renderStage(
      <SessionCombatStage combat={dmCombatDetail} myEntryIds={['entry-mira']} copy={copyEn} isCurrentDm={false} roomId="room" campaignId="campaign" sessionId="session" token="token" onError={() => undefined} refresh={() => undefined} />,
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
    const markup = renderStage(
      <SessionCombatStage combat={playerCombatDetail} myEntryIds={['entry-mira']} copy={copyEn} isCurrentDm={false} roomId="room" campaignId="campaign" sessionId="session" token="token" onError={() => undefined} refresh={() => undefined} />,
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
    const withoutNote = renderStage(
      <SessionCombatStage combat={playerCombatDetail} myEntryIds={['entry-mira']} copy={copyZh} isCurrentDm={false} roomId="room" campaignId="campaign" sessionId="session" token="token" onError={() => undefined} refresh={() => undefined} />,
    )
    expect(withoutNote).not.toContain(copyZh.combatPositionNote)

    const withNote = renderStage(
      <SessionCombatStage combat={dmCombatDetail} myEntryIds={['entry-mira']} copy={copyZh} isCurrentDm={false} roomId="room" campaignId="campaign" sessionId="session" token="token" onError={() => undefined} refresh={() => undefined} />,
    )
    expect(withNote).toContain(copyZh.combatPositionNote)
    expect(withNote).toContain('Behind barrels')
  })

  it('(d) shows your-turn badge when current turn is in myEntryIds, and omits it otherwise', () => {
    const notMyTurn = renderStage(
      <SessionCombatStage combat={dmCombatDetail} myEntryIds={['entry-mira']} copy={copyEn} isCurrentDm={false} roomId="room" campaignId="campaign" sessionId="session" token="token" onError={() => undefined} refresh={() => undefined} />,
    )
    expect(notMyTurn).not.toContain(copyEn.combatYourTurn)

    const myTurnCombat: CombatDetailView = {
      ...dmCombatDetail,
      current_turn_entry_id: 'entry-mira',
    }
    const isMyTurn = renderStage(
      <SessionCombatStage combat={myTurnCombat} myEntryIds={['entry-mira']} copy={copyEn} isCurrentDm={false} roomId="room" campaignId="campaign" sessionId="session" token="token" onError={() => undefined} refresh={() => undefined} />,
    )
    expect(isMyTurn).toContain(copyEn.combatYourTurn)
  })

  it('(e) renders display_name row in initiative list even when entry has no combatant detail', () => {
    const markup = renderStage(
      <SessionCombatStage combat={playerCombatDetail} myEntryIds={['entry-mira']} copy={copyEn} isCurrentDm={false} roomId="room" campaignId="campaign" sessionId="session" token="token" onError={() => undefined} refresh={() => undefined} />,
    )
    // entry-hidden is omitted from playerCombatDetail.combatants, but in initiative list:
    expect(markup).toContain('Ambush Lurker')
  })

  it('(f) renders DM controls region and roll button on pending enemy row when isCurrentDm is true', () => {
    const pendingEntryMira = makeEntry('entry-mira', 'Mira', 'char-mira', null, {
      initiative_roll_request_id: 'req-mira',
      initiative_roll_result_id: null,
      initiative_total: null,
    })
    const pendingEntryGoblin = makeEntry('entry-goblin', 'Goblin Scout', null, null, {
      initiative_roll_request_id: 'req-goblin',
      initiative_roll_result_id: null,
      initiative_total: null,
    })
    const pendingCombatDetail: CombatDetailView = {
      ...dmCombatDetail,
      status: 'initiative_pending',
      round_number: null,
      entries: [pendingEntryMira, pendingEntryGoblin],
    }

    const markup = renderStage(
      <SessionCombatStage
        combat={pendingCombatDetail}
        myEntryIds={['entry-mira']}
        copy={copyEn}
        isCurrentDm={true}
        roomId="room"
        campaignId="campaign"
        sessionId="session"
        token="token"
        onError={() => undefined}
        refresh={() => undefined}
      />,
    )

    expect(markup).toContain('data-combat-dm-controls="true"')
    expect(markup).toContain('data-initiative-roll="entry-goblin"')
    expect(markup).toContain('data-initiative-roll="entry-mira"')
  })

  it('(g) renders NO DM controls and roll button only for player entry, none on enemy row when isCurrentDm is false', () => {
    const pendingEntryMira = makeEntry('entry-mira', 'Mira', 'char-mira', null, {
      initiative_roll_request_id: 'req-mira',
      initiative_roll_result_id: null,
      initiative_total: null,
    })
    const pendingEntryGoblin = makeEntry('entry-goblin', 'Goblin Scout', null, null, {
      initiative_roll_request_id: 'req-goblin',
      initiative_roll_result_id: null,
      initiative_total: null,
    })
    const pendingCombatDetail: CombatDetailView = {
      ...playerCombatDetail,
      status: 'initiative_pending',
      round_number: null,
      entries: [pendingEntryMira, pendingEntryGoblin],
    }

    const markup = renderStage(
      <SessionCombatStage
        combat={pendingCombatDetail}
        myEntryIds={['entry-mira']}
        copy={copyEn}
        isCurrentDm={false}
        roomId="room"
        campaignId="campaign"
        sessionId="session"
        token="token"
        onError={() => undefined}
        refresh={() => undefined}
      />,
    )

    expect(markup).not.toContain('data-combat-dm-controls')
    expect(markup).toContain('data-initiative-roll="entry-mira"')
    expect(markup).not.toContain('data-initiative-roll="entry-goblin"')
  })
})
