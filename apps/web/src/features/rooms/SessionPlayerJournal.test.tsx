import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type { RoomCharacterSummary } from '../../api/campaigns'
import type {
  RuntimeWorldEntryDmView,
  RuntimeWorldEntryPlayerView,
} from '../../api/campaignRuntime'
import * as campaignRuntimeApi from '../../api/campaignRuntime'
import type { CampaignSeat } from '../../api/seats'
import type { SessionSnapshot, TableEvent } from '../../api/sessions'
import { LocaleProvider } from '../../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type LocaleStorage } from '../../i18n/locale'
import { campaignRuntimeCopy } from './campaignRuntimeCopy'
import { deriveLatestWorldEventSeq, LoadCoordinator } from './sessionCampaignRuntime'
import {
  applyPlayerJournalCommit,
  assertSafeRuntimeWorldEntryPlayerView,
  derivePlayerJournalIdentity,
  FORBIDDEN_DM_FIELDS,
  formatPlayerJournalCharacterNames,
  isPlayerJournalAuthorityLossError,
  isSafeRuntimeWorldEntryPlayerView,
  loadSessionPlayerJournal,
  selectPlayerJournalProjection,
  SessionPlayerJournal,
  SessionPlayerJournalView,
  UnexpectedDmProjectionError,
  type DerivePlayerJournalIdentityInput,
  type PlayerJournalManagedState,
  type PlayerJournalSelection,
} from './SessionPlayerJournal'
import {
  sessionTableSnapshotWithCurrentControllers,
} from './RoomSessionPage'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const SESSION_ID = '30000000-0000-4000-8000-000000000001'
const TOKEN = 'test-token-b5e'

function testStorage(locale: 'en' | 'zh-TW'): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? locale : null),
    setItem: () => undefined,
  }
}

function makeSeat(
  id: string,
  role: 'dm' | 'player' | 'spectator',
  controllerKind: 'human' | 'ai' | 'none',
  accessSessionId: string | null,
  label = 'Seat Label',
): CampaignSeat {
  return {
    id,
    campaign_id: CAMPAIGN_ID,
    role,
    label,
    controller_kind: controllerKind,
    controller_access_session_id: accessSessionId,
    controller_display_name: null,
    controller_authority: null,
    presence: 'connected',
    selected_character_id: null,
    archived_at: null,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
  }
}

function makeSnapshot(options: {
  status?: SessionSnapshot['status']
  dmSeatId?: string
  dmAccessSessionId?: string | null
  participants?: SessionSnapshot['participants']
}): SessionSnapshot {
  return {
    id: SESSION_ID,
    campaign_id: CAMPAIGN_ID,
    status: options.status ?? 'active',
    dm_seat_id: options.dmSeatId ?? 'dm-seat-1',
    dm_controller_access_session_id: options.dmAccessSessionId ?? 'dm-access-1',
    started_at: '2026-09-20T00:00:00Z',
    ended_at: options.status === 'ended' ? '2026-09-20T04:00:00Z' : null,
    participants: options.participants ?? [],
  }
}

const validPlayerQuest: RuntimeWorldEntryPlayerView = {
  id: '50000000-0000-4000-8000-000000000010',
  campaign_id: CAMPAIGN_ID,
  kind: 'quest',
  title: 'Find the Sunken Key',
  body: 'Locate the bronze key in the flooded temple ruins.',
  state: { kind: 'quest' },
  visibility: 'public',
  revision: 1,
  created_at: '2026-09-21T00:00:00Z',
  updated_at: '2026-09-21T00:00:00Z',
}

const validPlayerFact: RuntimeWorldEntryPlayerView = {
  id: '50000000-0000-4000-8000-000000000011',
  campaign_id: CAMPAIGN_ID,
  kind: 'fact',
  title: 'The Blood Moon Rises',
  body: 'Local elders warn of strange tide surges during the full moon.',
  state: { kind: 'fact' },
  visibility: 'public',
  revision: 2,
  created_at: '2026-09-21T00:00:00Z',
  updated_at: '2026-09-21T00:00:00Z',
}

const validCharacterKnowledge: RuntimeWorldEntryPlayerView = {
  id: '50000000-0000-4000-8000-000000000012',
  campaign_id: CAMPAIGN_ID,
  kind: 'secret',
  title: 'Secret Family Crest',
  body: 'The crest on the dagger matches the sigil of House Ravencrest.',
  state: { kind: 'secret' },
  visibility: 'character',
  revision: 3,
  created_at: '2026-09-21T00:00:00Z',
  updated_at: '2026-09-21T00:00:00Z',
}

const sampleCharacterSummary: RoomCharacterSummary = {
  id: '60000000-0000-4000-8000-000000000001',
  name: 'Thorin Stonehelm',
  level: 3,
  class_summary: 'Fighter 3',
  version_no: 1,
}

