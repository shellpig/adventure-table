import { useEffect, useState } from 'react'

import {
  archiveAdventure,
  createAdventure,
  deleteAdventure,
  finalizeAdventure,
  listAdventures,
  type AdventureDefinition,
  type AdventureStatus,
} from '../../api/adventures'
import type { RoomAuthority } from '../../api/rooms'
import { useLocale } from '../../i18n/LocaleProvider'
import { AdventureEditorPage } from './AdventureEditorPage'
import { AdventureImporterPanel } from './AdventureImporterPanel'
import { adventureErrorMessage, adventuresCopy } from './adventuresCopy'
import { recentRoomForId } from './roomStorage'
import './rooms.css'

const UUID_PATTERN = '[0-9a-fA-F-]{36}'

export type RoomAdventuresRoute = {
  roomId: string
  adventureId: string | null
}

export function roomAdventuresRouteFromPath(pathname: string): RoomAdventuresRoute | null {
  const match = pathname.match(
    new RegExp(`^/rooms/(${UUID_PATTERN})/adventures(?:/(${UUID_PATTERN}))?/?$`),
  )
  return match ? { roomId: match[1], adventureId: match[2] ?? null } : null
}

export function adventurePermissions(authority: RoomAuthority | null | undefined): {
  canAuthor: boolean
} {
  return {
    canAuthor: authority === 'owner' || authority === 'dm',
  }
}

export function adventureActions(status: AdventureStatus): {
  finalize: boolean
  archive: boolean
  delete: boolean
} {
  switch (status) {
    case 'draft':
      return { finalize: true, archive: true, delete: true }
    case 'finalized':
      return { finalize: false, archive: true, delete: true }
    case 'archived':
      return { finalize: false, archive: false, delete: true }
  }
}

export function adventureStatusLabel(
  status: AdventureStatus,
  copy: ReturnType<typeof adventuresCopy>,
): string {
  switch (status) {
    case 'draft':
      return copy.statusDraft
    case 'finalized':
      return copy.statusFinalized
    case 'archived':
      return copy.statusArchived
  }
}

export type AdventureListProps = {
  adventures: AdventureDefinition[]
  copy: ReturnType<typeof adventuresCopy>
  onFinalize: (id: string) => void
  onArchive: (id: string) => void
  onDelete: (id: string) => void
  roomId: string
  pending?: boolean
}

export function AdventureList({
  adventures,
  copy,
  onFinalize,
  onArchive,
  onDelete,
  roomId,
  pending = false,
}: AdventureListProps) {
  if (adventures.length === 0) {
    return <p className="room-empty-text">{copy.empty}</p>
  }

  const statusLabel = (status: AdventureStatus) => adventureStatusLabel(status, copy)

  return (
    <div className="adventure-grid">
      {adventures.map((item) => {
        const actions = adventureActions(item.status)
        return (
          <article className="adventure-card" key={item.id}>
            <h2>{item.name}</h2>
            <p className="adventure-card__status">
              {copy.statusLabel}: {statusLabel(item.status)}
            </p>
            {item.summary ? <p className="adventure-card__summary">{item.summary}</p> : null}
            <p className="adventure-card__updated">
              {item.updated_at}
            </p>
            <div className="adventure-card__actions">
              <a className="button primary" href={`/rooms/${roomId}/adventures/${item.id}`}>
                {copy.open}
              </a>
              {actions.finalize ? (
                <button
                  className="button secondary"
                  disabled={pending}
                  type="button"
                  onClick={() => onFinalize(item.id)}
                >
                  {copy.finalize}
                </button>
              ) : null}
              {actions.archive ? (
                <button
                  className="button secondary"
                  disabled={pending}
                  type="button"
                  onClick={() => {
                    if (!window.confirm(copy.archiveConfirm)) return
                    onArchive(item.id)
                  }}
                >
                  {copy.archive}
                </button>
              ) : null}
              {actions.delete ? (
                <button
                  className="button danger"
                  disabled={pending}
                  type="button"
                  onClick={() => {
                    if (!window.confirm(copy.deleteConfirm)) return
                    onDelete(item.id)
                  }}
                >
                  {copy.delete}
                </button>
              ) : null}
            </div>
          </article>
        )
      })}
    </div>
  )
}

