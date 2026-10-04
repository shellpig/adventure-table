import { describe, expect, it } from 'vitest'

import { SessionApiError } from '../../api/sessions'
import {
  battleMapLibraryCopy,
  battleMapLibraryErrorMessage,
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
})
