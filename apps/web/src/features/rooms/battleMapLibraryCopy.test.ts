import { describe, expect, it } from 'vitest'

import { SessionApiError } from '../../api/sessions'
import {
  battleMapLibraryCopy,
  battleMapLibraryErrorMessage,
  monsterPlacementProblemMessage,
} from './battleMapLibraryCopy'

describe('battleMapLibraryCopy', () => {
  it('has identical keys for en and zh-TW', () => {
    const enCopy = battleMapLibraryCopy('en')
    const zhCopy = battleMapLibraryCopy('zh-TW')

    const enKeys = Object.keys(enCopy).sort()
    const zhKeys = Object.keys(zhCopy).sort()

    expect(enKeys).toEqual(zhKeys)
  })

  it('maps all B1 machine error codes correctly in en and zh-TW', () => {
    const enCopy = battleMapLibraryCopy('en')
    const zhCopy = battleMapLibraryCopy('zh-TW')

    const codes = [
      {
        code: 'battle_map_not_found',
        status: 404,
        expectedEn: enCopy.errBattleMapNotFound,
        expectedZh: zhCopy.errBattleMapNotFound,
      },
      {
        code: 'battle_map_revision_conflict',
        status: 409,
        expectedEn: enCopy.errBattleMapRevisionConflict,
        expectedZh: zhCopy.errBattleMapRevisionConflict,
      },
      {
        code: 'battle_map_referenced',
        status: 409,
        expectedEn: enCopy.errBattleMapReferenced,
        expectedZh: zhCopy.errBattleMapReferenced,
      },
      {
        code: 'battle_map_archived',
        status: 409,
        expectedEn: enCopy.errBattleMapArchived,
        expectedZh: zhCopy.errBattleMapArchived,
      },
      {
        code: 'battle_map_invalid',
        status: 400,
        expectedEn: enCopy.errBattleMapInvalid,
        expectedZh: zhCopy.errBattleMapInvalid,
      },
      {
        code: 'battle_map_asset_invalid',
        status: 400,
        expectedEn: enCopy.errBattleMapAssetInvalid,
        expectedZh: zhCopy.errBattleMapAssetInvalid,
      },
      {
        code: 'room_forbidden',
        status: 403,
        expectedEn: enCopy.requestFailed,
        expectedZh: zhCopy.requestFailed,
      },
    ]

    for (const { code, status, expectedEn, expectedZh } of codes) {
      const err = new SessionApiError(status, code, 'Failed')
      expect(battleMapLibraryErrorMessage(err, enCopy)).toBe(expectedEn)
      expect(battleMapLibraryErrorMessage(err, zhCopy)).toBe(expectedZh)
    }
  })

  it('returns fallback message for unknown error', () => {
    const enCopy = battleMapLibraryCopy('en')
    const err = new Error('Unknown error')
    expect(battleMapLibraryErrorMessage(err, enCopy)).toBe(enCopy.requestFailed)
  })

  it('maps M07-C placement machine error codes correctly in en and zh-TW', () => {
    const enCopy = battleMapLibraryCopy('en')
    const zhCopy = battleMapLibraryCopy('zh-TW')

    const codes = [
      {
        code: 'map_monster_placement_invalid',
        status: 409,
        expectedEn: enCopy.errMapMonsterPlacementInvalid,
        expectedZh: zhCopy.errMapMonsterPlacementInvalid,
      },
      {
        code: 'monster_placement_reference_not_found',
        status: 404,
        expectedEn: enCopy.errMonsterPlacementReferenceNotFound,
        expectedZh: zhCopy.errMonsterPlacementReferenceNotFound,
      },
      {
        code: 'monster_placement_invalid_source',
        status: 422,
        expectedEn: enCopy.errMonsterPlacementInvalidSource,
        expectedZh: zhCopy.errMonsterPlacementInvalidSource,
      },
    ]

    for (const { code, status, expectedEn, expectedZh } of codes) {
      const err = new SessionApiError(status, code, 'Failed')
      expect(battleMapLibraryErrorMessage(err, enCopy)).toBe(expectedEn)
      expect(battleMapLibraryErrorMessage(err, zhCopy)).toBe(expectedZh)
      expect(expectedEn.length).toBeGreaterThan(0)
      expect(expectedZh.length).toBeGreaterThan(0)
      expect(expectedEn).not.toBe(expectedZh)
    }
  })

  it('explains every placement problem code in en and zh-TW', () => {
    const enCopy = battleMapLibraryCopy('en')
    const zhCopy = battleMapLibraryCopy('zh-TW')

    const codes = [
      'out_of_bounds',
      'blocked_terrain',
      'wall_or_door_blocked',
      'overlapping_placement',
      'template_archived',
      'invalid_size',
    ]
    for (const code of codes) {
      const en = monsterPlacementProblemMessage(code, enCopy)
      const zh = monsterPlacementProblemMessage(code, zhCopy)
      expect(en.length).toBeGreaterThan(0)
      expect(zh.length).toBeGreaterThan(0)
      expect(en).not.toBe(code)
      expect(zh).not.toBe(code)
      expect(en).not.toBe(zh)
    }
    // Unknown future codes stay visible instead of vanishing.
    expect(monsterPlacementProblemMessage('future_code', enCopy)).toBe('future_code')
  })
})
