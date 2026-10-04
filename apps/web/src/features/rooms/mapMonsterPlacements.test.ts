import { describe, expect, it } from 'vitest'

import type { BattleMapMonsterPlacement } from '../../api/battleMaps'
import { SessionApiError } from '../../api/sessions'
import type { MonsterLibrarySummaryView } from '../../api/monsterLibrary'
import {
  addMonsterPlacement,
  availableMonsterTemplates,
  buildMonsterPlacementsBody,
  extractPlacementProblems,
  footprintForSizeName,
  monsterPlacementsFromMap,
  moveMonsterPlacement,
  placementSourceForRef,
  removeMonsterPlacement,
  resolvePlacementTemplate,
  templateRefForPlacement,
  toMonsterPlacementsPayload,
  toggleMonsterPlacementVisibility,
} from './mapMonsterPlacements'

const SAVED_ID = '20000000-0000-4000-8000-000000000001'
const CUSTOM_ID = '30000000-0000-4000-8000-000000000001'

function savedPlacement(
  overrides?: Partial<BattleMapMonsterPlacement>,
): BattleMapMonsterPlacement {
  return {
    id: SAVED_ID,
    template_key: 'srd5.1:monster:goblin',
    custom_template_id: null,
    anchor_x: 2,
    anchor_y: 3,
    visibility: 'public',
    sort_order: 0,
    ...overrides,
  }
}

function summary(
  overrides?: Partial<MonsterLibrarySummaryView>,
): MonsterLibrarySummaryView {
  return {
    ref: 'srd5.1:monster:goblin',
    name: 'Goblin',
    names: { en: 'Goblin', 'zh-TW': '地精' },
    name_is_custom: false,
    source_kind: 'builtin',
    source_key: 'srd5.1:monster:goblin',
    size: 'Small',
    archived_at: null,
    revision: null,
    ...overrides,
  }
}

describe('map monster placement refs', () => {
  it('maps a custom template id to a custom: ref and back', () => {
    const ref = templateRefForPlacement({
      template_key: null,
      custom_template_id: CUSTOM_ID,
    })
    expect(ref).toBe(`custom:${CUSTOM_ID}`)
    expect(placementSourceForRef(ref)).toEqual({
      template_key: null,
      custom_template_id: CUSTOM_ID,
    })
  })

  it('maps a builtin content key to a template_key source', () => {
    expect(
      templateRefForPlacement({
        template_key: 'srd5.1:monster:goblin',
        custom_template_id: null,
      }),
    ).toBe('srd5.1:monster:goblin')
    expect(placementSourceForRef('srd5.1:monster:goblin')).toEqual({
      template_key: 'srd5.1:monster:goblin',
      custom_template_id: null,
    })
  })
})

describe('monster placement working state', () => {
  it('loads saved placements ordered by sort_order', () => {
    const working = monsterPlacementsFromMap([
      savedPlacement({ id: 'b', sort_order: 2, anchor_x: 9 }),
      savedPlacement({ id: 'a', sort_order: 0, anchor_x: 1 }),
    ])
    expect(working.map((p) => p.clientId)).toEqual(['a', 'b'])
    expect(working[0]).toMatchObject({
      templateRef: 'srd5.1:monster:goblin',
      anchor_x: 1,
      anchor_y: 3,
      visibility: 'public',
    })
  })

  it('moves, toggles visibility, and removes by client id', () => {
    let working = monsterPlacementsFromMap([savedPlacement()])
    working = moveMonsterPlacement(working, SAVED_ID, 5, 6)
    expect(working[0]).toMatchObject({ anchor_x: 5, anchor_y: 6 })
    working = toggleMonsterPlacementVisibility(working, SAVED_ID)
    expect(working[0].visibility).toBe('hidden')
    working = toggleMonsterPlacementVisibility(working, SAVED_ID)
    expect(working[0].visibility).toBe('public')
    working = removeMonsterPlacement(working, SAVED_ID)
    expect(working).toHaveLength(0)
  })

  it('appends a new placement entry', () => {
    const working = addMonsterPlacement([], {
      clientId: 'new-uuid',
      templateRef: 'srd5.1:monster:ogre',
      anchor_x: 1,
      anchor_y: 1,
      visibility: 'hidden',
    })
    expect(working).toHaveLength(1)
    expect(working[0]).toMatchObject({ visibility: 'hidden' })
  })
})

