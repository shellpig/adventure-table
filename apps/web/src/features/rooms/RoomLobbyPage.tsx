import { useEffect, useMemo, useState } from 'react'

import { listRoomCharacters, listRoster, type RoomCharacterSummary, type RosterEntry } from '../../api/campaigns'
import { heartbeatRoom } from '../../api/rooms'
import {
  archiveSeat,
  createSeat,
  deleteSeat,
  getLobby,
  SeatApiError,
  setSeatCharacter,
  setSeatController,
  type CampaignSeat,
  type LobbySnapshot,
  type SeatRole,
} from '../../api/seats'
import { useLocale } from '../../i18n/LocaleProvider'
import { startRoomHeartbeat } from './heartbeat'
import { lobbyCopy } from './lobbyCopy'
import { recentRoomForId } from './roomStorage'
import './rooms.css'

const UUID_PATTERN = '[0-9a-fA-F-]{36}'

export type RoomLobbyRoute = { roomId: string; campaignId: string }

export function roomLobbyRouteFromPath(pathname: string): RoomLobbyRoute | null {
  const match = pathname.match(
    new RegExp(`^/rooms/(${UUID_PATTERN})/campaigns/(${UUID_PATTERN})/lobby/?$`),
  )
  return match ? { roomId: match[1], campaignId: match[2] } : null
}

function message(error: unknown, fallback: string) {
  return error instanceof SeatApiError ? error.message : fallback
}

