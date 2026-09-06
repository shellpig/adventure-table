import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  claimLegacyCharacterData,
  getLegacyCharacterDataStatus,
} from '../../api/roomCharacters'
import { useLocale } from '../../i18n/LocaleProvider'
import { CharacterWorkshopPage } from '../character-builder/CharacterWorkshopPage'
import { roomCopy } from './copy'
import { recentRoomForId } from './roomStorage'

export function RoomCharacterWorkspacePage({ roomId }: { roomId: string }) {
  const recent = recentRoomForId(roomId)
  const { locale } = useLocale()
  const copy = roomCopy(locale)
  const queryClient = useQueryClient()
  const isOwner = recent?.authority === 'owner'
  const legacy = useQuery({
    queryKey: ['room-legacy-character-data', roomId],
    queryFn: () => getLegacyCharacterDataStatus(roomId, recent?.accessToken ?? ''),
    enabled: Boolean(isOwner && recent?.accessToken),
  })
  const claim = useMutation({
    mutationFn: () => claimLegacyCharacterData(roomId, recent?.accessToken ?? ''),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['room-legacy-character-data', roomId] })
      void queryClient.invalidateQueries({ queryKey: ['character-list'] })
      void queryClient.invalidateQueries({ queryKey: ['builder-drafts', 'create'] })
    },
  })

  const counts = legacy.data
  const showLegacy = Boolean(isOwner && counts?.available)

  return (
    <>
      <div className="workshop-page room-character-workspace-heading">
        <div className="workshop-shell">
          <a className="builder-back" href={`/rooms/${roomId}`}>{copy.backToWorkspace}</a>
          {showLegacy ? (
            <section className="workshop-card room-legacy-card">
              <p className="eyebrow">{copy.legacyEyebrow}</p>
              <h2>{copy.legacyTitle}</h2>
              <p>{copy.legacyDescription}</p>
              <p>
                <strong>
                  {copy.legacyCounts
                    .replace('{characters}', String(counts?.character_count ?? 0))
                    .replace('{drafts}', String(counts?.draft_count ?? 0))}
                </strong>
              </p>
              {claim.error ? <div className="error-banner">{claim.error.message}</div> : null}
              <button
                type="button"
                className="button primary"
                disabled={claim.isPending}
                onClick={() => {
                  const targetName = recent?.name ?? roomId
                  const message = copy.legacyConfirm
                    .replace('{room}', targetName)
                    .replace('{characters}', String(counts?.character_count ?? 0))
                    .replace('{drafts}', String(counts?.draft_count ?? 0))
                  if (window.confirm(message)) claim.mutate()
                }}
              >
                {claim.isPending ? copy.legacyClaiming : copy.legacyClaim}
              </button>
            </section>
          ) : null}
          {legacy.error ? <div className="error-banner">{legacy.error.message}</div> : null}
        </div>
      </div>
      {!isOwner ? (
        <style>{`.room-character-member-scope .workshop-card__quiet-action--danger,.room-character-member-scope .workshop-card__danger{display:none}`}</style>
      ) : null}
      <div className={isOwner ? undefined : 'room-character-member-scope'}>
        <CharacterWorkshopPage />
      </div>
    </>
  )
}