describe('Player Journal mount helper truth table (derivePlayerJournalIdentity)', () => {
  it('mounts for active Human Player controller with an active Character', () => {
    const tableSnapshot = makeSnapshot({
      participants: [
        {
          id: 'p-1',
          seat_id: 'seat-p1',
          role: 'player',
          controller_kind_at_join: 'human',
          controller_access_session_id_at_join: 'access-human-1',
          active_character_id: '60000000-0000-4000-8000-000000000001',
        },
      ],
    })

    const identity = derivePlayerJournalIdentity({
      status: 'active',
      isCurrentDm: false,
      callerAccessSessionId: 'access-human-1',
      tableSnapshot,
    })

    expect(identity).toEqual({
      callerAccessSessionId: 'access-human-1',
      controlledSeatIds: ['seat-p1'],
      activeCharacterIds: ['60000000-0000-4000-8000-000000000001'],
      projectionKey: 'access-human-1:seat-p1:60000000-0000-4000-8000-000000000001',
    })
  })

  it('mounts for active Player controller even when active_character_id is null', () => {
    const tableSnapshot = makeSnapshot({
      participants: [
        {
          id: 'p-1',
          seat_id: 'seat-p1',
          role: 'player',
          controller_kind_at_join: 'human',
          controller_access_session_id_at_join: 'access-human-1',
          active_character_id: null,
        },
      ],
    })

    const identity = derivePlayerJournalIdentity({
      status: 'active',
      isCurrentDm: false,
      callerAccessSessionId: 'access-human-1',
      tableSnapshot,
    })

    expect(identity).not.toBeNull()
    expect(identity?.activeCharacterIds).toEqual([])
    expect(identity?.controlledSeatIds).toEqual(['seat-p1'])
    expect(identity?.projectionKey).toBe('access-human-1:seat-p1:')
  })

  it('handles multiple controlled Player seats with sorted deterministic keys', () => {
    const tableSnapshot = makeSnapshot({
      participants: [
        {
          id: 'p-2',
          seat_id: 'seat-p2',
          role: 'player',
          controller_kind_at_join: 'human',
          controller_access_session_id_at_join: 'access-human-multi',
          active_character_id: 'char-2',
        },
        {
          id: 'p-1',
          seat_id: 'seat-p1',
          role: 'player',
          controller_kind_at_join: 'human',
          controller_access_session_id_at_join: 'access-human-multi',
          active_character_id: 'char-1',
        },
      ],
    })

    const identity = derivePlayerJournalIdentity({
      status: 'active',
      isCurrentDm: false,
      callerAccessSessionId: 'access-human-multi',
      tableSnapshot,
    })

    expect(identity).toEqual({
      callerAccessSessionId: 'access-human-multi',
      controlledSeatIds: ['seat-p1', 'seat-p2'],
      activeCharacterIds: ['char-1', 'char-2'],
      projectionKey: 'access-human-multi:seat-p1,seat-p2:char-1,char-2',
    })
  })

  it('returns null when caller is current DM', () => {
    const tableSnapshot = makeSnapshot({
      participants: [
        {
          id: 'p-1',
          seat_id: 'seat-p1',
          role: 'player',
          controller_kind_at_join: 'human',
          controller_access_session_id_at_join: 'access-dm',
          active_character_id: 'char-1',
        },
      ],
    })

    const identity = derivePlayerJournalIdentity({
      status: 'active',
      isCurrentDm: true,
      callerAccessSessionId: 'access-dm',
      tableSnapshot,
    })

    expect(identity).toBeNull()
  })

  it('returns null for spectator or non-participant callers', () => {
    const tableSnapshot = makeSnapshot({
      participants: [
        {
          id: 'p-spec',
          seat_id: 'seat-spec',
          role: 'spectator',
          controller_kind_at_join: 'human',
          controller_access_session_id_at_join: 'access-spectator',
          active_character_id: null,
        },
      ],
    })

    // Spectator
    expect(
      derivePlayerJournalIdentity({
        status: 'active',
        isCurrentDm: false,
        callerAccessSessionId: 'access-spectator',
        tableSnapshot,
      }),
    ).toBeNull()

    // Non-participant
    expect(
      derivePlayerJournalIdentity({
        status: 'active',
        isCurrentDm: false,
        callerAccessSessionId: 'access-unknown',
        tableSnapshot,
      }),
    ).toBeNull()

    // Null callerAccessSessionId
    expect(
      derivePlayerJournalIdentity({
        status: 'active',
        isCurrentDm: false,
        callerAccessSessionId: null,
        tableSnapshot,
      }),
    ).toBeNull()
  })

  it('uses current Seat truth when old join controller was replaced', () => {
    const rawSnapshot = makeSnapshot({
      participants: [
        {
          id: 'p-1',
          seat_id: 'seat-1',
          role: 'player',
          controller_kind_at_join: 'human',
          controller_access_session_id_at_join: 'old-human',
          active_character_id: 'char-1',
        },
      ],
    })

    // Handoff to new human controller
    const updatedSeat = makeSeat('seat-1', 'player', 'human', 'new-human')
    const tableSnapshot = sessionTableSnapshotWithCurrentControllers(rawSnapshot, [updatedSeat])

    // Old human no longer has control
    expect(
      derivePlayerJournalIdentity({
        status: 'active',
        isCurrentDm: false,
        callerAccessSessionId: 'old-human',
        tableSnapshot,
      }),
    ).toBeNull()

    // New human has control
    const newIdentity = derivePlayerJournalIdentity({
      status: 'active',
      isCurrentDm: false,
      callerAccessSessionId: 'new-human',
      tableSnapshot,
    })
    expect(newIdentity?.callerAccessSessionId).toBe('new-human')
    expect(newIdentity?.controlledSeatIds).toEqual(['seat-1'])

    // AI takeover
    const aiSeat = makeSeat('seat-1', 'player', 'ai', null)
    const aiTableSnapshot = sessionTableSnapshotWithCurrentControllers(rawSnapshot, [aiSeat])
    expect(
      derivePlayerJournalIdentity({
        status: 'active',
        isCurrentDm: false,
        callerAccessSessionId: 'new-human',
        tableSnapshot: aiTableSnapshot,
      }),
    ).toBeNull()
  })

  it('room owner watching AI DM sees Journal only if also controlling a Player participant', () => {
    const withoutPlayer = makeSnapshot({
      dmSeatId: 'seat-ai-dm',
      dmAccessSessionId: null,
      participants: [
        {
          id: 'p-other',
          seat_id: 'seat-other',
          role: 'player',
          controller_kind_at_join: 'human',
          controller_access_session_id_at_join: 'other-player',
          active_character_id: 'char-other',
        },
      ],
    })

    // Owner without player seat
    expect(
      derivePlayerJournalIdentity({
        status: 'active',
        isCurrentDm: false,
        callerAccessSessionId: 'owner-access',
        tableSnapshot: withoutPlayer,
      }),
    ).toBeNull()

    // Owner with player seat
    const withPlayer = makeSnapshot({
      dmSeatId: 'seat-ai-dm',
      dmAccessSessionId: null,
      participants: [
        {
          id: 'p-owner',
          seat_id: 'seat-owner-player',
          role: 'player',
          controller_kind_at_join: 'human',
          controller_access_session_id_at_join: 'owner-access',
          active_character_id: 'char-owner',
        },
      ],
    })

    const ownerIdentity = derivePlayerJournalIdentity({
      status: 'active',
      isCurrentDm: false,
      callerAccessSessionId: 'owner-access',
      tableSnapshot: withPlayer,
    })
    expect(ownerIdentity).not.toBeNull()
    expect(ownerIdentity?.controlledSeatIds).toEqual(['seat-owner-player'])
  })

  it('returns null when session is ended or abandoned', () => {
    const tableSnapshot = makeSnapshot({
      participants: [
        {
          id: 'p-1',
          seat_id: 'seat-p1',
          role: 'player',
          controller_kind_at_join: 'human',
          controller_access_session_id_at_join: 'access-human-1',
          active_character_id: 'char-1',
        },
      ],
    })

    expect(
      derivePlayerJournalIdentity({
        status: 'ended',
        isCurrentDm: false,
        callerAccessSessionId: 'access-human-1',
        tableSnapshot,
      }),
    ).toBeNull()

    expect(
      derivePlayerJournalIdentity({
        status: 'abandoned',
        isCurrentDm: false,
        callerAccessSessionId: 'access-human-1',
        tableSnapshot,
      }),
    ).toBeNull()
  })
})

