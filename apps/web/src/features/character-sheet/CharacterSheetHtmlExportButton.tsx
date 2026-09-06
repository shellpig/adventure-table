import { useState } from 'react'
import { flushSync } from 'react-dom'
import { createRoot } from 'react-dom/client'
import {
  QueryClient,
  QueryClientProvider,
  useIsFetching,
  useQueryClient,
} from '@tanstack/react-query'

import type { CharacterSheetDTO, ContentEntry } from '../../api/character'
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
  const supportFetches = useIsFetching({ queryKey: ['rules-content'] })
  const presentationFetches = useIsFetching({ queryKey: ['content-presentations'] })
  const { locale } = useUiCopy()
  const copy = characterSheetExportCopy(locale)
  const [scope, setScope] = useState<CharacterSheetExportScope>('build')
  const [pending, setPending] = useState(false)
  const [failed, setFailed] = useState(false)
  const dataPending = supportFetches > 0 || presentationFetches > 0

  return (
    <div className="character-html-export-action">
      <label className="character-html-export-scope">
        <span>{copy.scopeLabel}</span>
        <select
          data-testid="character-html-export-scope"
          aria-label={copy.scopeLabel}
          value={scope}
          disabled={pending || dataPending}
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
        disabled={pending || dataPending}
        onClick={async () => {
          setPending(true)
          setFailed(false)
          try {
            const sheet = queryClient.getQueryData<CharacterSheetDTO>([
              SHEET_QUERY_PREFIX,
              characterId,
            ])
            if (!sheet) throw new Error('Character Sheet query data is unavailable')

            const conditionContent =
              queryClient.getQueryData<ContentEntry[]>(['rules-content', 'conditions']) ?? []
            const inventoryContent = [
              ...(queryClient.getQueryData<ContentEntry[]>(['rules-content', 'equipment']) ?? []),
              ...(queryClient.getQueryData<ContentEntry[]>(['rules-content', 'magic-items']) ?? []),
            ]

            // Freeze the data that the visible Character Sheet already holds. The
            // detached renderer gets a private cache with infinite staleness, so
            // useContentPresentations cannot turn an HTML export into a new API read.
            const exportQueryClient = createFrozenExportQueryClient(queryClient)
            try {
              const { CharacterSheetView } = await import('./CharacterSheetPage')
              const renderTab = (tab: CharacterSheetExportTab) =>
                renderCharacterSheetTab({
                  CharacterSheetView,
                  sheet,
                  conditionContent,
                  inventoryContent,
                  tab,
                  locale,
                  queryClient: exportQueryClient,
                })

              downloadCharacterSheetHtml(
                createCharacterSheetHtmlExport({
                  sheet,
                  scope,
                  locale,
                  renderTab,
                }),
              )
            } finally {
              exportQueryClient.clear()
            }
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

export function createFrozenExportQueryClient(source: QueryClient): QueryClient {
  const target = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        gcTime: Infinity,
        retry: false,
      },
    },
  })

  for (const query of source.getQueryCache().getAll()) {
    if (query.state.data !== undefined) {
      target.setQueryData(query.queryKey, query.state.data)
      continue
    }
    if (query.queryKey[0] === 'content-presentations') {
      // A visible sheet may currently be showing canonical fallback text after a
      // failed presentation request. Preserve that fallback without retrying it.
      target.setQueryData(query.queryKey, { presentations: [] })
    }
  }
  return target
}

function renderCharacterSheetTab({
  CharacterSheetView,
  sheet,
  conditionContent,
  inventoryContent,
  tab,
  locale,
  queryClient,
}: {
  CharacterSheetView: typeof import('./CharacterSheetPage').CharacterSheetView
  sheet: CharacterSheetDTO
  conditionContent: ContentEntry[]
  inventoryContent: ContentEntry[]
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
          <CharacterSheetView
            sheet={sheet}
            conditionContent={conditionContent}
            inventoryContent={inventoryContent}
            initialTab={tab}
          />
        </LocaleProvider>
      </QueryClientProvider>,
    )
  })
  const markup = host.innerHTML
  root.unmount()
  return markup
}
