import { useEffect, useId, useMemo, useState } from 'react'

export type SearchOption = {
  value: string
  label: string
  description?: string
  disabled?: boolean
  disabledReason?: string
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

function optionInputLabel(option: SearchOption | undefined) {
  return option ? optionDisplay(option.label).primary : ''
}

export function SearchableSelect({
  label,
  options,
  value,
  onChange,
  placeholder = '輸入關鍵字或展開選單',
  disabled = false,
  secondaryMode = 'always',
}: SearchableSelectProps) {
  const inputId = useId()
  const listboxId = useId()
  const [open, setOpen] = useState(false)
  const selected = options.find((option) => option.value === value)
  const [query, setQuery] = useState(optionInputLabel(selected))
  const [activeIndex, setActiveIndex] = useState(0)
  const duplicateNames = useMemo(() => duplicateOptionNames(options), [options])

  useEffect(() => {
    if (value) setQuery(optionInputLabel(options.find((option) => option.value === value)))
    else if (!open) setQuery('')
  }, [open, options, value])

  const filtered = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase()
    const source = keyword
      ? options.filter((option) =>
          `${option.label} ${option.description ?? ''} ${option.disabledReason ?? ''}`
            .toLocaleLowerCase()
            .includes(keyword),
        )
      : options
    return source.slice(0, 80)
  }, [options, query])

  const choose = (option: SearchOption) => {
    if (option.disabled) return
    onChange(option.value)
    setQuery(optionInputLabel(option))
    setOpen(false)
  }

  const moveActive = (direction: 1 | -1) => {
    if (!filtered.length) return
    let next = activeIndex
    for (let attempts = 0; attempts < filtered.length; attempts += 1) {
      next = Math.min(Math.max(next + direction, 0), filtered.length - 1)
      if (!filtered[next]?.disabled || next === 0 || next === filtered.length - 1) break
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
            open && filtered[activeIndex] ? `${listboxId}-${activeIndex}` : undefined
          }
          value={query}
          placeholder={placeholder}
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
                const current = options.find((option) => option.value === value)
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
              filtered[activeIndex] &&
              !filtered[activeIndex].disabled
            ) {
              event.preventDefault()
              choose(filtered[activeIndex])
            } else if (event.key === 'Escape') {
              setOpen(false)
            }
          }}
        />
        <button
          type="button"
          className="combobox-toggle"
          aria-label={`${label}：${open ? '收合' : '展開'}選單`}
          disabled={disabled}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => setOpen((current) => !current)}
        >
          ▾
        </button>
      </div>
      {open ? (
        <div className="combobox-popover" id={listboxId} role="listbox">
          {filtered.length ? (
            filtered.map((option, index) => {
              const display = optionDisplay(option.label)
              return (
                <button
                  type="button"
                  role="option"
                  id={`${listboxId}-${index}`}
                  aria-selected={option.value === value}
                  aria-disabled={option.disabled || undefined}
                  className={index === activeIndex ? 'combobox-option is-active' : 'combobox-option'}
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
            <div className="combobox-empty">找不到符合「{query}」的項目</div>
          )}
        </div>
      ) : null}
    </div>
  )
}
