import { useEffect, useState } from 'react'

import { deleteRoom, getRoom, heartbeatRoom, RoomApiError, type RoomSummary } from '../../api/rooms'
import { useLocale } from '../../i18n/LocaleProvider'
import { localizedRoomRequestMessage } from '../../i18n/roomMessages'
import { roomCopy } from './copy'
import { startRoomHeartbeat } from './heartbeat'
import { forgetRecentRoom, recentRoomForId } from './roomStorage'
import './rooms.css'

export function roomIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/rooms\/([0-9a-fA-F-]{36})\/?$/)
  return match?.[1] ?? null
}

export function RoomWorkspacePage({ roomId }: { roomId: string }) {
  const { locale } = useLocale()
  const copy = roomCopy(locale)
  const recent = recentRoomForId(roomId)
  const [room, setRoom] = useState<RoomSummary | null>(null)
  const [roomError, setRoomError] = useState<RoomApiError | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'missing' | 'error'>(
    recent ? 'loading' : 'missing',
  )
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteConfirmation, setDeleteConfirmation] = useState('')
  const [deletePending, setDeletePending] = useState(false)
  const [deleteError, setDeleteError] = useState<RoomApiError | null>(null)

  useEffect(() => {
    if (!recent) return
    let active = true

    void getRoom(roomId, recent.accessToken)
      .then((next) => {
        if (!active) return
        setRoom(next)
        setRoomError(null)
        setStatus('ready')
      })
      .catch((cause: unknown) => {
        if (!active) return
        setRoomError(cause instanceof RoomApiError ? cause : null)
        setStatus('error')
      })

    const stopHeartbeat = startRoomHeartbeat(async () => {
      try {
        await heartbeatRoom(roomId, recent.accessToken)
      } catch (cause) {
        if (active) {
          setRoomError(cause instanceof RoomApiError ? cause : null)
          setStatus('error')
        }
      }
    })

    return () => {
      active = false
      stopHeartbeat()
    }
  }, [recent?.accessToken, roomId])

  if (status === 'missing') {
    return (
      <main className="landing-page room-workspace-page">
        <section className="landing-card room-workspace-card">
          <p className="eyebrow">{copy.workspaceEyebrow}</p>
          <h1>Adventure Table</h1>
          <p>{copy.workspaceMissing}</p>
          <a className="button secondary" href="/">{copy.backHome}</a>
        </section>
      </main>
    )
  }

  if (status === 'loading') {
    return (
      <main className="landing-page room-workspace-page">
        <section className="landing-card room-workspace-card">
          <p className="eyebrow">{copy.workspaceEyebrow}</p>
          <h1>{copy.workspaceLoading}</h1>
        </section>
      </main>
    )
  }

  if (status === 'error' || !recent) {
    const message = roomError
      ? localizedRoomRequestMessage(roomError.code, roomError.status, roomError.message, locale)
      : copy.workspaceError
    return (
      <main className="landing-page room-workspace-page">
        <section className="landing-card room-workspace-card">
          <p className="eyebrow">{copy.workspaceEyebrow}</p>
          <h1>Adventure Table</h1>
          <p>{message}</p>
          <a className="button secondary" href="/">{copy.backHome}</a>
        </section>
      </main>
    )
  }

  const roomName = room?.name ?? recent.name
  const isOwner = recent.authority === 'owner'

  return (
    <main className="landing-page room-workspace-page">
      <section className="landing-card room-workspace-card">
        <p className="eyebrow">{copy.workspaceEyebrow}</p>
        <h1>{roomName}</h1>
        <div className="room-workspace-meta">
          <code>{room?.code ?? recent.code}</code>
          <span>{copy.authority}: {recent.authority}</span>
        </div>
        <p>{copy.workspacePlaceholder}</p>
        <div className="workshop-card__split-actions">
          <a className="button primary" href={`/rooms/${roomId}/characters`}>
            {copy.charactersAction}
          </a>
          <a className="button primary" href={`/rooms/${roomId}/campaigns`}>
            {copy.campaignsAction}
          </a>
          <a className="button secondary" href="/">{copy.backHome}</a>
        </div>

        {isOwner ? (
          <div className="workshop-card__danger">
            <strong>{copy.deleteRoomTitle}</strong>
            <p>{copy.deleteRoomDescription}</p>
            {deleteError ? (
              <div className="error-banner">
                {localizedRoomRequestMessage(deleteError.code, deleteError.status, deleteError.message, locale)}
              </div>
            ) : null}
            {deleteOpen ? (
              <>
                <label htmlFor={`delete-room-${roomId}`}>
                  {copy.deleteRoomPrompt.replace('{room}', roomName)}
                </label>
                <input
                  id={`delete-room-${roomId}`}
                  value={deleteConfirmation}
                  autoComplete="off"
                  onChange={(event) => setDeleteConfirmation(event.target.value)}
                />
                <div className="workshop-card__split-actions">
                  <button
                    type="button"
                    className="button secondary"
                    disabled={deletePending}
                    onClick={() => {
                      setDeleteOpen(false)
                      setDeleteConfirmation('')
                      setDeleteError(null)
                    }}
                  >
                    {copy.deleteRoomCancel}
                  </button>
                  <button
                    type="button"
                    className="button danger"
                    disabled={deletePending || deleteConfirmation.trim() !== roomName}
                    onClick={() => {
                      setDeletePending(true)
                      setDeleteError(null)
                      void deleteRoom(roomId, recent.accessToken)
                        .then(() => {
                          forgetRecentRoom(roomId)
                          window.location.assign('/')
                        })
                        .catch((cause: unknown) => {
                          setDeleteError(cause instanceof RoomApiError ? cause : null)
                          setDeletePending(false)
                        })
                    }}
                  >
                    {deletePending ? copy.deleteRoomDeleting : copy.deleteRoomConfirm}
                  </button>
                </div>
              </>
            ) : (
              <button
                type="button"
                className="workshop-card__quiet-action workshop-card__quiet-action--danger"
                onClick={() => setDeleteOpen(true)}
              >
                {copy.deleteRoomAction}
              </button>
            )}
          </div>
        ) : null}
      </section>
    </main>
  )
}
