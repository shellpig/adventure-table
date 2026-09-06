import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { characterSheetExportCopy } from '../../i18n/m01nCharacterSheetExportCopy'

const exporterSource = readFileSync(new URL('./CharacterSheetHtmlExport.ts', import.meta.url), 'utf8')

describe('M01-N build-only spell slot wording', () => {
  it('describes transformed slot totals as capacity instead of server state', () => {
    expect(characterSheetExportCopy('en').capacity).toBe('Capacity')
    expect(exporterSource).toContain('if (value) value.textContent = String(entry.total)')
    expect(exporterSource).toContain('if (caption) caption.textContent = copy.total')
    expect(exporterSource).toContain('const spellSlotSubtitle = slotPairs[0]?.row')
    expect(exporterSource).toContain('if (spellSlotSubtitle) spellSlotSubtitle.textContent = copy.capacity')
  })
})
