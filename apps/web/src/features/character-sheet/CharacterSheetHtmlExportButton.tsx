import { useState } from 'react'
import { flushSync } from 'react-dom'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'

import type { CharacterSheetDTO } from '../../api/character'
import { LocaleProvider } from '../../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type Locale, type LocaleStorage } from '../../i18n/locale'
import { characterSheetExportCopy } from '../../i18n/m01nCharacterSheetExportCopy'
import { useUiCopy } from '../../i18n/useUiCopy'
import {
  createCharacterSheetHtmlExport,
  downloadCharacterSheetHtml,
  type CharacterSheetExportScope,
  type CharacterSheetExportTab,
} from './CharacterSheetHtmlExport'
import './characterSheetExportButton.css'

const SHEET_QUERY_PREFIX = 'character-sheet'

type CharacterSheetHtmlExportButtonProps = {
  characterId: string
}

function fixedLocaleStorage(locale: Locale): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? locale : null),
    setItem: () => undefined,
  }
}

export function CharacterSheetHtmlExportButton({ characterId }: CharacterSheetHtmlExportButtonProps) {
  const queryClient = useQueryClient()
  const { locale } = useUiCopy()
  const copy = characterSheetExportCopy(locale)
  const [scope, setScope] = useState<CharacterSheetExportScope>('build')
  const [pending, setPending] = useState(false)
  const [failed, setFailed] = useState(false)

  return (
    <div className="character-html-export-action">
      <label className="character-html-export-scope">
        <span>{copy.scopeLabel}</span>
        <select
          data-testid="character-html-export-scope"
          aria-label={copy.scopeLabel}
          value={scope}
          disabled={pending}
          onChange={(event) => setScope(event.target.value as CharacterSheetExportScope)}
        >
          <option value="build">{copy.buildScope}</option>
          <option value="snapshot">{copy.snapshotScope}</option>
        </select>
      </label>
      <button
        type="button"
        className="button secondary full"
        data-testid="character-html-export-button"
        disabled={pending}
        onClick={async () => {
          setPending(true)
          setFailed(false)
          try {
            const sheet = queryClient.getQueryData<CharacterSheetDTO>([
              SHEET_QUERY_PREFIX,
              characterId,
            ])
            if (!sheet) throw new Error('Character Sheet query data is unavailable')

            // CharacterSheetPage already owns the live sheet query. Reuse that exact
            // in-memory DTO instead of introducing an export-only API request.
            const { CharacterSheetView } = await import('./CharacterSheetPage')
            const renderTab = (tab: CharacterSheetExportTab) =>
              renderCharacterSheetTab({
                CharacterSheetView,
                sheet,
                tab,
                locale,
                queryClient,
              })

            downloadCharacterSheetHtml(
              createCharacterSheetHtmlExport({
                sheet,
                scope,
                locale,
                renderTab,
              }),
            )
          } catch {
            setFailed(true)
          } finally {
            setPending(false)
          }
        }}
      >
        {pending ? copy.exporting : copy.button}
      </button>
      {failed ? (
        <span className="character-export-toast" role="alert">
          {copy.failed}
        </span>
      ) : null}
    </div>
  )
}

function renderCharacterSheetTab({
  CharacterSheetView,
  sheet,
  tab,
  locale,
  queryClient,
}: {
  CharacterSheetView: typeof import('./CharacterSheetPage').CharacterSheetView
  sheet: CharacterSheetDTO
  tab: CharacterSheetExportTab
  locale: Locale
  queryClient: QueryClient
}): string {
  const host = document.createElement('div')
  const root = createRoot(host)

  flushSync(() => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <LocaleProvider storage={fixedLocaleStorage(locale)} documentTarget={null}>
          <CharacterSheetView sheet={sheet} initialTab={tab} />
        </LocaleProvider>
      </QueryClientProvider>,
    )
  })
  const markup = host.innerHTML
  flushSync(() => root.unmount())
  return markup
}