describe('Projection key stability and reset semantics', () => {
  it('changes key when access id, controlled seat set, or active character changes', () => {
    const baseInput: DerivePlayerJournalIdentityInput = {
      status: 'active',
      isCurrentDm: false,
      callerAccessSessionId: 'access-1',
      tableSnapshot: makeSnapshot({
        participants: [
          {
            id: 'p-1',
            seat_id: 'seat-1',
            role: 'player',
            controller_kind_at_join: 'human',
            controller_access_session_id_at_join: 'access-1',
            active_character_id: 'char-1',
          },
        ],
      }),
    }

    const baseKey = derivePlayerJournalIdentity(baseInput)?.projectionKey

    // Access ID change (reconnect)
    const reconnectInput: DerivePlayerJournalIdentityInput = {
      ...baseInput,
      callerAccessSessionId: 'access-reconnected',
      tableSnapshot: makeSnapshot({
        participants: [
          {
            id: 'p-1',
            seat_id: 'seat-1',
            role: 'player',
            controller_kind_at_join: 'human',
            controller_access_session_id_at_join: 'access-reconnected',
            active_character_id: 'char-1',
          },
        ],
      }),
    }
    expect(derivePlayerJournalIdentity(reconnectInput)?.projectionKey).not.toBe(baseKey)

    // Controlled seat set change
    const multiSeatInput: DerivePlayerJournalIdentityInput = {
      ...baseInput,
      tableSnapshot: makeSnapshot({
        participants: [
          {
            id: 'p-1',
            seat_id: 'seat-1',
            role: 'player',
            controller_kind_at_join: 'human',
            controller_access_session_id_at_join: 'access-1',
            active_character_id: 'char-1',
          },
          {
            id: 'p-2',
            seat_id: 'seat-2',
            role: 'player',
            controller_kind_at_join: 'human',
            controller_access_session_id_at_join: 'access-1',
            active_character_id: 'char-2',
          },
        ],
      }),
    }
    expect(derivePlayerJournalIdentity(multiSeatInput)?.projectionKey).not.toBe(baseKey)

    // Active character change
    const charChangeInput: DerivePlayerJournalIdentityInput = {
      ...baseInput,
      tableSnapshot: makeSnapshot({
        participants: [
          {
            id: 'p-1',
            seat_id: 'seat-1',
            role: 'player',
            controller_kind_at_join: 'human',
            controller_access_session_id_at_join: 'access-1',
            active_character_id: 'char-different',
          },
        ],
      }),
    }
    expect(derivePlayerJournalIdentity(charChangeInput)?.projectionKey).not.toBe(baseKey)
  })

  it('seat label changes do NOT change projection key', () => {
    const rawSnapshot = makeSnapshot({
      participants: [
        {
          id: 'p-1',
          seat_id: 'seat-1',
          role: 'player',
          controller_kind_at_join: 'human',
          controller_access_session_id_at_join: 'access-1',
          active_character_id: 'char-1',
        },
      ],
    })

    const seatWithOldLabel = makeSeat('seat-1', 'player', 'human', 'access-1', 'Old Mira Seat')
    const snap1 = sessionTableSnapshotWithCurrentControllers(rawSnapshot, [seatWithOldLabel])
    const key1 = derivePlayerJournalIdentity({
      status: 'active',
      isCurrentDm: false,
      callerAccessSessionId: 'access-1',
      tableSnapshot: snap1,
    })?.projectionKey

    const seatWithNewLabel = makeSeat('seat-1', 'player', 'human', 'access-1', 'Renamed Mira Seat')
    const snap2 = sessionTableSnapshotWithCurrentControllers(rawSnapshot, [seatWithNewLabel])
    const key2 = derivePlayerJournalIdentity({
      status: 'active',
      isCurrentDm: false,
      callerAccessSessionId: 'access-1',
      tableSnapshot: snap2,
    })?.projectionKey

    expect(key1).toBe(key2)
  })
})

