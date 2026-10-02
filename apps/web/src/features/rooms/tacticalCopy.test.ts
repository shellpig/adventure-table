import { describe, expect, it } from 'vitest'

import { sessionCopy } from './sessionCopy'

const tacticalKeys = [
  'tacticalMapEditorTitle',
  'tacticalMapListHeading',
  'tacticalMapCreate',
  'tacticalMapName',
  'tacticalMapWidth',
  'tacticalMapHeight',
  'tacticalMapSave',
  'tacticalMapSaving',
  'tacticalMapSaved',
  'tacticalMapOpenEditor',
  'tacticalToolSelect',
  'tacticalToolWall',
  'tacticalToolDoor',
  'tacticalToolTerrain',
  'tacticalToolToken',
  'tacticalToolDraw',
  'tacticalToolErase',
  'tacticalToolUndo',
  'tacticalToolFitMap',
  'tacticalHiddenToggle',
  'tacticalStartButton',
  'tacticalStarting',
  'tacticalSelectMap',
  'tacticalMapListEmpty',
  'tacticalStartBlank',
  'tacticalPlacementHeading',
  'tacticalPlaceToken',
  'tacticalPlacing',
  'tacticalStageTitle',
  'tacticalBoardLoading',
  'tacticalBoardLoadFailed',
  'tacticalHiddenWall',
  'tacticalHiddenDoor',
  'tacticalCenterParty',
  'tacticalZoomIn',
  'tacticalZoomOut',
  'tacticalTokenHint',
  'tacticalTerrainDifficult',
  'tacticalTerrainNormal',
  'tacticalTerrainBlocked',
  'tacticalDrawColor',
  'tacticalDrawWidth',
  'tacticalDrawColorWhite',
  'tacticalDrawColorBlack',
  'tacticalDrawColorRed',
  'tacticalDrawColorOrange',
  'tacticalDrawColorYellow',
  'tacticalDrawColorGreen',
  'tacticalDrawColorBlue',
  'tacticalDrawColorPurple',
  'tacticalMapResize',
] as const

describe('P5-F F2 tactical copy parity', () => {
  it('has all tactical keys in zh-TW and en with non-empty values', () => {
    for (const locale of ['zh-TW', 'en'] as const) {
      const copy = sessionCopy(locale)
      for (const key of tacticalKeys) {
        const value = (copy as Record<string, unknown>)[key]
        expect(typeof value, `${locale}.${key}`).toBe('string')
        expect((value as string).length, `${locale}.${key}`).toBeGreaterThan(0)
      }
    }
  })

  it('zh-TW and en values differ (not untranslated)', () => {
    const zh = sessionCopy('zh-TW')
    const en = sessionCopy('en')
    for (const key of tacticalKeys) {
      const zhVal = (zh as Record<string, string>)[key]
      const enVal = (en as Record<string, string>)[key]
      // Allow identical only for single-word tool names that are proper nouns.
      if (key === 'tacticalToolToken') continue
      expect(zhVal, key).not.toBe(enVal)
    }
  })
})
