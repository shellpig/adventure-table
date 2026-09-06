import { describe, expect, it } from 'vitest'

import type { CharacterSheetDTO } from '../../api/character'
import { createCharacterSheetHtmlExport } from './CharacterSheetHtmlExport'

const sheet = {
  name: 'Slot Capacity Wizard',
  version_no: 4,
  current_hp: 12,
  max_hp: 20,
  temporary_hp: 0,
  conditions: [],
  hit_dice: [],
  spell_slots: { '1': { used: 2, remaining: 2 } },
  resources: {},
  spellcasting: [],
  spells: [],
  inventory: [],
} as unknown as CharacterSheetDTO

function renderTab(tab: 'attributes' | 'spells' | 'inventory'): string {
  if (tab === 'attributes') {
    return `
      <main class="character-page">
        <section class="sheet-shell">
          <header class="character-hero">
            <div class="hero-stat"><span>HP</span><strong data-testid="header-hp">12</strong><small>/ 20</small></div>
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
            <article class="panel">
              <div class="panel-title"><h3>Spell Slots</h3><span>Server State</span></div>
              <div class="slot-grid">
                <div class="slot-card" data-sheet-index-key="1">
                  <span>Level 1</span><strong>2 / 4</strong><small>Remaining / Total</small>
                </div>
              </div>
            </article>
          </section>
          <footer class="sheet-footer"></footer>
        </section>
      </main>
    `
  }
  return '<main class="character-page"><section class="sheet-shell"><section class="sheet-content">Inventory</section><footer class="sheet-footer"></footer></section></main>'
}

describe('M01-N build-only spell slot wording', () => {
  it('describes transformed slot totals as capacity instead of server state', () => {
    const result = createCharacterSheetHtmlExport({
      sheet,
      scope: 'build',
      locale: 'en',
      renderTab,
    })
    const host = document.createElement('div')
    host.innerHTML = result.html

    const panel = host.querySelector('.slot-card')?.closest('article.panel')
    expect(panel?.querySelector('.panel-title span')?.textContent).toBe('Capacity')
    expect(panel?.querySelector('.slot-card strong')?.textContent).toBe('4')
    expect(panel?.querySelector('.slot-card small')?.textContent).toBe('Total')
    expect(result.html).not.toContain('Server State')
  })
})