describe('Safe Player-View Guard and Exact DTO Boundary (isSafeRuntimeWorldEntryPlayerView)', () => {
  it('accepts valid Player DTOs and verifies safe predicates', () => {
    expect(isSafeRuntimeWorldEntryPlayerView(validPlayerQuest)).toBe(true)
    expect(isSafeRuntimeWorldEntryPlayerView(validPlayerFact)).toBe(true)
    expect(isSafeRuntimeWorldEntryPlayerView(validCharacterKnowledge)).toBe(true)

    expect(() => assertSafeRuntimeWorldEntryPlayerView(validPlayerQuest)).not.toThrow()
  })

  it('rejects every forbidden DM field', () => {
    for (const forbiddenField of FORBIDDEN_DM_FIELDS) {
      const contaminated = {
        ...validPlayerQuest,
        [forbiddenField]: forbiddenField === 'needs_review' ? false : 'forbidden_value',
      }
      expect(isSafeRuntimeWorldEntryPlayerView(contaminated)).toBe(false)
      expect(() => assertSafeRuntimeWorldEntryPlayerView(contaminated)).toThrow(
        UnexpectedDmProjectionError,
      )
    }
  })

  it('rejects undefined forbidden fields and undefined unknown fields', () => {
    const undefinedForbidden = {
      ...validPlayerQuest,
      dm_notes: undefined,
    }
    expect(isSafeRuntimeWorldEntryPlayerView(undefinedForbidden)).toBe(false)
    expect(() => assertSafeRuntimeWorldEntryPlayerView(undefinedForbidden)).toThrow(
      UnexpectedDmProjectionError,
    )

    const undefinedUnknown = {
      ...validPlayerQuest,
      extra_unknown_key: undefined,
    }
    expect(isSafeRuntimeWorldEntryPlayerView(undefinedUnknown)).toBe(false)
  })

  it('rejects unknown extra top-level fields', () => {
    const withExtraField = {
      ...validPlayerQuest,
      unknown_extra: 123,
    }
    expect(isSafeRuntimeWorldEntryPlayerView(withExtraField)).toBe(false)
    expect(() => assertSafeRuntimeWorldEntryPlayerView(withExtraField)).toThrow(
      UnexpectedDmProjectionError,
    )
  })

  it('rejects unknown kind or invalid kind string', () => {
    const unknownKind = {
      ...validPlayerQuest,
      kind: 'unknown_kind',
      state: { kind: 'unknown_kind' },
    }
    expect(isSafeRuntimeWorldEntryPlayerView(unknownKind)).toBe(false)
  })

  it('rejects array, null, or non-object state', () => {
    expect(isSafeRuntimeWorldEntryPlayerView({ ...validPlayerQuest, state: null })).toBe(false)
    expect(isSafeRuntimeWorldEntryPlayerView({ ...validPlayerQuest, state: [] })).toBe(false)
    expect(isSafeRuntimeWorldEntryPlayerView({ ...validPlayerQuest, state: 'string-state' })).toBe(
      false,
    )
  })

  it('rejects mismatched state.kind', () => {
    const mismatchedState = {
      ...validPlayerQuest,
      state: { kind: 'npc' },
    }
    expect(isSafeRuntimeWorldEntryPlayerView(mismatchedState)).toBe(false)
    expect(() => assertSafeRuntimeWorldEntryPlayerView(mismatchedState)).toThrow(
      UnexpectedDmProjectionError,
    )
  })

  it('rejects non-finite revision or invalid revision number', () => {
    expect(isSafeRuntimeWorldEntryPlayerView({ ...validPlayerQuest, revision: NaN })).toBe(false)
    expect(isSafeRuntimeWorldEntryPlayerView({ ...validPlayerQuest, revision: Infinity })).toBe(
      false,
    )
    expect(isSafeRuntimeWorldEntryPlayerView({ ...validPlayerQuest, revision: 0 })).toBe(false)
    expect(isSafeRuntimeWorldEntryPlayerView({ ...validPlayerQuest, revision: -1 })).toBe(false)
    expect(isSafeRuntimeWorldEntryPlayerView({ ...validPlayerQuest, revision: 1.5 })).toBe(false)
  })

  it('rejects missing required fields', () => {
    const { revision: _rev, ...missingRevision } = validPlayerQuest
    expect(isSafeRuntimeWorldEntryPlayerView(missingRevision)).toBe(false)
  })

  it('rejects dm_only visibility entries', () => {
    const dmOnlyEntry = {
      ...validPlayerQuest,
      visibility: 'dm_only' as const,
    }
    expect(isSafeRuntimeWorldEntryPlayerView(dmOnlyEntry)).toBe(false)
    expect(() => assertSafeRuntimeWorldEntryPlayerView(dmOnlyEntry)).toThrow(
      UnexpectedDmProjectionError,
    )
  })

  it('rejects complete DM view fixtures', () => {
    const fullDmView: RuntimeWorldEntryDmView = {
      id: 'dm-view-1',
      campaign_id: CAMPAIGN_ID,
      kind: 'quest',
      title: 'Secret Quest',
      body: 'Hidden details',
      state: { kind: 'quest' },
      visibility: 'public',
      dm_notes: 'Private DM instructions',
      needs_review: false,
      source_adventure_entry_id: null,
      provenance_json: null,
      character_recipient_ids: [],
      revision: 1,
      created_by_actor_kind: 'human',
      created_by_actor_id: 'dm-seat',
      created_at: '2026-09-20T00:00:00Z',
      updated_at: '2026-09-20T00:00:00Z',
      archived_at: null,
    }

    expect(isSafeRuntimeWorldEntryPlayerView(fullDmView)).toBe(false)
    expect(() => assertSafeRuntimeWorldEntryPlayerView(fullDmView)).toThrow(
      UnexpectedDmProjectionError,
    )
  })
})

