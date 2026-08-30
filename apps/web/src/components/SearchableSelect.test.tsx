import { describe, expect, it } from 'vitest'

import { duplicateOptionNames, optionDisplay } from './SearchableSelect'


describe('SearchableSelect source-aware labels', () => {
  it('keeps the display name primary and moves source metadata to secondary text', () => {
    expect(optionDisplay('Human · D&D 5e SRD 5.1')).toEqual({
      primary: 'Human',
      secondary: 'D&D 5e SRD 5.1',
    })
  })

  it('keeps same-name entries distinct by their secondary source label', () => {
    expect(optionDisplay('Goblin · Fixture Pack A')).toEqual({
      primary: 'Goblin',
      secondary: 'Fixture Pack A',
    })
    expect(optionDisplay('Goblin · Fixture Pack B')).toEqual({
      primary: 'Goblin',
      secondary: 'Fixture Pack B',
    })
  })

  it('preserves labels that do not carry secondary metadata', () => {
    expect(optionDisplay('Standard Array')).toEqual({
      primary: 'Standard Array',
      secondary: undefined,
    })
  })

  it('identifies only names that need source metadata for disambiguation', () => {
    expect(
      duplicateOptionNames([
        { value: 'srd-human', label: 'Human · SRD' },
        { value: 'phb-human', label: 'Human · PHB' },
        { value: 'elf', label: 'Elf · SRD' },
      ]),
    ).toEqual(new Set(['Human']))
  })
})
