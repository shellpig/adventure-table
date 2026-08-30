import { describe, expect, it } from 'vitest'

import {
  appendRoleplaySuggestion,
  parseRoleplayText,
  roleplayLines,
} from './RoleplayProfileEditor'


describe('M01-B RoleplayProfileEditor helpers', () => {
  it('normalizes optional saved roleplay values without inventing entries', () => {
    expect(roleplayLines(undefined)).toEqual([])
    expect(roleplayLines(['  Patient listener.  ', '', 42, 'Keeps promises.'])).toEqual([
      'Patient listener.',
      'Keeps promises.',
    ])
  })

  it('turns manual multiline text into saved roleplay entries', () => {
    expect(parseRoleplayText('  My own trait.\n\nAnother note.  ')).toEqual([
      'My own trait.',
      'Another note.',
    ])
  })

  it('adds a background suggestion once while preserving manual entries', () => {
    const first = appendRoleplaySuggestion('My own trait.', 'Always polite and respectful.')
    expect(first).toEqual(['My own trait.', 'Always polite and respectful.'])

    const duplicate = appendRoleplaySuggestion(first.join('\n'), 'Always polite and respectful.')
    expect(duplicate).toEqual(first)
  })
})