export function RoomLobbyPage({ roomId, campaignId }: RoomLobbyRoute) {
  const { locale } = useLocale()
  const copy = lobbyCopy(locale)
  const recent = recentRoomForId(roomId)
  const token = recent?.accessToken ?? ''
  const authority = recent?.authority
  const isOwner = authority === 'owner'
  const canManage = authority === 'owner' || authority === 'dm'
  const [snapshot, setSnapshot] = useState<LobbySnapshot | null>(null)
  const [roster, setRoster] = useState<RosterEntry[]>([])
  const [characters, setCharacters] = useState<RoomCharacterSummary[]>([])
  const [role, setRole] = useState<SeatRole>('player')
  const [label, setLabel] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reload = async () => {
    const [nextLobby, nextRoster, nextCharacters] = await Promise.all([
      getLobby(roomId, campaignId, token),
      listRoster(roomId, campaignId, token),
      listRoomCharacters(roomId, token),
    ])
    setSnapshot(nextLobby)
    setRoster(nextRoster)
    setCharacters(nextCharacters)
  }

  useEffect(() => {
    if (!recent) return
    let active = true
    void reload().catch((cause) => {
      if (active) setError(message(cause, copy.requestFailed))
    })
    const stopHeartbeat = startRoomHeartbeat(async () => {
      try {
        await heartbeatRoom(roomId, token)
      } catch (cause) {
        if (active) setError(message(cause, copy.requestFailed))
      }
    })
    return () => {
      active = false
      stopHeartbeat()
    }
    // Room credential and route identify this Lobby.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, campaignId, token])

  const eligibleCharacters = useMemo(() => {
    const allowed = new Set(
      roster.filter((entry) => entry.status === 'active' || entry.status === 'inactive')
        .map((entry) => entry.character_id),
    )
    return characters.filter((character) => allowed.has(character.id))
  }, [characters, roster])

  const mutate = (operation: () => Promise<unknown>) => {
    setPending(true)
    setError(null)
    void operation()
      .then(() => reload())
      .catch((cause) => setError(message(cause, copy.requestFailed)))
      .finally(() => setPending(false))
  }

  if (!recent) {
    return (
      <main className="landing-page room-workspace-page">
        <section className="landing-card room-workspace-card">
          <h1>{copy.title}</h1>
          <p>{copy.missingAccess}</p>
          <a className="button secondary" href="/">{copy.backCampaign}</a>
        </section>
      </main>
    )
  }

  if (!snapshot) {
    return (
      <main className="landing-page"><section className="landing-card">
        <h1>{copy.title}</h1>
        {error ? <div className="error-banner">{error}</div> : null}
        <a className="button secondary" href={`/rooms/${roomId}/campaigns/${campaignId}`}>{copy.backCampaign}</a>
      </section></main>
    )
  }

  const selectedElsewhere = (seat: CampaignSeat) => new Set(
    snapshot.seats
      .filter((other) => other.id !== seat.id && other.selected_character_id)
      .map((other) => other.selected_character_id as string),
  )

  const canOperateCharacter = (seat: CampaignSeat) =>
    seat.role === 'player' && (
      canManage || (
        authority === 'member' &&
        seat.controller_kind === 'human' &&
        seat.controller_access_session_id === snapshot.caller_access_session_id
      )
    )

  const selectedCharacterName = (seat: CampaignSeat) =>
    characters.find((character) => character.id === seat.selected_character_id)?.name ?? copy.noCharacter

  return (
    <main className="landing-page room-workspace-page">
      <section className="landing-card room-workspace-card">
        <h1>{copy.title}</h1>
        <p>{copy.intro}</p>
        <div className="workshop-card__split-actions">
          <a className="button secondary" href={`/rooms/${roomId}/campaigns/${campaignId}`}>{copy.backCampaign}</a>
        </div>
        <p>{copy.dmSeatHint}</p>
        <p>{copy.activeRosterOnly}</p>
        {authority === 'member' ? <p>{copy.memberHint}</p> : null}
        {error ? <div className="error-banner">{error}</div> : null}

        {canManage ? (
          <form
            className="room-form"
            onSubmit={(event) => {
              event.preventDefault()
              mutate(() => createSeat(roomId, campaignId, token, { role, label: label || null }))
              setLabel('')
            }}
          >
            <h2>{copy.createSeat}</h2>
            <label>{copy.role}
              <select value={role} onChange={(event) => setRole(event.target.value as SeatRole)}>
                <option value="player">{copy.player}</option>
                <option value="spectator">{copy.spectator}</option>
                {isOwner ? <option value="dm">{copy.dm}</option> : null}
              </select>
            </label>
            <label>{copy.label}<input value={label} onChange={(event) => setLabel(event.target.value)} /></label>
            <button className="button primary" disabled={pending} type="submit">{copy.createSeat}</button>
          </form>
        ) : null}

        <div className="workshop-list">
          {snapshot.seats.length === 0 ? <p>{copy.noSeats}</p> : snapshot.seats.map((seat) => {
            const canManageSeat = seat.role === 'dm' ? isOwner : canManage
            const unavailableCharacterIds = selectedElsewhere(seat)
            const choices = eligibleCharacters.filter((item) => !unavailableCharacterIds.has(item.id))
            const controllerChoices = seat.role === 'dm'
              ? snapshot.controllers.filter((item) => item.authority === 'dm' || item.authority === 'owner')
              : snapshot.controllers
            return (
              <article className="workshop-card" key={seat.id}>
                <h2>{seat.label || (seat.role === 'dm' ? copy.dm : seat.role === 'player' ? copy.player : copy.spectator)}</h2>
                <p>{copy.role}: {seat.role === 'dm' ? copy.dm : seat.role === 'player' ? copy.player : copy.spectator}</p>
                <p>
                  {copy.controller}: {seat.controller_display_name || copy.unassigned}
                  {seat.controller_kind === 'human' ? ` · ${seat.presence === 'connected' ? copy.connected : copy.offline}` : ''}
                </p>
                {canManageSeat ? (
                  <label>{copy.controller}
                    <select
                      disabled={pending}
                      value={seat.controller_access_session_id ?? ''}
                      onChange={(event) => mutate(() => setSeatController(
                        roomId,
                        campaignId,
                        seat.id,
                        token,
                        event.target.value
                          ? { controller_kind: 'human', controller_access_session_id: event.target.value }
                          : { controller_kind: 'none', controller_access_session_id: null },
                      ))}
                    >
                      <option value="">{copy.unassigned}</option>
                      {controllerChoices.map((controller) => (
                        <option key={controller.access_session_id} value={controller.access_session_id}>
                          {controller.display_name || controller.access_session_id} · {controller.presence === 'connected' ? copy.connected : copy.offline}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                {seat.role === 'player' ? (
                  canOperateCharacter(seat) ? (
                    <label>{copy.character}
                      <select
                        disabled={pending}
                        value={seat.selected_character_id ?? ''}
                        onChange={(event) => mutate(() => setSeatCharacter(
                          roomId,
                          campaignId,
                          seat.id,
                          token,
                          event.target.value || null,
                        ))}
                      >
                        <option value="">{copy.noCharacter}</option>
                        {choices.map((character) => (
                          <option value={character.id} key={character.id}>{character.name}</option>
                        ))}
                      </select>
                    </label>
                  ) : <p>{copy.character}: {selectedCharacterName(seat)}</p>
                ) : null}
                {canManageSeat ? (
                  <div className="workshop-card__split-actions">
                    <button
                      className="button secondary"
                      disabled={pending}
                      type="button"
                      onClick={() => mutate(() => archiveSeat(roomId, campaignId, seat.id, token))}
                    >{copy.archive}</button>
                    <button
                      className="button danger"
                      disabled={pending}
                      type="button"
                      onClick={() => {
                        if (!window.confirm(copy.removeConfirm)) return
                        mutate(() => deleteSeat(roomId, campaignId, seat.id, token))
                      }}
                    >{copy.remove}</button>
                  </div>
                ) : null}
              </article>
            )
          })}
        </div>
        <p>{copy.aiReserved}</p>
      </section>
    </main>
  )
}
