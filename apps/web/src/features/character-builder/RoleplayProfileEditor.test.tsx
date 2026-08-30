import { describe, expect, it } from 'vitest'

import {
  appendRoleplaySuggestion,
  localizedRoleplayLines,
  parseRoleplayText,
  roleplayLines,
  roleplaySuggestionRefs,
} from './RoleplayProfileEditor'


describe('M01-B / M02-C RoleplayProfileEditor helpers', () => {
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

  it('keeps system suggestion identity separate from locale-specific display text', () => {
    const refs = roleplaySuggestionRefs({
      personality_traits: [
        { suggestion_id: 'phb2014:background:acolyte:roleplay:personality_traits:01', position: 1 },
      ],
    })
    const lines = localizedRoleplayLines(
      ['My own trait.', 'English system text.'],
      refs.personality_traits,
      {
        'phb2014:background:acolyte:roleplay:personality_traits:01': '繁體中文系統建議。',
      },
    )

    expect(lines).toEqual(['My own trait.', '繁體中文系統建議。'])
    expect(refs.personality_traits?.[0].position).toBe(1)
  })

  it('ignores malformed persisted system suggestion refs instead of guessing', () => {
    expect(
      roleplaySuggestionRefs({
        ideals: [
          { suggestion_id: '', position: 0 },
          { suggestion_id: 'valid-id', position: -1 },
          { suggestion_id: 'valid-id', position: 2 },
        ],
      }).ideals,
    ).toEqual([{ suggestion_id: 'valid-id', position: 2 }])
  })
})
