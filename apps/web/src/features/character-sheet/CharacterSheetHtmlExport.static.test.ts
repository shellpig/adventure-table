import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const exporterSource = readFileSync(
  new URL('./CharacterSheetHtmlExport.ts', import.meta.url),
  'utf8',
)
const actionSource = readFileSync(
  new URL('./CharacterSheetHtmlExportButton.tsx', import.meta.url),
  'utf8',
)
const viewSource = readFileSync(
  new URL('./CharacterSheetView.tsx', import.meta.url),
  'utf8',
)
const importDialogSource = readFileSync(
  new URL('../character-io/ImportCharacterDialog.tsx', import.meta.url),
  'utf8',
)

describe('M01-N static boundaries', () => {
  it('keeps react-dom/server out of Character Sheet export runtime code', () => {
    for (const source of [exporterSource, actionSource, viewSource]) {
      expect(source).not.toContain('react-dom/server')
    }
    expect(actionSource).toContain("await import('./CharacterSheetView')")
    expect(actionSource).not.toContain("await import('./CharacterSheetPage')")
  })

  it('keeps the export renderer separated from page API reads', () => {
    expect(viewSource).not.toContain('getCharacterSheet')
    expect(viewSource).not.toContain('listContent')
    expect(viewSource).not.toContain('patchCharacterState')
    expect(viewSource).not.toMatch(/\bfetch\s*\(/)
  })

  it('reuses already-held sheet and presentation data without adding an export-only read', () => {
    expect(actionSource).toContain('queryClient.getQueryData<CharacterSheetDTO>')
    expect(actionSource).toContain('createFrozenExportQueryClient(queryClient)')
    expect(actionSource).toContain('staleTime: Infinity')
    expect(actionSource).not.toContain('getCharacterSheet(')
    expect(actionSource).not.toContain('listContent(')
    expect(actionSource).not.toMatch(/\bfetch\s*\(/)
  })

  it('keeps HTML one-way by leaving Character import JSON-only', () => {
    expect(importDialogSource).toContain('accept="application/json,.json"')
    expect(importDialogSource).not.toContain('text/html')
    expect(importDialogSource).not.toContain('.html')
  })

  it('keeps the exporter client-only and type-only at the Character API boundary', () => {
    expect(exporterSource).toContain("import type { CharacterSheetDTO } from '../../api/character'")
    expect(exporterSource).not.toContain('getCharacterSheet')
    expect(exporterSource).not.toContain('patchCharacterState')
  })
})
