import { type FormEvent, useMemo, useState } from 'react'

import { createRoom, enterRoom, RoomApiError, type RoomAccessGrant } from '../../api/rooms'
import { useLocale } from '../../i18n/LocaleProvider'
import { localizedRoomRequestMessage } from '../../i18n/roomMessages'
import { roomCopy } from './copy'
import { persistRoomGrant, readRecentRooms } from './roomStorage'

function navigateToRoom(roomId: string) {
  if (typeof window !== 'undefined') window.location.assign(`/rooms/${roomId}`)
}

export function RoomLandingPage() {
  const { locale } = useLocale()
  const copy = roomCopy(locale)
  const [recentRooms, setRecentRooms] = useState(() => readRecentRooms())
  const [created, setCreated] = useState<RoomAccessGrant | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [createName, setCreateName] = useState('')
  const [createPassword, setCreatePassword] = useState('')
  const [createDisplayName, setCreateDisplayName] = useState('')

  const [enterCode, setEnterCode] = useState('')
  const [enterPassword, setEnterPassword] = useState('')
  const [enterKey, setEnterKey] = useState('')
  const [enterDisplayName, setEnterDisplayName] = useState('')

  const canCreate = useMemo(
    () => createName.trim().length > 0 && createPassword.length >= 6,
    [createName, createPassword],
  )
  const canEnter = useMemo(
    () => enterCode.trim().length > 0 && enterPassword.length >= 6,
    [enterCode, enterPassword],
  )

  function presentError(cause: unknown) {
    if (!(cause instanceof RoomApiError)) return copy.requestError
    return localizedRoomRequestMessage(cause.code, cause.status, cause.message, locale)
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canCreate || busy) return
    setBusy(true)
    setError(null)
    try {
      const grant = await createRoom({
        name: createName,
        password: createPassword,
        displayName: createDisplayName,
      })
      persistRoomGrant(grant)
      setRecentRooms(readRecentRooms())
      setCreated(grant)
      setCreatePassword('')
    } catch (cause) {
      setError(presentError(cause))
    } finally {
      setBusy(false)
    }
  }

  async function handleEnter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canEnter || busy) return
    setBusy(true)
    setError(null)
    try {
      const grant = await enterRoom({
        code: enterCode,
        password: enterPassword,
        elevatedKey: enterKey,
        displayName: enterDisplayName,
      })
      persistRoomGrant(grant)
      navigateToRoom(grant.room.id)
    } catch (cause) {
      setError(presentError(cause))
      setBusy(false)
    }
  }

  if (created) {
    return (
      <main className="landing-page room-entry-page">
        <section className="landing-card room-secret-card">
          <p className="eyebrow">{copy.eyebrow}</p>
          <h1>{copy.createdTitle}</h1>
          <p>{copy.createdDescription}</p>
          <dl className="room-secret-list">
            <div><dt>{copy.roomCodeLabel}</dt><dd><code>{created.room.code}</code></dd></div>
            <div><dt>{copy.ownerKey}</dt><dd><code>{created.owner_key}</code></dd></div>
            <div><dt>{copy.dmKey}</dt><dd><code>{created.dm_key}</code></dd></div>
          </dl>
          <button
            className="button primary landing-action"
            type="button"
            onClick={() => navigateToRoom(created.room.id)}
          >
            {copy.continueAction}
          </button>
        </section>
      </main>
    )
  }

  return (
    <main className="landing-page room-entry-page">
      <section className="landing-card room-entry-card">
        <p className="eyebrow">{copy.eyebrow}</p>
        <div className="landing-mark" aria-hidden="true">AT</div>
        <h1>Adventure Table</h1>
        <h2>{copy.title}</h2>
        <p>{copy.description}</p>
        {error ? <p className="form-error" role="alert">{error}</p> : null}

        <div className="room-entry-grid">
          <form className="room-entry-form" onSubmit={handleCreate}>
            <h3>{copy.createTitle}</h3>
            <label>
              <span>{copy.roomName}</span>
              <input value={createName} onChange={(event) => setCreateName(event.target.value)} maxLength={120} required />
            </label>
            <label>
              <span>{copy.password}</span>
              <input type="password" value={createPassword} onChange={(event) => setCreatePassword(event.target.value)} minLength={6} maxLength={128} required />
            </label>
            <label>
              <span>{copy.displayName}</span>
              <input value={createDisplayName} onChange={(event) => setCreateDisplayName(event.target.value)} maxLength={100} />
            </label>
            <button className="button primary" type="submit" disabled={!canCreate || busy}>{copy.createAction}</button>
          </form>

          <form className="room-entry-form" onSubmit={handleEnter}>
            <h3>{copy.enterTitle}</h3>
            <label>
              <span>{copy.roomCode}</span>
              <input value={enterCode} onChange={(event) => setEnterCode(event.target.value.toUpperCase())} maxLength={10} autoCapitalize="characters" required />
            </label>
            <label>
              <span>{copy.password}</span>
              <input type="password" value={enterPassword} onChange={(event) => setEnterPassword(event.target.value)} minLength={6} maxLength={128} required />
            </label>
            <label>
              <span>{copy.elevatedKey}</span>
              <input type="password" value={enterKey} onChange={(event) => setEnterKey(event.target.value)} maxLength={256} />
            </label>
            <label>
              <span>{copy.displayName}</span>
              <input value={enterDisplayName} onChange={(event) => setEnterDisplayName(event.target.value)} maxLength={100} />
            </label>
            <button className="button secondary" type="submit" disabled={!canEnter || busy}>{copy.enterAction}</button>
          </form>
        </div>

        {recentRooms.length > 0 ? (
          <section className="recent-rooms">
            <h3>{copy.recentTitle}</h3>
            <div className="recent-room-list">
              {recentRooms.map((room) => (
                <a className="recent-room-card" href={`/rooms/${room.roomId}`} key={room.roomId}>
                  <strong>{room.name}</strong>
                  <code>{room.code}</code>
                </a>
              ))}
            </div>
          </section>
        ) : null}
      </section>
    </main>
  )
}
