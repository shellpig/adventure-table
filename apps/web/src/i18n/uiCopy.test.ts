import { describe, expect, it } from 'vitest'

import { UI_COPY, UI_COPY_SURFACES, translateUi } from './uiCopy'

describe('M02-B UI copy resources', () => {
  it('keeps a maintainable inventory for every required UI surface', () => {
    expect(UI_COPY_SURFACES).toEqual([
      'landing',
      'character-workshop',
      'builder-basic',
      'builder-origin',
      'builder-abilities',
      'builder-class',
      'builder-spellcasting',
      'builder-equipment',
      'builder-review',
      'character-sheet',
      'version-history',
      'shared-components',
    ])
  })

  it('keeps zh-TW and en keysets exactly identical', () => {
    expect(Object.keys(UI_COPY['zh-TW']).sort()).toEqual(Object.keys(UI_COPY.en).sort())
  })

  it('interpolates runtime values without changing resource keys', () => {
    expect(translateUi('en', 'workshop.characterCount', { count: 3 })).toBe('3 characters')
    expect(translateUi('zh-TW', 'workshop.characterCount', { count: 3 })).toBe('3 名角色')
    expect(translateUi('en', 'sheet.removeItem', { name: 'Shield' })).toBe('Remove Shield')
    expect(translateUi('zh-TW', 'sheet.removeItem', { name: '盾牌' })).toBe('移除 盾牌')
  })

  it('provides localized accessibility and empty-state copy in both locales', () => {
    expect(UI_COPY.en['shared.search.expand']).toContain('expand list')
    expect(UI_COPY['zh-TW']['shared.search.expand']).toContain('展開選單')
    expect(UI_COPY.en['sheet.tabsAria']).toBe('Character Sheet tabs')
    expect(UI_COPY['zh-TW']['sheet.tabsAria']).toBe('角色卡分頁')
    expect(UI_COPY.en['sheet.noInventory']).toContain('No items')
    expect(UI_COPY['zh-TW']['sheet.noInventory']).toContain('沒有符合搜尋條件')
  })
})