describe('No-active-Character Rejection and Projection Selector (selectPlayerJournalProjection)', () => {
  it('rejects character-visible entry when caller has no active character', () => {
    expect(() =>
      selectPlayerJournalProjection([validCharacterKnowledge], false),
    ).toThrow(UnexpectedDmProjectionError)

    // Public items succeed even with allowCharacterKnowledge=false
    const selection = selectPlayerJournalProjection([validPlayerQuest, validPlayerFact], false)
    expect(selection.publicEntries).toHaveLength(2)
    expect(selection.characterEntries).toHaveLength(0)
  })

  it('accepts character-visible entry when caller has active character', () => {
    const selection = selectPlayerJournalProjection(
      [validPlayerQuest, validCharacterKnowledge],
      true,
    )
    expect(selection.publicEntries).toHaveLength(1)
    expect(selection.characterEntries).toHaveLength(1)
    expect(selection.characterEntries[0].id).toBe(validCharacterKnowledge.id)
  })

  it('selects public quests and facts, excludes other public kinds without count hints', () => {
    const publicScene: RuntimeWorldEntryPlayerView = {
      id: 'scene-1',
      campaign_id: CAMPAIGN_ID,
      kind: 'scene',
      title: 'Campfire Clearing',
      body: 'Quiet woods',
      state: { kind: 'scene' },
      visibility: 'public',
      revision: 1,
      created_at: '2026-09-21T00:00:00Z',
      updated_at: '2026-09-21T00:00:00Z',
    }

    const publicNpc: RuntimeWorldEntryPlayerView = {
      id: 'npc-1',
      campaign_id: CAMPAIGN_ID,
      kind: 'npc',
      title: 'Old Hermit',
      body: 'Grumpy sage',
      state: { kind: 'npc', monster_instance_id: null, monster_template_ref: null },
      visibility: 'public',
      revision: 1,
      created_at: '2026-09-21T00:00:00Z',
      updated_at: '2026-09-21T00:00:00Z',
    }

    const selection = selectPlayerJournalProjection(
      [validPlayerQuest, publicScene, validPlayerFact, publicNpc, validCharacterKnowledge],
      true,
    )

    // Public entries only contain quest and fact
    expect(selection.publicEntries).toHaveLength(2)
    expect(selection.publicEntries.map((e) => e.id)).toEqual([
      validPlayerQuest.id,
      validPlayerFact.id,
    ])

    // Character entries contain character knowledge
    expect(selection.characterEntries).toHaveLength(1)
    expect(selection.characterEntries[0].id).toBe(validCharacterKnowledge.id)
  })

  it('selectPlayerJournalProjection accepts a valid list with character entries', () => {
    const selection = selectPlayerJournalProjection(
      [validPlayerQuest, validCharacterKnowledge],
      true,
    )
    expect(selection.publicEntries).toHaveLength(1)
    expect(selection.characterEntries).toHaveLength(1)
  })
})

describe('Loader boundary (loadSessionPlayerJournal)', () => {
  it('calls only listActiveRuntimeEntries with default active rows and zero Adventure/override/context calls', async () => {
    const listSpy = vi
      .spyOn(campaignRuntimeApi, 'listActiveRuntimeEntries')
      .mockResolvedValue([validPlayerQuest, validPlayerFact, validCharacterKnowledge])
    const contextSpy = vi.spyOn(campaignRuntimeApi, 'getActiveRuntimeContext')
    const overrideSpy = vi.spyOn(campaignRuntimeApi, 'listActiveOverrides')

    try {
      const selection = await loadSessionPlayerJournal(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN, true)
      expect(selection.publicEntries).toHaveLength(2)
      expect(selection.characterEntries).toHaveLength(1)

      expect(listSpy).toHaveBeenCalledTimes(1)
      expect(listSpy).toHaveBeenCalledWith(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)

      expect(contextSpy).not.toHaveBeenCalled()
      expect(overrideSpy).not.toHaveBeenCalled()
    } finally {
      vi.restoreAllMocks()
    }
  })

  it('rejects entire load when allowCharacterKnowledge=false and character entry returned', async () => {
    vi.spyOn(campaignRuntimeApi, 'listActiveRuntimeEntries').mockResolvedValue([
      validPlayerQuest,
      validCharacterKnowledge,
    ])

    try {
      await expect(
        loadSessionPlayerJournal(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN, false),
      ).rejects.toThrow(UnexpectedDmProjectionError)
    } finally {
      vi.restoreAllMocks()
    }
  })

  it('rejects entire load when any entry contains DM-only projection', async () => {
    const contaminatedList = [
      validPlayerQuest,
      {
        ...validPlayerFact,
        dm_notes: 'leaked note',
      },
    ]

    vi.spyOn(campaignRuntimeApi, 'listActiveRuntimeEntries').mockResolvedValue(contaminatedList)

    try {
      await expect(
        loadSessionPlayerJournal(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN, true),
      ).rejects.toThrow(UnexpectedDmProjectionError)
    } finally {
      vi.restoreAllMocks()
    }
  })
})

