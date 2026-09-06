import { describe, expect, it } from 'vitest'

import type { CharacterSheetDTO } from '../../api/character'
import { characterSheetExportCopy } from '../../i18n/m01nCharacterSheetExportCopy'
import {
  assertSafeCharacterSheetHtml,
  buildCharacterSheetExportFilename,
  buildCharacterSheetHtmlDocument,
  formatConditionForExport,
  projectCharacterSheetForExport,
  sanitizeFilenameSegment,
} from './CharacterSheetHtmlExport'

const sheet = {
  name: 'Mira: Wizard/Scout?',
  version_no: 7,
  current_hp: 21,
  max_hp: 38,
  temporary_hp: 6,
  conditions: [
    { condition_ref: 'srd5.1:condition:poisoned', name: 'Poisoned', note: 'From spider venom' },
    { condition_ref: 'srd5.1:condition:prone', name: 'Prone' },
  ],
  hit_dice: [
    { die: 'd10', total: 3, available: 1 },
    { die: 'd6', total: 4, available: 2 },
  ],
  spell_slots: {
    '1': { used: 2, remaining: 2 },
    '2': { used: 1, remaining: 2 },
  },
  resources: {
    'feature:arcane-recovery': { used: 1, remaining: 0 },
  },
  spellcasting: [
    {
      source_key: 'srd5.1:class:wizard',
      prepared_limit: 5,
      prepared_count: 3,
    },
  ],
  spells: [
    { entry_id: 'wizard:shield', prepared: true },
    { entry_id: 'wizard:detect-magic', prepared: false },
    { entry_id: 'wizard:magic-missile', prepared: true },
  ],
  inventory: [
    { entry_id: 'inventory:shield' },
    { entry_id: 'inventory:potion' },
  ],
} as CharacterSheetDTO

describe('M01-N Character Sheet export projection', () => {
  it('keeps current HP, temporary HP and conditions in a current snapshot', () => {
    const projection = projectCharacterSheetForExport(sheet, 'snapshot')
    expect(projection.currentHp).toBe(21)
    expect(projection.temporaryHp).toBe(6)
    expect(projection.conditionCount).toBe(2)
  })

  it('keeps current hit dice, slot/resource remainders, prepared state and inventory in a snapshot', () => {
    const projection = projectCharacterSheetForExport(sheet, 'snapshot')
    expect(projection.hitDice).toEqual([
      { die: 'd10', total: 3, available: 1 },
      { die: 'd6', total: 4, available: 2 },
    ])
    expect(projection.spellSlots[0]).toEqual({ level: '1', total: 4, remaining: 2 })
    expect(projection.resources[0]).toEqual({ key: 'feature:arcane-recovery', total: 1, remaining: 0 })
    expect(projection.preparedSpellEntryIds).toEqual(['wizard:shield', 'wizard:magic-missile'])
    expect(projection.inventoryCount).toBe(2)
  })

  it('removes all Current State fields from the build-only projection', () => {
    const projection = projectCharacterSheetForExport(sheet, 'build')
    expect(projection.currentHp).toBeNull()
    expect(projection.temporaryHp).toBeNull()
    expect(projection.conditionCount).toBe(0)
    expect(projection.preparedSpellEntryIds).toBeNull()
    expect(projection.inventoryCount).toBe(0)
  })

  it('retains hit-die totals, slot totals and resource capacity for build-only output', () => {
    const projection = projectCharacterSheetForExport(sheet, 'build')
    expect(projection.hitDice).toEqual([
      { die: 'd10', total: 3, available: null },
      { die: 'd6', total: 4, available: null },
    ])
    expect(projection.spellSlots).toEqual([
      { level: '1', total: 4, remaining: null },
      { level: '2', total: 3, remaining: null },
    ])
    expect(projection.resources[0]).toEqual({ key: 'feature:arcane-recovery', total: 1, remaining: null })
  })

  it('retains a prepared-spell limit without leaking the current prepared count in build-only output', () => {
    const projection = projectCharacterSheetForExport(sheet, 'build')
    expect(projection.spellcasting[0]).toEqual({
      sourceKey: 'srd5.1:class:wizard',
      limit: 5,
      preparedCount: null,
    })
  })

  it('preserves visible condition notes as static text instead of hover-only state', () => {
    expect(formatConditionForExport('Poisoned ×', '  From spider venom  ')).toBe(
      'Poisoned — From spider venom',
    )
    expect(formatConditionForExport('Prone ×')).toBe('Prone')
  })
})

describe('M01-N Character Sheet export identity', () => {
  it('marks scope and build version in the filename and sanitizes filesystem-hostile characters', () => {
    expect(buildCharacterSheetExportFilename(sheet, 'build')).toBe('Mira- Wizard-Scout--v7-build.html')
    expect(buildCharacterSheetExportFilename(sheet, 'snapshot')).toBe('Mira- Wizard-Scout--v7-snapshot.html')
  })

  it('falls back to a stable filename segment when a name becomes empty after sanitization', () => {
    expect(sanitizeFilenameSegment('   ...   ')).toBe('character')
  })

  it('ships the new export copy in both supported locales', () => {
    expect(characterSheetExportCopy('en')).toMatchObject({
      button: 'Export HTML',
      buildScope: 'Build only',
      snapshotScope: 'Current snapshot',
    })
    expect(characterSheetExportCopy('zh-TW')).toMatchObject({
      button: '匯出 HTML',
      buildScope: '角色配置',
      snapshotScope: '當前快照',
    })
  })
})

describe('M01-N self-contained HTML document', () => {
  it('inlines styles, contains the print block, freezes locale, and emits no external dependency', () => {
    const html = buildCharacterSheetHtmlDocument({
      bodyMarkup: '<main class="character-page"><article>Offline</article></main>',
      locale: 'en',
      title: 'Mira — Build only',
    })
    expect(html).toContain('<html lang="en">')
    expect(html).toContain('<style>')
    expect(html).toContain('@media print')
    expect(html).not.toMatch(/<script\b/i)
    expect(html).not.toMatch(/https?:\/\//i)
    expect(html).not.toMatch(/\bsrc\s*=/i)
    expect(html).not.toMatch(/\bhref\s*=/i)
  })

  it('escapes document-title text instead of creating markup', () => {
    const html = buildCharacterSheetHtmlDocument({
      bodyMarkup: '<main class="character-page">Safe body</main>',
      locale: 'zh-TW',
      title: '<Mira & Friends>',
    })
    expect(html).toContain('<title>&lt;Mira &amp; Friends&gt;</title>')
  })

  it.each([
    ['script', '<script>alert(1)</script>'],
    ['external URL', '<div>https://example.invalid</div>'],
    ['src attribute', '<img src="x">'],
    ['href attribute', '<a href="/x">x</a>'],
    ['button control', '<button>Save</button>'],
    ['input control', '<input value="x">'],
    ['collapsible details', '<details open><summary>Roleplay</summary></details>'],
    ['tab navigation', '<div role="tablist">tabs</div>'],
  ])('rejects %s from the final export', (_label, unsafe) => {
    expect(() => assertSafeCharacterSheetHtml(unsafe)).toThrow()
  })
})