export function RoomAdventuresPage({ roomId, adventureId }: RoomAdventuresRoute) {
  const { locale } = useLocale()
  const copy = adventuresCopy(locale)
  const recent = recentRoomForId(roomId)
  const token = recent?.accessToken ?? ''
  const { canAuthor } = adventurePermissions(recent?.authority)

  const [adventures, setAdventures] = useState<AdventureDefinition[]>([])
  const [name, setName] = useState('')
  const [summary, setSummary] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reloadList = async () => {
    const list = await listAdventures(roomId, token)
    setAdventures(list)
  }

  const runMutation = (operation: () => Promise<unknown>) => {
    setPending(true)
    setError(null)
    void operation()
      .then(() => reloadList())
      .catch((cause: unknown) => setError(adventureErrorMessage(cause, copy)))
      .finally(() => setPending(false))
  }

  useEffect(() => {
    if (!recent || !canAuthor) return
    if (adventureId) return
    let active = true

    void listAdventures(roomId, token)
      .then((items) => {
        if (active) setAdventures(items)
      })
      .catch((cause: unknown) => {
        if (active) setError(adventureErrorMessage(cause, copy))
      })

    return () => {
      active = false
    }
    // `recent` is re-read from storage on every render; the token is the stable credential.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adventureId, canAuthor, roomId, token])

  if (!recent) {
    return (
      <main className="landing-page room-workspace-page">
        <section className="landing-card room-workspace-card">
          <h1>{copy.title}</h1>
          <p>{copy.missingAccess}</p>
          <a className="button secondary" href="/">{copy.backRoom}</a>
        </section>
      </main>
    )
  }

  if (!canAuthor) {
    return (
      <main className="landing-page room-workspace-page">
        <section className="landing-card room-workspace-card">
          <h1>{copy.title}</h1>
          <p>{copy.noAuthority}</p>
          <a className="button secondary" href={`/rooms/${roomId}`}>{copy.backRoom}</a>
        </section>
      </main>
    )
  }

  if (adventureId) {
    return <AdventureEditorPage roomId={roomId} adventureId={adventureId} token={token} />
  }

  return (
    <main className="landing-page room-workspace-page">
      <section className="landing-card room-workspace-card">
        <h1>{copy.title}</h1>
        <p>{copy.intro}</p>
        <a className="button secondary" href={`/rooms/${roomId}`}>{copy.backRoom}</a>

        {error ? <div className="form-error">{error}</div> : null}

        <form
          className="room-form"
          onSubmit={(event) => {
            event.preventDefault()
            runMutation(() =>
              createAdventure(roomId, token, {
                name: name.trim(),
                summary: summary.trim() ? summary.trim() : null,
              }).then(() => {
                setName('')
                setSummary('')
              }),
            )
          }}
        >
          <h2>{copy.createTitle}</h2>
          <label className="room-field">
            <span>{copy.nameLabel}</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </label>
          <label className="room-field">
            <span>{copy.summaryLabel}</span>
            <input
              value={summary}
              onChange={(event) => setSummary(event.target.value)}
            />
          </label>
          <button
            className="button primary room-form-submit"
            disabled={pending || !name.trim()}
            type="submit"
          >
            {copy.createAction}
          </button>
        </form>

        <AdventureList
          adventures={adventures}
          copy={copy}
          roomId={roomId}
          pending={pending}
          onFinalize={(id) => runMutation(() => finalizeAdventure(roomId, id, token))}
          onArchive={(id) => runMutation(() => archiveAdventure(roomId, id, token))}
          onDelete={(id) => runMutation(() => deleteAdventure(roomId, id, token))}
        />

        <AdventureImporterPanel
          key={`${roomId}:${token}`}
          canAuthor={canAuthor}
          roomId={roomId}
          token={token}
          onFinalized={(adv) => {
            void reloadList()
            window.location.assign(`/rooms/${roomId}/adventures/${adv.id}`)
          }}
        />
      </section>
    </main>
  )
}
