import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getCharacterSheet,
  listContent,
  patchCharacterState,
} from '../../api/character'
import type { CharacterStatePatch } from '../../api/character'
import { ExportCharacterButton } from '../character-io/ExportCharacterButton'
import { useUiCopy } from '../../i18n/useUiCopy'
import { CharacterSheetView } from './CharacterSheetView'

export { CharacterSheetView } from './CharacterSheetView'

export function CharacterSheetPage({ characterId }: { characterId: string }) {
  const { t } = useUiCopy()
  const queryClient = useQueryClient()
  const sheetQuery = useQuery({
    queryKey: ['character-sheet', characterId],
    queryFn: () => getCharacterSheet(characterId),
  })
  const conditionQuery = useQuery({
    queryKey: ['rules-content', 'conditions'],
    queryFn: () => listContent('conditions'),
  })
  const equipmentQuery = useQuery({
    queryKey: ['rules-content', 'equipment'],
    queryFn: () => listContent('equipment'),
  })
  const itemQuery = useQuery({
    queryKey: ['rules-content', 'magic-items'],
    queryFn: () => listContent('magic-items'),
  })

  const mutation = useMutation({
    mutationFn: (patch: CharacterStatePatch) => patchCharacterState(characterId, patch),
    onSuccess: (authoritativeSheet) => {
      queryClient.setQueryData(['character-sheet', characterId], authoritativeSheet)
    },
  })

  if (sheetQuery.isPending) {
    return (
      <main className="character-page loading-page">
        <div className="loading-card"><span className="loading-mark">AT</span><h1>{t('sheet.loadingTitle')}</h1><p>{t('sheet.loadingHint')}</p></div>
      </main>
    )
  }

  if (sheetQuery.isError || !sheetQuery.data) {
    return (
      <main className="character-page loading-page">
        <div className="loading-card error-state"><span className="loading-mark">!</span><h1>{t('sheet.errorTitle')}</h1><p>{sheetQuery.error instanceof Error ? sheetQuery.error.message : t('sheet.unknownError')}</p></div>
      </main>
    )
  }

  const contentError = [conditionQuery.error, equipmentQuery.error, itemQuery.error].find(Boolean)
  const mutationError = mutation.error
  const errorMessage = mutationError instanceof Error
    ? mutationError.message
    : contentError instanceof Error
      ? t('sheet.contentError', { message: contentError.message })
      : null

  return (
    <CharacterSheetView
      sheet={sheetQuery.data}
      conditionContent={conditionQuery.data ?? []}
      inventoryContent={[...(equipmentQuery.data ?? []), ...(itemQuery.data ?? [])]}
      busy={mutation.isPending}
      errorMessage={errorMessage}
      headerActions={<ExportCharacterButton characterId={characterId} placement="sheet" />}
      onPatch={async (patch) => {
        await mutation.mutateAsync(patch)
      }}
    />
  )
}
