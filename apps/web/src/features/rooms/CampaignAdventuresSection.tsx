import { useEffect, useMemo, useState } from 'react'

import {
  attachCampaignAdventure,
  detachCampaignAdventure,
  listAdventures,
  listCampaignAdventures,
  type AdventureDefinition,
  type AttachedAdventure,
} from '../../api/adventures'
import { useLocale } from '../../i18n/LocaleProvider'
import { adventureErrorMessage, adventuresCopy } from './adventuresCopy'
import { adventureStatusLabel } from './RoomAdventuresPage'
import './rooms.css'

export function attachableAdventures(
  all: AdventureDefinition[],
  attached: AttachedAdventure[],
): AdventureDefinition[] {
  const attachedIds = new Set(attached.map((item) => item.adventure_id))
  return all.filter((item) => item.status === 'finalized' && !attachedIds.has(item.id))
}

export type AttachedAdventureListProps = {
  attached: AttachedAdventure[]
  copy: ReturnType<typeof adventuresCopy>
  roomId: string
  pending?: boolean
  onDetach: (adventureId: string) => void
}

export function AttachedAdventureList({
  attached,
  copy,
  roomId,
  pending = false,
  onDetach,
}: AttachedAdventureListProps) {
  if (attached.length === 0) {
    return <p>{copy.attachedEmpty}</p>
  }

  return (
    <div className="adventure-grid">
      {attached.map((item) => (
        <article className="adventure-card" key={item.adventure_id}>
          <h2>{item.name}</h2>
          <p className="adventure-card__status">
            {copy.statusLabel}: {adventureStatusLabel(item.status, copy)}
          </p>
          {item.summary ? <p className="adventure-card__summary">{item.summary}</p> : null}
          <div className="adventure-card__actions">
            <a className="button primary" href={`/rooms/${roomId}/adventures/${item.adventure_id}`}>
              {copy.open}
            </a>
            <button
              className="button secondary"
              disabled={pending}
              type="button"
              onClick={() => {
                if (!window.confirm(copy.detachConfirm)) return
                onDetach(item.adventure_id)
              }}
            >
              {copy.detach}
            </button>
          </div>
        </article>
      ))}
    </div>
  )
}

export type CampaignAdventuresSectionProps = {
  roomId: string
  campaignId: string
  token: string
}

export function CampaignAdventuresSection({
  roomId,
  campaignId,
  token,
}: CampaignAdventuresSectionProps) {
  const { locale } = useLocale()
  const copy = adventuresCopy(locale)
  const [attached, setAttached] = useState<AttachedAdventure[]>([])
  const [adventures, setAdventures] = useState<AdventureDefinition[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const attachable = useMemo(
    () => attachableAdventures(adventures, attached),
    [adventures, attached],
  )

  const reload = async () => {
    const [nextAttached, nextAdventures] = await Promise.all([
      listCampaignAdventures(roomId, campaignId, token),
      listAdventures(roomId, token),
    ])
    setAttached(nextAttached)
    setAdventures(nextAdventures)
    const nextAvailable = attachableAdventures(nextAdventures, nextAttached)
    setSelectedId((current) =>
      nextAvailable.some((item) => item.id === current) ? current : (nextAvailable[0]?.id ?? ''),
    )
  }

  const runMutation = (operation: () => Promise<unknown>) => {
    setPending(true)
    setError(null)
    void operation()
      .then(() => reload())
      .catch((cause: unknown) => setError(adventureErrorMessage(cause, copy)))
      .finally(() => setPending(false))
  }

  useEffect(() => {
    let active = true
    setPending(true)
    setError(null)
    void reload()
      .catch((cause: unknown) => {
        if (active) setError(adventureErrorMessage(cause, copy))
      })
      .finally(() => {
        if (active) setPending(false)
      })

    return () => {
      active = false
    }
    // The Room token is the authoritative browser credential for this section.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, campaignId, token])

  return (
    <>
      <hr />
      <h2>{copy.attachedTitle}</h2>
      <p>{copy.attachedIntro}</p>
      {error ? <div className="form-error">{error}</div> : null}
      {attachable.length > 0 ? (
        <div className="roster-add-bar">
          <label className="room-field roster-add-field">
            <span>{copy.attachPicker}</span>
            <select
              disabled={pending}
              value={selectedId}
              onChange={(event) => setSelectedId(event.target.value)}
            >
              {attachable.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <button
            className="button primary roster-add-button"
            disabled={pending || !selectedId}
            type="button"
            onClick={() =>
              runMutation(() => attachCampaignAdventure(roomId, campaignId, token, selectedId))
            }
          >
            {copy.attachAction}
          </button>
        </div>
      ) : (
        <p>
          {copy.noAttachable}{' '}
          <a href={`/rooms/${roomId}/adventures`}>{copy.goToAdventures}</a>
        </p>
      )}
      <AttachedAdventureList
        attached={attached}
        copy={copy}
        pending={pending}
        roomId={roomId}
        onDetach={(adventureId) =>
          runMutation(() => detachCampaignAdventure(roomId, campaignId, adventureId, token))
        }
      />
    </>
  )
}
