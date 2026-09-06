import { useEffect, useState } from 'react'

import { getRoom, heartbeatRoom, RoomApiError, type RoomSummary } from '../../api/rooms'
import { useLocale } from '../../i18n/LocaleProvider'
import { localizedRoomRequestMessage } from '../../i18n/roomMessages'
import { roomCopy } from './copy'
import { startRoomHeartbeat } from './heartbeat'
import { recentRoomForId } from './roomStorage'

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

  return (
    <main className="landing-page room-workspace-page">
      <section className="landing-card room-workspace-card">
        <p className="eyebrow">{copy.workspaceEyebrow}</p>
        <h1>{room?.name ?? recent.name}</h1>
        <div className="room-workspace-meta">
          <code>{room?.code ?? recent.code}</code>
          <span>{copy.authority}: {recent.authority}</span>
        </div>
        <p>{copy.workspacePlaceholder}</p>
        <a className="button secondary" href="/">{copy.backHome}</a>
      </section>
    </main>
  )
}
