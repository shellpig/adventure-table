import { describe, expect, it } from 'vitest'

import { translateUi } from './uiCopy'

describe('M01-E movement UI copy', () => {
  it('comes from the typed UI-copy SSOT in both supported locales', () => {
    expect(translateUi('en', 'sheet.movement')).toBe('Movement')
    expect(translateUi('en', 'sheet.movement.walk')).toBe('Walk')
    expect(translateUi('en', 'sheet.distanceFeet', { value: 35 })).toBe('35 ft')

    expect(translateUi('zh-TW', 'sheet.movement')).toBe('移動')
    expect(translateUi('zh-TW', 'sheet.movement.swim')).toBe('游泳')
    expect(translateUi('zh-TW', 'sheet.distanceFeet', { value: 30 })).toBe('30 尺')
  })
})
