import { useEffect, useId, useMemo, useState } from 'react'

export type SearchOption = {
  value: string
  label: string
  description?: string
}

type SearchableSelectProps = {
  label: string
  options: SearchOption[]
  value: string
  onChange: (value: string) => void
  placeholder?: string
  disabled?: boolean
}

export function SearchableSelect({
  label,
  options,
  value,
  onChange,
  placeholder = '輸入關鍵字或展開選單',
  disabled = false,
}: SearchableSelectProps) {
  const inputId = useId()
  const listboxId = useId()
  const [open, setOpen] = useState(false)
  const selected = options.find((option) => option.value === value)
  const [query, setQuery] = useState(selected?.label ?? '')
  const [activeIndex, setActiveIndex] = useState(0)

  useEffect(() => {
    if (value) {
      setQuery(options.find((option) => option.value === value)?.label ?? '')
    } else if (!open) {
      setQuery('')
    }
  }, [open, options, value])

  const filtered = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase()
    const source = keyword
      ? options.filter((option) =>
          `${option.label} ${option.description ?? ''}`.toLocaleLowerCase().includes(keyword),
        )
      : options
    return source.slice(0, 80)
  }, [options, query])

  const choose = (option: SearchOption) => {
    onChange(option.value)
    setQuery(option.label)
    setOpen(false)
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
                setQuery(current?.label ?? '')
              }
            }, 120)
          }}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') {
              event.preventDefault()
              setOpen(true)
              setActiveIndex((index) => Math.min(index + 1, Math.max(filtered.length - 1, 0)))
            } else if (event.key === 'ArrowUp') {
              event.preventDefault()
              setActiveIndex((index) => Math.max(index - 1, 0))
            } else if (event.key === 'Enter' && open && filtered[activeIndex]) {
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
            filtered.map((option, index) => (
              <button
                type="button"
                role="option"
                id={`${listboxId}-${index}`}
                aria-selected={option.value === value}
                className={index === activeIndex ? 'combobox-option is-active' : 'combobox-option'}
                key={option.value}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => choose(option)}
              >
                <span>{option.label}</span>
                {option.description ? <small>{option.description}</small> : null}
              </button>
            ))
          ) : (
            <div className="combobox-empty">找不到符合「{query}」的項目</div>
          )}
        </div>
      ) : null}
    </div>
  )
}