describe('monster placements PUT payload', () => {
  it('sends expected_revision with the full placement set, hidden flag intact', () => {
    const body = buildMonsterPlacementsBody(7, [
      {
        clientId: SAVED_ID,
        templateRef: 'srd5.1:monster:goblin',
        anchor_x: 2,
        anchor_y: 3,
        visibility: 'hidden',
      },
      {
        clientId: '40000000-0000-4000-8000-000000000001',
        templateRef: `custom:${CUSTOM_ID}`,
        anchor_x: 4,
        anchor_y: 4,
        visibility: 'public',
      },
    ])
    expect(body).toEqual({
      expected_revision: 7,
      placements: [
        {
          id: SAVED_ID,
          template_key: 'srd5.1:monster:goblin',
          custom_template_id: null,
          anchor_x: 2,
          anchor_y: 3,
          visibility: 'hidden',
          sort_order: 0,
        },
        {
          id: '40000000-0000-4000-8000-000000000001',
          template_key: null,
          custom_template_id: CUSTOM_ID,
          anchor_x: 4,
          anchor_y: 4,
          visibility: 'public',
          sort_order: 1,
        },
      ],
    })
  })

  it('strips non-UUID editor ids to null and keeps server UUIDs', () => {
    const sent = toMonsterPlacementsPayload([
      { clientId: SAVED_ID, templateRef: 'k', anchor_x: 0, anchor_y: 0, visibility: 'public' },
      { clientId: 'placement-local-1', templateRef: 'k', anchor_x: 1, anchor_y: 1, visibility: 'public' },
    ])
    expect(sent.map((p) => p.id)).toEqual([SAVED_ID, null])
  })

  it('an empty working set sends an empty placements array, never undefined', () => {
    expect(buildMonsterPlacementsBody(3, [])).toEqual({
      expected_revision: 3,
      placements: [],
    })
  })
})

describe('monster footprint preview', () => {
  it('maps sizes to footprints, case-insensitively', () => {
    expect(footprintForSizeName('Tiny')).toEqual({ width: 1, height: 1 })
    expect(footprintForSizeName('small')).toEqual({ width: 1, height: 1 })
    expect(footprintForSizeName('MEDIUM')).toEqual({ width: 1, height: 1 })
    expect(footprintForSizeName('Large')).toEqual({ width: 2, height: 2 })
    expect(footprintForSizeName('Huge')).toEqual({ width: 3, height: 3 })
    expect(footprintForSizeName('Gargantuan')).toEqual({ width: 4, height: 4 })
  })

  it('falls back to 1x1 for missing or unreadable sizes (server reports invalid_size on save)', () => {
    expect(footprintForSizeName(null)).toEqual({ width: 1, height: 1 })
    expect(footprintForSizeName('')).toEqual({ width: 1, height: 1 })
    expect(footprintForSizeName('Colossal')).toEqual({ width: 1, height: 1 })
  })
})

describe('monster template availability', () => {
  it('offers only unarchived templates in the add picker', () => {
    const list = [
      summary(),
      summary({ ref: 'custom:archived', archived_at: '2026-10-04T00:00:00Z' }),
    ]
    expect(availableMonsterTemplates(list).map((s) => s.ref)).toEqual([
      'srd5.1:monster:goblin',
    ])
  })

  it('still resolves an archived ref for an already-saved placement', () => {
    const archived = summary({ ref: `custom:${CUSTOM_ID}`, archived_at: '2026-10-04T00:00:00Z' })
    expect(availableMonsterTemplates([archived])).toHaveLength(0)
    // Resolution for display/move/remove uses the full loaded list, which the
    // editor fetches with include_archived: true.
    expect(resolvePlacementTemplate(`custom:${CUSTOM_ID}`, [archived])?.ref).toBe(
      `custom:${CUSTOM_ID}`,
    )
    expect(resolvePlacementTemplate('missing-ref', [archived])).toBeUndefined()
  })
})

describe('placement problem extraction', () => {
  it('returns problems only for map_monster_placement_invalid with a problems array', () => {
    const problems = [
      { placement_id: SAVED_ID, code: 'overlapping_placement' },
      { placement_id: 'other', code: 'out_of_bounds' },
    ]
    const err = new SessionApiError(409, 'map_monster_placement_invalid', 'invalid', {
      problems,
    })
    expect(extractPlacementProblems(err)).toEqual(problems)
  })

  it('returns [] for other codes, missing params, malformed entries, and non-API errors', () => {
    expect(
      extractPlacementProblems(new SessionApiError(409, 'battle_map_revision_conflict', 'stale')),
    ).toEqual([])
    expect(
      extractPlacementProblems(new SessionApiError(409, 'map_monster_placement_invalid', 'x')),
    ).toEqual([])
    expect(
      extractPlacementProblems(
        new SessionApiError(409, 'map_monster_placement_invalid', 'x', {
          problems: [{ placement_id: 123, code: null }] as unknown as Array<{
            placement_id: string
            code: string
          }>,
        }),
      ),
    ).toEqual([])
    expect(extractPlacementProblems(new Error('boom'))).toEqual([])
  })
})
