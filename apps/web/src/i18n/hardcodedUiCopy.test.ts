import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

const SOURCE_FILES = [
  '../App.tsx',
  '../i18n/LocaleSwitcher.tsx',
  '../components/SearchableSelect.tsx',
  '../features/capabilities/CapabilityDisabledPage.tsx',
  '../features/capabilities/CapabilityLink.tsx',
  '../features/character-builder/BuilderDraftShell.tsx',
  '../features/character-builder/CharacterBuilderPage.tsx',
  '../features/character-builder/CharacterWorkshopPage.tsx',
  '../features/character-builder/CharacterVersionHistoryPage.tsx',
  '../features/character-builder/ClassProgressionStep.tsx',
  '../features/character-builder/EquipmentReviewStep.tsx',
  '../features/character-builder/RoleplayProfileEditor.tsx',
  '../features/character-builder/SpellcastingStep.tsx',
  '../features/character-io/ExportCharacterButton.tsx',
  '../features/character-io/ImportCharacterDialog.tsx',
  '../features/character-sheet/CharacterSheetPage.tsx',
] as const

const ALLOWED_LITERAL_TEXT = new Set([
  'Adventure Table',
  'AT',
  'EN',
  '繁中',
  'HP',
  'AC',
  'PB',
  'LV',
  'D&amp;D 5e · 2014',
  'D&D 5e · 2014',
])

function hardcodedPresentationCopy(relativePath: string): string[] {
  const url = new URL(relativePath, import.meta.url)
  const text = readFileSync(url, 'utf8')
  const source = ts.createSourceFile(url.pathname, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const offenders: string[] = []

  const visit = (node: ts.Node) => {
    if (ts.isJsxText(node)) {
      const value = node.getText(source).replace(/\s+/g, ' ').trim()
      if (
        value &&
        /[A-Za-z\u3400-\u9fff]{2,}/.test(value) &&
        !ALLOWED_LITERAL_TEXT.has(value)
      ) {
        offenders.push(`JSX text: ${value}`)
      }
    }

    if (
      ts.isJsxAttribute(node) &&
      ['aria-label', 'placeholder', 'title', 'label'].includes(node.name.getText(source)) &&
      node.initializer &&
      ts.isStringLiteral(node.initializer)
    ) {
      offenders.push(`${node.name.getText(source)}: ${node.initializer.text}`)
    }

    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      node.expression.name.text === 'confirm' &&
      node.arguments[0] &&
      ts.isStringLiteral(node.arguments[0])
    ) {
      offenders.push(`confirm: ${node.arguments[0].text}`)
    }

    ts.forEachChild(node, visit)
  }

  visit(source)
  return offenders
}

describe('M02-B hardcoded UI copy guard', () => {
  for (const sourceFile of SOURCE_FILES) {
    it(`${sourceFile} has no new hardcoded presentation prose`, () => {
      expect(hardcodedPresentationCopy(sourceFile)).toEqual([])
    })
  }
})
