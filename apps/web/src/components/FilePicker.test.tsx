import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { LocaleProvider } from '../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type Locale, type LocaleStorage } from '../i18n/locale'
import { FilePicker } from './FilePicker'

function localeStorage(locale: Locale): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? locale : null),
    setItem: () => undefined,
  }
}

function renderPicker(
  props: {
    accept?: string
    disabled?: boolean
    onFileChange?: (file: File | null) => void
    chooseLabel?: string
  } = {},
  locale: Locale = 'en',
) {
  return renderToStaticMarkup(
    <LocaleProvider storage={localeStorage(locale)} documentTarget={null}>
      <FilePicker
        accept={props.accept ?? 'image/*'}
        disabled={props.disabled ?? false}
        onFileChange={props.onFileChange ?? (() => undefined)}
        chooseLabel={props.chooseLabel}
      />
    </LocaleProvider>,
  )
}

describe('FilePicker component', () => {
  it('renders the native file input FIRST with type=file, accept attribute, tabindex -1 and class file-picker__input', () => {
    const html = renderPicker({ accept: 'image/png,image/jpeg' })
    const inputIndex = html.indexOf('<input')
    const buttonIndex = html.indexOf('<button')
    const nameIndex = html.indexOf('class="file-picker__name"')

    expect(inputIndex).toBeGreaterThan(-1)
    expect(buttonIndex).toBeGreaterThan(inputIndex)
    expect(nameIndex).toBeGreaterThan(buttonIndex)

    expect(html).toContain('type="file"')
    expect(html).toContain('class="file-picker__input"')
    expect(html).toContain('tabindex="-1"')
    expect(html).toContain('accept="image/png,image/jpeg"')
  })

  it('renders the localized no-file text in en and zh-TW', () => {
    const enHtml = renderPicker({}, 'en')
    expect(enHtml).toContain('Choose file')
    expect(enHtml).toContain('No file chosen')

    const zhHtml = renderPicker({}, 'zh-TW')
    expect(zhHtml).toContain('選擇檔案')
    expect(zhHtml).toContain('尚未選擇檔案')
  })

  it('uses chooseLabel when given', () => {
    const html = renderPicker({ chooseLabel: 'Choose custom file' })
    expect(html).toContain('Choose custom file')
    expect(html).not.toContain('Choose file')
  })

  it('passes disabled through and never marks the native input required', () => {
    const defaultHtml = renderPicker({ disabled: false })
    expect(defaultHtml).not.toMatch(/<input[^>]*\brequired\b/)
    expect(defaultHtml).not.toMatch(/<input[^>]*\bdisabled\b/)
    expect(defaultHtml).not.toMatch(/<button[^>]*\bdisabled\b/)

    const disabledHtml = renderPicker({ disabled: true })
    expect(disabledHtml).toMatch(/<input[^>]*\bdisabled\b/)
    expect(disabledHtml).toMatch(/<button[^>]*\bdisabled\b/)
  })
})