describe('Generational ordering and commit helper (applyPlayerJournalCommit)', () => {
  const initialManagedState: PlayerJournalManagedState = {
    selection: null,
    error: null,
    accessUnavailable: false,
    lastLoadedCursor: -1,
  }

  const selectionA: PlayerJournalSelection = {
    publicEntries: [validPlayerQuest],
    characterEntries: [],
  }

  const selectionB: PlayerJournalSelection = {
    publicEntries: [validPlayerQuest, validPlayerFact],
    characterEntries: [validCharacterKnowledge],
  }

  it('newer projection wins over older response', () => {
    const coord = new LoadCoordinator()
    const gen1 = coord.nextGeneration() // 1
    const gen2 = coord.nextGeneration() // 2

    // Load 1 completes after Load 2 has started
    const res1 = applyPlayerJournalCommit(
      initialManagedState,
      { kind: 'success', generation: gen1, selection: selectionA, cursor: 1 },
      coord,
    )
    expect(res1).toBeNull() // Discarded because gen 1 is not current

    // Load 2 completes
    const res2 = applyPlayerJournalCommit(
      initialManagedState,
      { kind: 'success', generation: gen2, selection: selectionB, cursor: 2 },
      coord,
    )
    expect(res2).toEqual({
      selection: selectionB,
      error: null,
      accessUnavailable: false,
      lastLoadedCursor: 2,
    })
  })

  it('authority/projection failure clears selection and invalidates older in-flight responses', () => {
    const coord = new LoadCoordinator()
    const gen1 = coord.nextGeneration() // 1
    const gen2 = coord.nextGeneration() // 2

    const stateWithData: PlayerJournalManagedState = {
      selection: selectionA,
      error: null,
      accessUnavailable: false,
      lastLoadedCursor: 1,
    }

    // Load 2 experiences authority loss (e.g. session ended or forbidden or unexpected DM)
    const stateAfterLoss = applyPlayerJournalCommit(
      stateWithData,
      { kind: 'authority_loss', generation: gen2, errorMessage: 'Access unavailable' },
      coord,
    )
    expect(stateAfterLoss).toEqual({
      selection: null,
      error: 'Access unavailable',
      accessUnavailable: true,
      lastLoadedCursor: 1,
    })

    // Coordinator was invalidated by authority_loss, so gen 1 (or any prior gen) cannot commit
    expect(stateAfterLoss).not.toBeNull()
    if (!stateAfterLoss) throw new Error('expected authority-loss state')
    const staleCommit = applyPlayerJournalCommit(
      stateAfterLoss,
      { kind: 'success', generation: gen1, selection: selectionA, cursor: 1 },
      coord,
    )
    expect(staleCommit).toBeNull()
  })

  it('generic refresh failure preserves prior safe selection', () => {
    const coord = new LoadCoordinator()
    const gen1 = coord.nextGeneration() // 1

    const stateWithData: PlayerJournalManagedState = {
      selection: selectionA,
      error: null,
      accessUnavailable: false,
      lastLoadedCursor: 5,
    }

    const stateAfterGenericError = applyPlayerJournalCommit(
      stateWithData,
      { kind: 'generic_error', generation: gen1, errorMessage: 'Failed to load' },
      coord,
    )
    expect(stateAfterGenericError).toEqual({
      selection: selectionA, // Preserved!
      error: 'Failed to load',
      accessUnavailable: false,
      lastLoadedCursor: 5,
    })
  })

  it('ordered deferred loads demonstrate newer wins, failure invalidation, and preservation', async () => {
    // Simulate ordered async execution
    const coord = new LoadCoordinator()
    let currentState: PlayerJournalManagedState = { ...initialManagedState }

    function createDeferred<T>() {
      let resolve!: (val: T) => void
      let reject!: (err: unknown) => void
      const promise = new Promise<T>((res, rej) => {
        resolve = res
        reject = rej
      })
      return { promise, resolve, reject }
    }

    // Start load 1
    const gen1 = coord.nextGeneration()
    const def1 = createDeferred<PlayerJournalSelection>()

    // Start load 2 (e.g. event arrived)
    const gen2 = coord.nextGeneration()
    const def2 = createDeferred<PlayerJournalSelection>()

    // Load 2 resolves first
    def2.resolve(selectionB)
    const data2 = await def2.promise
    const commit2 = applyPlayerJournalCommit(
      currentState,
      { kind: 'success', generation: gen2, selection: data2, cursor: 2 },
      coord,
    )
    expect(commit2).not.toBeNull()
    if (commit2) currentState = commit2
    expect(currentState.selection).toBe(selectionB)

    // Load 1 resolves later with older data
    def1.resolve(selectionA)
    const data1 = await def1.promise
    const commit1 = applyPlayerJournalCommit(
      currentState,
      { kind: 'success', generation: gen1, selection: data1, cursor: 1 },
      coord,
    )
    expect(commit1).toBeNull()
    expect(currentState.selection).toBe(selectionB) // Older response did not overwrite!

    // Now start load 3 which fails with generic error
    const gen3 = coord.nextGeneration()
    const commit3 = applyPlayerJournalCommit(
      currentState,
      { kind: 'generic_error', generation: gen3, errorMessage: 'Network 500' },
      coord,
    )
    expect(commit3?.selection).toBe(selectionB) // Preserved prior selection!
  })
})

describe('Event-driven refresh and error classification', () => {
  it('derives cursor only from current-session world.* events', () => {
    const events: TableEvent[] = [
      {
        id: 'ev-1',
        session_id: SESSION_ID,
        seq: 1,
        kind: 'roll.created',
        acting_seat_id: 'seat-1',
        subject_seat_id: null,
        subject_character_id: null,
        execution_mode: 'self',
        visibility: 'public',
        recipient_seat_ids: [],
        payload_version: 1,
        payload: {},
        created_at: '2026-09-21T00:00:00Z',
      },
      {
        id: 'ev-2',
        session_id: 'other-session-uuid',
        seq: 99,
        kind: 'world.entry_created',
        acting_seat_id: 'seat-dm',
        subject_seat_id: null,
        subject_character_id: null,
        execution_mode: 'self',
        visibility: 'public',
        recipient_seat_ids: [],
        payload_version: 1,
        payload: {},
        created_at: '2026-09-21T00:00:00Z',
      },
      {
        id: 'ev-3',
        session_id: SESSION_ID,
        seq: 5,
        kind: 'world.entry_created',
        acting_seat_id: 'seat-dm',
        subject_seat_id: null,
        subject_character_id: null,
        execution_mode: 'self',
        visibility: 'public',
        recipient_seat_ids: [],
        payload_version: 1,
        payload: {},
        created_at: '2026-09-21T00:00:00Z',
      },
    ]

    expect(deriveLatestWorldEventSeq(events, SESSION_ID)).toBe(5)
    expect(deriveLatestWorldEventSeq(events.slice(0, 1), SESSION_ID)).toBe(0)
    expect(deriveLatestWorldEventSeq(events.slice(1, 2), SESSION_ID)).toBe(0)
  })

  it('classifies authority errors vs generic network errors without casts', () => {
    expect(isPlayerJournalAuthorityLossError(new UnexpectedDmProjectionError())).toBe(true)

    expect(
      isPlayerJournalAuthorityLossError(
        new campaignRuntimeApi.CampaignRuntimeApiError(
          409,
          'campaign_runtime_session_not_active',
          'Not active',
        ),
      ),
    ).toBe(true)

    expect(
      isPlayerJournalAuthorityLossError({
        code: 'session_not_active',
      }),
    ).toBe(true)

    expect(
      isPlayerJournalAuthorityLossError(
        new campaignRuntimeApi.CampaignRuntimeApiError(
          403,
          'campaign_runtime_forbidden',
          'Forbidden',
        ),
      ),
    ).toBe(true)

    expect(isPlayerJournalAuthorityLossError(new Error('Network failure'))).toBe(false)
    expect(
      isPlayerJournalAuthorityLossError(
        new campaignRuntimeApi.CampaignRuntimeApiError(500, 'internal_error', 'Server error'),
      ),
    ).toBe(false)
  })
})

