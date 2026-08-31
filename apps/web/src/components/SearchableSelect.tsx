import { useEffect, useId, useMemo, useState } from 'react'

import { useContentPresentations } from '../i18n/useContentPresentations'
import { useUiCopy } from '../i18n/useUiCopy'

export type SearchOption = {
  value: string
  label: string
  description?: string
  disabled?: boolean
  disabledReason?: string
  searchAliases?: string[]
}

type SearchableSelectProps = {
  label: string
  options: SearchOption[]
  value: string
  onChange: (value: string) => void
  placeholder?: string
  disabled?: boolean
  secondaryMode?: 'always' | 'duplicates'
}

type OptionDisplay = {
  primary: string
  secondary?: string
}

const STABLE_KEY_RE = /^[^:]+:[^:]+:[^:]+$/

export function optionDisplay(label: string): OptionDisplay {
  const [primary, ...secondaryParts] = label.split(' · ')
  const secondary = secondaryParts.join(' · ').trim()
  return {
    primary: primary.trim(),
    secondary: secondary || undefined,
  }
}

export function duplicateOptionNames(options: SearchOption[]): Set<string> {
  const counts = new Map<string, number>()
  for (const option of options) {
    const primary = optionDisplay(option.label).primary
    counts.set(primary, (counts.get(primary) ?? 0) + 1)
  }
  return new Set(
    [...counts.entries()]
      .filter(([, count]) => count > 1)
      .map(([primary]) => primary),
  )
}

export function sortSearchOptions(options: SearchOption[], locale: string): SearchOption[] {
  const collator = new Intl.Collator(locale, { sensitivity: 'base', numeric: true })
  return [...options].sort((left, right) => {
    const byName = collator.compare(optionDisplay(left.label).primary, optionDisplay(right.label).primary)
    return byName || left.value.localeCompare(right.value)
  })
}

export function rankSearchOptions(options: SearchOption[], query: string, locale = 'en') {
  const keyword = query.trim().toLocaleLowerCase(locale)
  const ranked = sortSearchOptions(options, locale).map((option) => ({
    option,
    matches: Boolean(keyword) &&
      [option.label, option.description, option.disabledReason, ...(option.searchAliases ?? [])]
        .filter(Boolean)
        .join(' ')
        .toLocaleLowerCase(locale)
        .includes(keyword),
  }))
  if (!keyword) return ranked
  return [
    ...ranked.filter((entry) => entry.matches),
    ...ranked.filter((entry) => !entry.matches),
  ]
}

function optionInputLabel(option: SearchOption | undefined) {
  return option ? optionDisplay(option.label).primary : ''
}

export function SearchableSelect({
  label,
  options,
  value,
  onChange,
  placeholder,
  disabled = false,
  secondaryMode = 'always',
}: SearchableSelectProps) {
  const { t } = useUiCopy()
  const contentReferences = useMemo(
    () => options.map((option) => option.value).filter((candidate) => STABLE_KEY_RE.test(candidate)),
    [options],
  )
  const { locale, searchAliasesFor } = useContentPresentations(contentReferences)
  const searchableOptions = useMemo(
    () => options.map((option) => ({
      ...option,
      searchAliases: Array.from(new Set([
        ...(option.searchAliases ?? []),
        ...(STABLE_KEY_RE.test(option.value) ? searchAliasesFor(option.value, option.label) : []),
      ])),
    })),
    [options, searchAliasesFor],
  )
  const inputId = useId()
  const listboxId = useId()
  const [open, setOpen] = useState(false)
  const selected = searchableOptions.find((option) => option.value === value)
  const [query, setQuery] = useState(optionInputLabel(selected))
  const [activeIndex, setActiveIndex] = useState(0)
  const duplicateNames = useMemo(() => duplicateOptionNames(searchableOptions), [searchableOptions])
  const resolvedPlaceholder = placeholder ?? t('shared.search.placeholder')

  useEffect(() => {
    if (value) setQuery(optionInputLabel(searchableOptions.find((option) => option.value === value)))
    else if (!open) setQuery('')
  }, [open, searchableOptions, value])

  const rankedOptions = useMemo(
    () => rankSearchOptions(searchableOptions, query, locale),
    [locale, query, searchableOptions],
  )

  const choose = (option: SearchOption) => {
    if (option.disabled) return
    onChange(option.value)
    setQuery(optionInputLabel(option))
    setOpen(false)
  }

  const moveActive = (direction: 1 | -1) => {
    if (!rankedOptions.length) return
    let next = activeIndex
    for (let attempts = 0; attempts < rankedOptions.length; attempts += 1) {
      next = Math.min(Math.max(next + direction, 0), rankedOptions.length - 1)
      if (!rankedOptions[next]?.option.disabled || next === 0 || next === rankedOptions.length - 1) break
    }
    setActiveIndex(next)
  }

  return (
    <div className="combobox-field">
      <label htmlFor={inputId}>{label}</label>
      <div className="combobox-control">
        <input
          id={inputId}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-activedescendant={
            open && rankedOptions[activeIndex] ? `${listboxId}-${activeIndex}` : undefined
          }
          value={query}
          placeholder={resolvedPlaceholder}
          autoComplete="off"
          disabled={disabled}
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            setQuery(event.target.value)
            setActiveIndex(0)
            setOpen(true)
            if (value) onChange('')
          }}
          onBlur={() => {
            window.setTimeout(() => {
              setOpen(false)
              if (value) {
                const current = searchableOptions.find((option) => option.value === value)
                setQuery(optionInputLabel(current))
              }
            }, 120)
          }}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') {
              event.preventDefault()
              setOpen(true)
              moveActive(1)
            } else if (event.key === 'ArrowUp') {
              event.preventDefault()
              moveActive(-1)
            } else if (
              event.key === 'Enter' &&
              open &&
              rankedOptions[activeIndex] &&
              !rankedOptions[activeIndex].option.disabled
            ) {
              event.preventDefault()
              choose(rankedOptions[activeIndex].option)
            } else if (event.key === 'Escape') {
              setOpen(false)
            }
          }}
        />
        <button
          type="button"
          className="combobox-toggle"
          aria-label={t(open ? 'shared.search.collapse' : 'shared.search.expand', { label })}
          disabled={disabled}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => setOpen((current) => !current)}
        >
          ▾
        </button>
      </div>
      {open ? (
        <div className="combobox-popover" id={listboxId} role="listbox">
          {rankedOptions.length ? (
            rankedOptions.map(({ option, matches }, index) => {
              const display = optionDisplay(option.label)
              return (
                <button
                  type="button"
                  role="option"
                  id={`${listboxId}-${index}`}
                  aria-selected={option.value === value}
                  aria-disabled={option.disabled || undefined}
                  className={`combobox-option${index === activeIndex ? ' is-active' : ''}${matches ? ' is-match' : ''}`}
                  key={option.value}
                  disabled={option.disabled}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => choose(option)}
                >
                  <span>{display.primary}</span>
                  {display.secondary &&
                  (secondaryMode === 'always' || duplicateNames.has(display.primary)) ? (
                    <small>{display.secondary}</small>
                  ) : null}
                  {option.description ? <small>{option.description}</small> : null}
                  {option.disabledReason ? <small>{option.disabledReason}</small> : null}
                </button>
              )
            })
          ) : (
            <div className="combobox-empty">{t('shared.search.empty', { query })}</div>
          )}
        </div>
      ) : null}
    </div>
  )
}
