import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { LocaleProvider } from '../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type Locale, type LocaleStorage } from '../i18n/locale'
import {
  duplicateOptionNames,
  optionDisplay,
  rankSearchOptions,
  SearchableSelect,
  sortSearchOptions,
} from './SearchableSelect'

function localeStorage(locale: Locale): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? locale : null),
    setItem: () => undefined,
  }
}


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

  it('ranks localized-name matches first while retaining every unmatched option', () => {
    const options = [
      { value: 'elf', label: 'Elf' },
      { value: 'variant-human', label: 'Variant Human' },
      { value: 'dwarf', label: 'Dwarf' },
      { value: 'human', label: 'Human' },
    ]

    expect(rankSearchOptions(options, 'human', 'en').map(({ option, matches }) => [option.value, matches])).toEqual([
      ['human', true],
      ['variant-human', true],
      ['dwarf', false],
      ['elf', false],
    ])
  })

  it('matches another supported locale through a hidden alias without changing display text', () => {
    const options = [
      { value: 'srd5.1:spell:fireball', label: '火球術', searchAliases: ['Fireball'] },
      { value: 'srd5.1:spell:light', label: '光亮術', searchAliases: ['Light'] },
    ]

    const ranked = rankSearchOptions(options, 'fireball', 'zh-TW')
    expect(ranked[0]).toEqual({ option: options[0], matches: true })
    expect(ranked[0].option.label).toBe('火球術')
    expect(ranked[0].option.label).not.toContain('Fireball')
  })

  it('sorts by the current locale display label rather than StableKey/input order', () => {
    const options = [
      { value: 'srd5.1:spell:z', label: '乙術' },
      { value: 'srd5.1:spell:a', label: '甲術' },
      { value: 'srd5.1:spell:b', label: '丙術' },
    ]

    expect(sortSearchOptions(options, 'zh-TW').map((option) => option.label)).toEqual([
      '丙術',
      '甲術',
      '乙術',
    ].sort((left, right) => new Intl.Collator('zh-TW', { sensitivity: 'base', numeric: true }).compare(left, right)))
  })

  it('preserves configured order for numeric selectors such as Standard Array', () => {
    const options = [
      { value: '15', label: '15' },
      { value: '14', label: '14' },
      { value: '13', label: '13' },
      { value: '12', label: '12' },
      { value: '10', label: '10' },
      { value: '8', label: '8' },
    ]

    expect(sortSearchOptions(options, 'zh-TW')).toEqual(options)
  })
})

describe('SearchableSelect clearable', () => {
  const options = [
    { value: 'tce:feature:favored-foe', label: 'Favored Foe' },
  ]

  function markup(props: { value: string; clearable?: boolean }) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <LocaleProvider storage={localeStorage('zh-TW')} documentTarget={null}>
          <SearchableSelect label="Optional feature" options={options} onChange={() => undefined} {...props} />
        </LocaleProvider>
      </QueryClientProvider>,
    )
  }

  it('renders a clear button only when clearable and a value is selected', () => {
    expect(markup({ value: 'tce:feature:favored-foe', clearable: true })).toContain('combobox-clear')
    expect(markup({ value: '', clearable: true })).not.toContain('combobox-clear')
    expect(markup({ value: 'tce:feature:favored-foe' })).not.toContain('combobox-clear')
  })

  it('labels the clear button in the active locale', () => {
    expect(markup({ value: 'tce:feature:favored-foe', clearable: true })).toContain(
      'aria-label="Optional feature：清除選擇"',
    )
  })
})