describe('Pure View Rendering and Identity Secrecy (SessionPlayerJournalView)', () => {
  const copyEn = campaignRuntimeCopy('en')
  const copyZhTw = campaignRuntimeCopy('zh-TW')

  const selectionBoth: PlayerJournalSelection = {
    publicEntries: [validPlayerQuest, validPlayerFact],
    characterEntries: [validCharacterKnowledge],
  }

  it('renders correctly in en with public quests/facts and character knowledge', () => {
    const html = renderToStaticMarkup(
      createElement(SessionPlayerJournalView, {
        selection: selectionBoth,
        characterNames: ['Thorin Stonehelm'],
        hasActiveCharacters: true,
        loading: false,
        error: null,
        accessUnavailable: false,
        copy: copyEn,
        onRetry: vi.fn(),
      }),
    )

    expect(html).toContain(copyEn.playerJournalHeading)
    expect(html).toContain(copyEn.journalPublicGroupHeading)
    expect(html).toContain(copyEn.journalCharacterGroupHeading)

    // Quests and facts
    expect(html).toContain('Find the Sunken Key')
    expect(html).toContain('The Blood Moon Rises')
    expect(html).toContain(copyEn.kindQuest)
    expect(html).toContain(copyEn.kindFact)

    // Character knowledge
    expect(html).toContain('Secret Family Crest')
    expect(html).toContain('Thorin Stonehelm')
    expect(html).toContain(copyEn.visibilityCharacter)

    // Omit absent / forbidden fields
    expect(html).not.toContain('dm_notes')
    expect(html).not.toContain('character_recipient_ids')
    expect(html).not.toContain('needs_review')
    expect(html).not.toContain('provenance')
    expect(html).not.toContain('null')
    expect(html).not.toContain('?')
  })

  it('renders correctly in zh-TW with public quests/facts and character knowledge', () => {
    const html = renderToStaticMarkup(
      createElement(SessionPlayerJournalView, {
        selection: selectionBoth,
        characterNames: ['索林·石盔'],
        hasActiveCharacters: true,
        loading: false,
        error: null,
        accessUnavailable: false,
        copy: copyZhTw,
        onRetry: vi.fn(),
      }),
    )

    expect(html).toContain(copyZhTw.playerJournalHeading)
    expect(html).toContain(copyZhTw.journalPublicGroupHeading)
    expect(html).toContain(copyZhTw.journalCharacterGroupHeading)
    expect(html).toContain('Find the Sunken Key')
    expect(html).toContain('索林·石盔')
    expect(html).toContain(copyZhTw.kindQuest)
    expect(html).toContain(copyZhTw.kindFact)
    expect(html).toContain(copyZhTw.visibilityCharacter)
  })

  it('does NOT leak raw character IDs when character summary is missing; renders localized fallback', () => {
    const missingSummaryCharId = '99999999-9999-4000-8000-999999999999'

    // Verify helper replaces missing summary name with fallback label and never returns raw ID
    const namesEn = formatPlayerJournalCharacterNames(
      [missingSummaryCharId],
      [],
      copyEn.journalActiveCharacterFallback,
    )
    expect(namesEn).toEqual([copyEn.journalActiveCharacterFallback])
    expect(namesEn[0]).toBe('Active character')
    expect(namesEn).not.toContain(missingSummaryCharId)

    const namesZhTw = formatPlayerJournalCharacterNames(
      [missingSummaryCharId],
      [],
      copyZhTw.journalActiveCharacterFallback,
    )
    expect(namesZhTw).toEqual([copyZhTw.journalActiveCharacterFallback])
    expect(namesZhTw[0]).toBe('目前角色')
    expect(namesZhTw).not.toContain(missingSummaryCharId)

    // In en
    const htmlEn = renderToStaticMarkup(
      createElement(SessionPlayerJournalView, {
        selection: selectionBoth,
        characterNames: namesEn,
        hasActiveCharacters: true,
        loading: false,
        error: null,
        accessUnavailable: false,
        copy: copyEn,
        onRetry: vi.fn(),
      }),
    )

    expect(htmlEn).not.toContain(missingSummaryCharId)
    expect(htmlEn).toContain(copyEn.journalActiveCharacterFallback)

    // In zh-TW
    const htmlZhTw = renderToStaticMarkup(
      createElement(SessionPlayerJournalView, {
        selection: selectionBoth,
        characterNames: namesZhTw,
        hasActiveCharacters: true,
        loading: false,
        error: null,
        accessUnavailable: false,
        copy: copyZhTw,
        onRetry: vi.fn(),
      }),
    )

    expect(htmlZhTw).not.toContain(missingSummaryCharId)
    expect(htmlZhTw).toContain('目前角色')
  })

  it('renders AI-equivalent Player projection fixture identically without UI bypass', () => {
    const aiPlayerQuest: RuntimeWorldEntryPlayerView = {
      ...validPlayerQuest,
      id: 'ai-quest-1',
      title: 'AI Player Discovered Quest',
    }
    const aiPlayerKnowledge: RuntimeWorldEntryPlayerView = {
      ...validCharacterKnowledge,
      id: 'ai-char-know-1',
      title: 'AI Player Secret Knowledge',
    }

    const aiSelection: PlayerJournalSelection = {
      publicEntries: [aiPlayerQuest],
      characterEntries: [aiPlayerKnowledge],
    }

    const html = renderToStaticMarkup(
      createElement(SessionPlayerJournalView, {
        selection: aiSelection,
        characterNames: ['AI Wizard'],
        hasActiveCharacters: true,
        loading: false,
        error: null,
        accessUnavailable: false,
        copy: copyEn,
        onRetry: vi.fn(),
      }),
    )

    expect(html).toContain('AI Player Discovered Quest')
    expect(html).toContain('AI Player Secret Knowledge')
    expect(html).toContain('AI Wizard')
    expect(html).not.toContain('dm_notes')
  })

  it('distinguishes empty public items state', () => {
    const selectionEmptyPublic: PlayerJournalSelection = {
      publicEntries: [],
      characterEntries: [validCharacterKnowledge],
    }

    const html = renderToStaticMarkup(
      createElement(SessionPlayerJournalView, {
        selection: selectionEmptyPublic,
        characterNames: ['Thorin'],
        hasActiveCharacters: true,
        loading: false,
        error: null,
        accessUnavailable: false,
        copy: copyEn,
        onRetry: vi.fn(),
      }),
    )

    expect(html).toContain(copyEn.journalEmptyPublic)
    expect(html).not.toContain(copyEn.journalEmptyCharacterKnowledge)
    expect(html).not.toContain(copyEn.journalNoActiveCharacter)
    expect(html).toContain('Secret Family Crest')
  })

  it('distinguishes no active character state (public only)', () => {
    const selectionPublicOnly: PlayerJournalSelection = {
      publicEntries: [validPlayerQuest],
      characterEntries: [],
    }

    const html = renderToStaticMarkup(
      createElement(SessionPlayerJournalView, {
        selection: selectionPublicOnly,
        characterNames: [],
        hasActiveCharacters: false,
        loading: false,
        error: null,
        accessUnavailable: false,
        copy: copyEn,
        onRetry: vi.fn(),
      }),
    )

    expect(html).toContain('Find the Sunken Key')
    expect(html).toContain(copyEn.journalNoActiveCharacter)
    expect(html).not.toContain(copyEn.journalEmptyCharacterKnowledge)
  })

  it('distinguishes active character(s) but no character knowledge state', () => {
    const selectionNoKnowledge: PlayerJournalSelection = {
      publicEntries: [validPlayerQuest],
      characterEntries: [],
    }

    const html = renderToStaticMarkup(
      createElement(SessionPlayerJournalView, {
        selection: selectionNoKnowledge,
        characterNames: ['Thorin Stonehelm'],
        hasActiveCharacters: true,
        loading: false,
        error: null,
        accessUnavailable: false,
        copy: copyEn,
        onRetry: vi.fn(),
      }),
    )

    expect(html).toContain('Find the Sunken Key')
    expect(html).toContain(copyEn.journalEmptyCharacterKnowledge)
    expect(html).toContain('Thorin Stonehelm')
    expect(html).not.toContain(copyEn.journalNoActiveCharacter)
  })

  it('omits absent title and body elements cleanly without raw null or ?', () => {
    const namelessQuest: RuntimeWorldEntryPlayerView = {
      id: 'quest-no-title',
      campaign_id: CAMPAIGN_ID,
      kind: 'quest',
      title: null,
      body: null,
      state: { kind: 'quest' },
      visibility: 'public',
      revision: 1,
      created_at: '2026-09-21T00:00:00Z',
      updated_at: '2026-09-21T00:00:00Z',
    }

    const html = renderToStaticMarkup(
      createElement(SessionPlayerJournalView, {
        selection: {
          publicEntries: [namelessQuest],
          characterEntries: [],
        },
        characterNames: [],
        hasActiveCharacters: false,
        loading: false,
        error: null,
        accessUnavailable: false,
        copy: copyEn,
        onRetry: vi.fn(),
      }),
    )

    expect(html).not.toContain('null')
    expect(html).not.toContain('?')
    expect(html).not.toContain('session-journal-entry__title')
    expect(html).not.toContain('session-journal-entry__body')
  })

  it('renders entry title inside session-journal-entry__header after the badge for public and character entries', () => {
    const html = renderToStaticMarkup(
      createElement(SessionPlayerJournalView, {
        selection: {
          publicEntries: [validPlayerQuest],
          characterEntries: [validCharacterKnowledge],
        },
        characterNames: ['Thorin Stonehelm'],
        hasActiveCharacters: true,
        loading: false,
        error: null,
        accessUnavailable: false,
        copy: copyEn,
        onRetry: vi.fn(),
      }),
    )

    expect(html).toMatch(
      /<div class="session-journal-entry__header"><span class="session-journal-badge session-journal-badge--quest">[^<]*<\/span><h4 class="session-journal-entry__title">Find the Sunken Key<\/h4><\/div>/,
    )
    expect(html).toMatch(
      /<div class="session-journal-entry__header"><span class="session-journal-badge session-journal-badge--secret">[^<]*<\/span><span class="session-journal-badge session-journal-badge--character">[^<]*<\/span><h4 class="session-journal-entry__title">Secret Family Crest<\/h4><\/div>/,
    )
  })

  it('renders error banner and retry button when error is present', () => {
    const onRetry = vi.fn()
    const html = renderToStaticMarkup(
      createElement(SessionPlayerJournalView, {
        selection: null,
        characterNames: [],
        hasActiveCharacters: false,
        loading: false,
        error: copyEn.journalLoadError,
        accessUnavailable: false,
        copy: copyEn,
        onRetry,
      }),
    )

    expect(html).toContain('error-banner')
    expect(html).toContain(copyEn.journalLoadError)
    expect(html).toContain(copyEn.retryButton)
  })

  it('renders loading state when initial load is pending', () => {
    const html = renderToStaticMarkup(
      createElement(SessionPlayerJournalView, {
        selection: null,
        characterNames: [],
        hasActiveCharacters: false,
        loading: true,
        error: null,
        accessUnavailable: false,
        copy: copyEn,
        onRetry: vi.fn(),
      }),
    )

    expect(html).toContain('session-journal-loading')
    expect(html).toContain(copyEn.loading)
  })

  it('is strictly read-only: no create, edit, archive, or reveal controls', () => {
    const html = renderToStaticMarkup(
      createElement(SessionPlayerJournalView, {
        selection: selectionBoth,
        characterNames: ['Thorin'],
        hasActiveCharacters: true,
        loading: false,
        error: null,
        accessUnavailable: false,
        copy: copyEn,
        onRetry: vi.fn(),
      }),
    )

    expect(html).not.toContain('create')
    expect(html).not.toContain('edit')
    expect(html).not.toContain('archive')
    expect(html).not.toContain('reveal')
    expect(html).not.toContain('<input')
    expect(html).not.toContain('<textarea')
    expect(html).not.toContain('<select')
    expect(html).not.toContain('<form')
  })
})
