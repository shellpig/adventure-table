import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import type { CharacterSheetDTO } from '../../api/character'
import { characterSheetExportCopy } from '../../i18n/m01nCharacterSheetExportCopy'
import {
  assertSafeCharacterSheetHtml,
  buildCharacterSheetExportFilename,
  buildCharacterSheetHtmlDocument,
  createCharacterSheetHtmlExport,
  formatConditionForExport,
  pairCharacterSheetIndexRows,
  projectCharacterSheetForExport,
  sanitizeFilenameSegment,
} from './CharacterSheetHtmlExport'

const exportCssSource = readFileSync(new URL('./characterSheetExport.css', import.meta.url), 'utf8')
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
  resources: { 'feature:arcane-recovery': { used: 1, remaining: 0 } },
  spellcasting: [
    { source_key: 'srd5.1:class:wizard', prepared_limit: 5, prepared_count: 3 },
  ],
  spells: [
    { entry_id: 'wizard:shield', prepared: true },
    { entry_id: 'wizard:detect-magic', prepared: false },
    { entry_id: 'wizard:magic-missile', prepared: true },
  ],
  inventory: [{ entry_id: 'inventory:shield' }, { entry_id: 'inventory:potion' }],
} as unknown as CharacterSheetDTO

const preparedExportSheet = {
  name: 'Prepared Wizard',
  version_no: 2,
  current_hp: 18,
  max_hp: 24,
  temporary_hp: 0,
  conditions: [],
  hit_dice: [],
  spell_slots: {},
  resources: {},
  spellcasting: [
    { source_key: 'srd5.1:class:wizard', prepared_limit: 5, prepared_count: 3 },
  ],
  spells: [
    { entry_id: 'wizard:shield', prepared: true },
    { entry_id: 'wizard:detect-magic', prepared: false },
  ],
  inventory: [],
} as unknown as CharacterSheetDTO

function renderPreparedExportTab(tab: 'attributes' | 'spells' | 'inventory'): string {
  if (tab === 'attributes') {
    return `
      <main class="character-page">
        <section class="sheet-shell">
          <header class="character-hero">
            <div class="hero-stats">
              <div class="hero-stat"><span>HP</span><strong data-testid="header-hp">18</strong><small>/ 24</small></div>
            </div>
          </header>
          <section class="sheet-content">Attributes</section>
          <footer class="sheet-footer"><strong>Synced</strong></footer>
        </section>
      </main>
    `
  }
  if (tab === 'spells') {
    return `
      <main class="character-page">
        <section class="sheet-shell">
          <section class="sheet-content">
            <div class="spellcasting-grid">
              <article class="spellcasting-card">
                <div class="prepared-limit" data-sheet-index-key="srd5.1:class:wizard">
                  <small>Prepared</small><b>3 / 5</b>
                </div>
                <p class="prepared-limit-hint">Prepared limit reached: 5</p>
              </article>
            </div>
            <div class="spell-levels">
              <article class="spell-card is-prepared">
                <h3>Shield</h3>
                <span class="prepared-badge on">Prepared</span>
                <div class="prepared-control"><button type="button">Unprepare</button></div>
              </article>
              <article class="spell-card">
                <h3>Detect Magic</h3>
                <span class="prepared-badge">Unprepared</span>
              </article>
            </div>
          </section>
          <footer class="sheet-footer"><strong>Synced</strong></footer>
        </section>
      </main>
    `
  }
  return '<main class="character-page"><section class="sheet-shell"><section class="sheet-content">Inventory</section><footer class="sheet-footer"></footer></section></main>'
}

describe('M01-N Character Sheet export projection', () => {
  it('keeps current state in snapshot scope', () => {
    const value = projectCharacterSheetForExport(sheet, 'snapshot')
    expect(value.currentHp).toBe(21)
    expect(value.temporaryHp).toBe(6)
    expect(value.conditionCount).toBe(2)
    expect(value.hitDice[0]).toEqual({ die: 'd10', total: 3, available: 1 })
    expect(value.spellSlots[0]).toEqual({ level: '1', total: 4, remaining: 2 })
    expect(value.resources[0]).toEqual({ key: 'feature:arcane-recovery', total: 1, remaining: 0 })
    expect(value.preparedSpellEntryIds).toEqual(['wizard:shield', 'wizard:magic-missile'])
    expect(value.inventoryCount).toBe(2)
  })

  it('drops mutable state but retains capacities in build scope', () => {
    const value = projectCharacterSheetForExport(sheet, 'build')
    expect(value.currentHp).toBeNull()
    expect(value.temporaryHp).toBeNull()
    expect(value.conditionCount).toBe(0)
    expect(value.hitDice[0]).toEqual({ die: 'd10', total: 3, available: null })
    expect(value.spellSlots[0]).toEqual({ level: '1', total: 4, remaining: null })
    expect(value.resources[0]).toEqual({ key: 'feature:arcane-recovery', total: 1, remaining: null })
    expect(value.spellcasting[0]).toEqual({
      sourceKey: 'srd5.1:class:wizard',
      limit: 5,
      preparedCount: null,
    })
    expect(value.preparedSpellEntryIds).toBeNull()
    expect(value.inventoryCount).toBe(0)
  })

  it('preserves condition notes as static text', () => {
    expect(formatConditionForExport('Poisoned ×', ' From spider venom ')).toBe(
      'Poisoned — From spider venom',
    )
    expect(formatConditionForExport('Prone ×')).toBe('Prone')
  })
})

describe('M01-N keyed export row pairing', () => {
  it('pairs rows by stable key instead of DOM order', () => {
    const host = document.createElement('div')
    host.innerHTML = `
      <div class="row" data-sheet-index-key="second">second row</div>
      <div class="row" data-sheet-index-key="first">first row</div>
    `
    const items = [
      { key: 'first', value: 1 },
      { key: 'second', value: 2 },
    ]

    const pairs = pairCharacterSheetIndexRows(host, '.row', items, (item) => item.key)
    expect(pairs.map(({ key, item, row }) => [key, item.value, row.textContent?.trim()])).toEqual([
      ['second', 2, 'second row'],
      ['first', 1, 'first row'],
    ])
  })

  it('fails loudly for duplicate DOM keys', () => {
    const host = document.createElement('div')
    host.innerHTML = `
      <div class="row" data-sheet-index-key="same"></div>
      <div class="row" data-sheet-index-key="same"></div>
    `
    expect(() =>
      pairCharacterSheetIndexRows(host, '.row', [{ key: 'same' }], (item) => item.key),
    ).toThrow(/duplicate key: same/)
  })

  it('fails loudly for duplicate item keys and missing row keys', () => {
    const duplicateItemsHost = document.createElement('div')
    duplicateItemsHost.innerHTML = '<div class="row" data-sheet-index-key="same"></div>'
    expect(() =>
      pairCharacterSheetIndexRows(
        duplicateItemsHost,
        '.row',
        [{ key: 'same' }, { key: 'same' }],
        (item) => item.key,
      ),
    ).toThrow(/duplicate key: same/)

    const missingKeyHost = document.createElement('div')
    missingKeyHost.innerHTML = '<div class="row"></div>'
    expect(() =>
      pairCharacterSheetIndexRows(missingKeyHost, '.row', [{ key: 'only' }], (item) => item.key),
    ).toThrow(/missing data-sheet-index-key/)
  })
})

describe('M01-N build-only exporter integration', () => {
  it('keeps prepared capacity and full spell access without current prepared state', () => {
    const result = createCharacterSheetHtmlExport({
      sheet: preparedExportSheet,
      scope: 'build',
      locale: 'en',
      renderTab: renderPreparedExportTab,
    })
    const host = document.createElement('div')
    host.innerHTML = result.html

    const preparedLimit = host.querySelector('.prepared-limit')
    expect(preparedLimit?.querySelector('small')?.textContent).toBe('Prepared limit')
    expect(preparedLimit?.querySelector('b')?.textContent).toBe('5')
    expect(result.html).not.toContain('3 / 5')
    expect(host.querySelector('.prepared-limit-hint')).toBeNull()
    expect(host.querySelector('.prepared-badge')).toBeNull()
    expect(host.querySelector('.prepared-control')).toBeNull()
    expect(host.querySelector('.spell-card.is-prepared')).toBeNull()
    expect(result.html).toContain('Shield')
    expect(result.html).toContain('Detect Magic')
  })
})

describe('M01-N export identity and localization', () => {
  it('marks scope/version in a sanitized filename', () => {
    expect(buildCharacterSheetExportFilename(sheet, 'build')).toBe('Mira- Wizard-Scout--v7-build.html')
    expect(buildCharacterSheetExportFilename(sheet, 'snapshot')).toBe('Mira- Wizard-Scout--v7-snapshot.html')
    expect(sanitizeFilenameSegment('   ...   ')).toBe('character')
  })

  it('ships English and Traditional Chinese scope copy', () => {
    expect(characterSheetExportCopy('en')).toMatchObject({ buildScope: 'Build only', snapshotScope: 'Current snapshot' })
    expect(characterSheetExportCopy('zh-TW')).toMatchObject({ buildScope: '角色配置', snapshotScope: '當前快照' })
  })
})

describe('M01-N self-contained document', () => {
  it('owns its style block, freezes locale, and has no external dependency', () => {
    const html = buildCharacterSheetHtmlDocument({
      bodyMarkup: '<main class="character-page"><article>Offline</article></main>',
      locale: 'en',
      title: 'Mira — Build only',
    })
    expect(html).toContain('<html lang="en">')
    expect(html).toContain('<style>')
    expect(html).not.toMatch(/https?:\/\//i)
    expect(html).not.toMatch(/\bsrc\s*=/i)
    expect(html).not.toMatch(/\bhref\s*=/i)
  })

  it('ships A4 print rules that avoid splitting cards', () => {
    expect(exportCssSource).toContain('@media print')
    expect(exportCssSource).toContain('size: A4')
    expect(exportCssSource).toContain('break-inside: avoid')
  })

  it('escapes title text and rejects interactive/external markup', () => {
    const html = buildCharacterSheetHtmlDocument({
      bodyMarkup: '<main class="character-page">Safe body</main>',
      locale: 'zh-TW',
      title: '<Mira & Friends>',
    })
    expect(html).toContain('<title>&lt;Mira &amp; Friends&gt;</title>')
    expect(() => assertSafeCharacterSheetHtml('<button>Save</button>')).toThrow()
    expect(() => assertSafeCharacterSheetHtml('<details><summary>Roleplay</summary></details>')).toThrow()
    expect(() => assertSafeCharacterSheetHtml('<div>https://example.invalid</div>')).toThrow()
  })
})
