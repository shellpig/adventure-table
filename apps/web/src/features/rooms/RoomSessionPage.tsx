import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'

import { listRoomCharacters, type RoomCharacterSummary } from '../../api/campaigns'
import { heartbeatRoom } from '../../api/rooms'
import { getLobby, type CampaignSeat, type LobbySnapshot } from '../../api/seats'
import {
  abandonSession,
  endSession,
  getActiveSession,
  getSession,
  lateJoinSession,
  waitSessionEvents,
  type SessionSnapshot,
  type StageState,
} from '../../api/sessions'
import { useLocale } from '../../i18n/LocaleProvider'
import { startRoomHeartbeat } from './heartbeat'
import { PlayerAIControlPanel } from './PlayerAIControlPanel'
import { recentRoomForId } from './roomStorage'
import {
  runSessionEventPoll,
  type SessionEventConnectionStatus,
} from './sessionEventPoll'
import {
  applySessionEventPage,
  eventStreamFromResume,
  mergeResumeStream,
  type SessionEventStreamState,
} from './sessionEventStream'
import { SessionTableSurface } from './SessionTableSurface'
import {
  clampCardWidth,
  DEFAULT_CARD_WIDTH,
  MAX_CARD_WIDTH,
  MIN_CARD_WIDTH,
  readCardWidth,
  resolveKeyboardCardWidth,
  toggleCardWidth,
  writeCardWidth,
} from './sessionTableLayout'
import { sessionCopy, sessionErrorMessage, type SessionCopy } from './sessionCopy'
import './rooms.css'

const UUID_PATTERN = '[0-9a-fA-F-]{36}'

export type RoomSessionRoute = { roomId: string; campaignId: string; sessionId: string }

export function roomSessionRouteFromPath(pathname: string): RoomSessionRoute | null {
  const match = pathname.match(
    new RegExp(
      `^/rooms/(${UUID_PATTERN})/campaigns/(${UUID_PATTERN})/sessions/(${UUID_PATTERN})/?$`,
    ),
  )
  return match ? { roomId: match[1], campaignId: match[2], sessionId: match[3] } : null
}

export function mergeSessionSeatTruth(
  lobbySeats: CampaignSeat[],
  resumeSeats: CampaignSeat[],
): CampaignSeat[] {
  const byId = new Map(resumeSeats.map((seat) => [seat.id, seat]))
  for (const seat of lobbySeats) byId.set(seat.id, seat)
  return [...byId.values()]
}

export function sessionTableSnapshotWithCurrentControllers(
  snapshot: SessionSnapshot,
  seats: CampaignSeat[],
): SessionSnapshot {
  const currentBySeat = new Map(seats.map((seat) => [seat.id, seat]))
  return {
    ...snapshot,
    participants: snapshot.participants.map((participant) => {
      const seat = currentBySeat.get(participant.seat_id)
      return {
        ...participant,
        controller_access_session_id_at_join: seat?.controller_kind === 'human'
          ? seat.controller_access_session_id
          : null,
      }
    }),
  }
}

export function SessionEventConnectionBanner({
  status,
  copy,
}: {
  status: SessionEventConnectionStatus
  copy: SessionCopy
}) {
  if (status === 'connected') return null
  const reconnecting = status === 'reconnecting'
  const message = reconnecting ? copy.eventReconnecting : copy.eventDisconnected
  return (
    <div
      className={reconnecting ? 'notice-banner' : 'error-banner'}
      role={reconnecting ? 'status' : 'alert'}
      data-session-event-connection={status}
    >
      {message}
    </div>
  )
}

export function RoomSessionPage({ roomId, campaignId, sessionId }: RoomSessionRoute) {
  const { locale } = useLocale()
  const copy = sessionCopy(locale)
  const recent = recentRoomForId(roomId)
  const token = recent?.accessToken ?? ''
  const [snapshot, setSnapshot] = useState<SessionSnapshot | null>(null)
  const [lobby, setLobby] = useState<LobbySnapshot | null>(null)
  const [resumeSeats, setResumeSeats] = useState<CampaignSeat[]>([])
  const [callerAccessSessionId, setCallerAccessSessionId] = useState<string | null>(null)
  const [selfTakeBackSeatIds, setSelfTakeBackSeatIds] = useState<Set<string>>(() => new Set())
  const [characters, setCharacters] = useState<RoomCharacterSummary[]>([])
  const [initialStage, setInitialStage] = useState<StageState | null>(null)
  const [eventStream, setEventStream] = useState<SessionEventStreamState | null>(null)
  const [eventConnectionStatus, setEventConnectionStatus] = useState<SessionEventConnectionStatus>('connected')
  const [lateJoinSeatId, setLateJoinSeatId] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cardWidth, setCardWidth] = useState(() => readCardWidth())
  const cardRef = useRef<HTMLElement | null>(null)

  const applyCardWidth = (nextWidth: number) => {
    setCardWidth(nextWidth)
    writeCardWidth(nextWidth)
  }

  const resizeCardFromPointer = (clientX: number, side: 'left' | 'right') => {
    const card = cardRef.current
    if (!card) return
    const rect = card.getBoundingClientRect()
    const centerX = rect.left + rect.width / 2
    const targetWidth = side === 'right'
      ? (clientX - centerX) * 2
      : (centerX - clientX) * 2
    const viewportWidth = typeof window !== 'undefined' ? window.innerWidth : undefined
    applyCardWidth(clampCardWidth(targetWidth, viewportWidth))
  }

  const resizeCardFromKeyboard = (key: string): boolean => {
    const viewportWidth = typeof window !== 'undefined' ? window.innerWidth : undefined
    const nextWidth = resolveKeyboardCardWidth(cardWidth, key, viewportWidth)
    if (nextWidth === null) return false
    applyCardWidth(nextWidth)
    return true
  }

  const handleToggleCardWidth = () => {
    const viewportWidth = typeof window !== 'undefined' ? window.innerWidth : undefined
    applyCardWidth(toggleCardWidth(cardWidth, viewportWidth))
  }

  const handleCardPointerDown = (
    event: React.PointerEvent<HTMLDivElement>,
    side: 'left' | 'right',
  ) => {
    if (event.button !== 0) return
    event.currentTarget.setPointerCapture(event.pointerId)
    resizeCardFromPointer(event.clientX, side)
  }

  const handleCardPointerMove = (
    event: React.PointerEvent<HTMLDivElement>,
    side: 'left' | 'right',
  ) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      resizeCardFromPointer(event.clientX, side)
    }
  }

  const handleCardPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  const reloadGeneration = useRef(0)
  const handleSessionTableError = useCallback(
    (cause: unknown) => setError(sessionErrorMessage(cause, copy)),
    [copy],
  )

  const optionalLobby = (): Promise<LobbySnapshot | null> =>
    getLobby(roomId, campaignId, token).catch(() => null)

  const reload = async () => {
    const generation = reloadGeneration.current + 1
    reloadGeneration.current = generation
    const [nextSession, nextLobby, nextCharacters, nextResume] = await Promise.all([
      getSession(roomId, campaignId, sessionId, token),
      optionalLobby(),
      listRoomCharacters(roomId, token),
      getActiveSession(roomId, campaignId, token),
    ])
    if (generation !== reloadGeneration.current) return
    setSnapshot(nextSession)
    setLobby(nextLobby)
    setCharacters(nextCharacters)
    setCallerAccessSessionId(nextResume.caller_access_session_id)
    setSelfTakeBackSeatIds(new Set(nextResume.self_take_back_seat_ids ?? []))
    setResumeSeats(nextResume.active_session?.id === sessionId ? nextResume.seats : [])
    setInitialStage(nextResume.active_session?.id === sessionId ? (nextResume.stage ?? null) : null)
    setEventStream((current) => mergeResumeStream(
      current,
      nextResume.active_session?.id === sessionId
        ? eventStreamFromResume(nextResume)
        : null,
    ))
  }

  useEffect(() => {
    if (!recent) return
    let active = true
    void reload().catch((cause) => {
      if (active) setError(sessionErrorMessage(cause, copy))
    })
    const stopHeartbeat = startRoomHeartbeat(async () => {
      try {
        await heartbeatRoom(roomId, token)
        const [nextSession, nextLobby] = await Promise.all([
          getSession(roomId, campaignId, sessionId, token),
          optionalLobby(),
        ])
        if (active) {
          setSnapshot(nextSession)
          setLobby(nextLobby)
        }
      } catch (cause) {
        if (active) setError(sessionErrorMessage(cause, copy))
      }
    })
    return () => {
      active = false
      stopHeartbeat()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, campaignId, sessionId, token])

  const eventStreamReady = eventStream !== null
  useEffect(() => {
    if (!recent || !eventStreamReady || snapshot?.status !== 'active') return

    const controller = new AbortController()
    setEventConnectionStatus('connected')

    void runSessionEventPoll({
      initialCursor: eventStream?.cursor ?? 0,
      signal: controller.signal,
      wait: (cursor, signal) => waitSessionEvents(
        roomId,
        campaignId,
        sessionId,
        cursor,
        token,
        { limit: 100, timeout: 30, signal },
      ),
      onPage: (page) => {
        setEventStream((current) => current ? applySessionEventPage(current, page) : current)
      },
      onStatus: setEventConnectionStatus,
      onFatal: () => undefined,
    })

    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, campaignId, sessionId, token, eventStreamReady, snapshot?.status])

  const participantSeatIds = useMemo(
    () => new Set(snapshot?.participants.map((participant) => participant.seat_id) ?? []),
    [snapshot],
  )
  const lateJoinSeats = useMemo(
    () => lobby?.seats.filter((seat) => (
      seat.role === 'player' &&
      seat.selected_character_id !== null &&
      !participantSeatIds.has(seat.id)
    )) ?? [],
    [lobby, participantSeatIds],
  )
  const sessionSeats = useMemo(
    () => mergeSessionSeatTruth(lobby?.seats ?? [], resumeSeats),
    [lobby, resumeSeats],
  )

  const mutate = (operation: () => Promise<SessionSnapshot>) => {
    setPending(true)
    setError(null)
    void operation()
      .then((next) => {
        setSnapshot(next)
        setLateJoinSeatId('')
        return reload()
      })
      .catch((cause) => setError(sessionErrorMessage(cause, copy)))
      .finally(() => setPending(false))
  }

  if (!recent) {
    return (
      <main className="landing-page room-workspace-page">
        <section className="landing-card room-workspace-card">
          <h1>{copy.title}</h1>
          <p>{copy.missingAccess}</p>
          <a className="button secondary" href="/">{copy.backLobby}</a>
        </section>
      </main>
    )
  }

  if (!snapshot) {
    return (
      <main className="landing-page"><section className="landing-card">
        <h1>{copy.title}</h1>
        {error ? <div className="error-banner">{error}</div> : null}
        <a className="button secondary" href={`/rooms/${roomId}/campaigns/${campaignId}/lobby`}>
          {copy.backLobby}
        </a>
      </section></main>
    )
  }

  const isCurrentDm = (
    snapshot.status === 'active' &&
    snapshot.dm_controller_access_session_id !== null &&
    snapshot.dm_controller_access_session_id === callerAccessSessionId
  )
  const isOwner = recent.authority === 'owner'
  const canManage = recent.authority === 'owner' || recent.authority === 'dm'
  const canAbandon = snapshot.status === 'active' && (isCurrentDm || isOwner)
  const statusLabel = snapshot.status === 'active'
    ? copy.active
    : snapshot.status === 'ended'
      ? copy.ended
      : copy.abandoned
  const characterName = (characterId: string | null) =>
    characters.find((character) => character.id === characterId)?.name ?? copy.noCharacter
  const seatLabel = (seatId: string) => {
    const seat = sessionSeats.find((item) => item.id === seatId)
    if (!seat) return seatId
    return seat.label || (seat.role === 'dm' ? copy.dm : seat.role === 'player' ? copy.player : copy.spectator)
  }
  const tableSnapshot = sessionTableSnapshotWithCurrentControllers(snapshot, sessionSeats)

  return (
    <main className="landing-page room-workspace-page">
      <section
        ref={cardRef}
        className="landing-card room-workspace-card session-table-card"
        style={{ '--session-card-width': `${cardWidth}px` } as CSSProperties}
      >
        <div
          className="session-table-card__resize-handle session-table-card__resize-handle--left"
          role="separator"
          tabIndex={0}
          aria-orientation="vertical"
          aria-label={copy.resizeCard}
          title={copy.resizeCardHint}
          aria-valuemin={MIN_CARD_WIDTH}
          aria-valuemax={MAX_CARD_WIDTH}
          aria-valuenow={Math.round(cardWidth)}
          onPointerDown={(event) => handleCardPointerDown(event, 'left')}
          onPointerMove={(event) => handleCardPointerMove(event, 'left')}
          onPointerUp={handleCardPointerUp}
          onDoubleClick={handleToggleCardWidth}
          onKeyDown={(event) => {
            if (resizeCardFromKeyboard(event.key)) event.preventDefault()
          }}
        />
        <div
          className="session-table-card__resize-handle session-table-card__resize-handle--right"
          role="separator"
          tabIndex={0}
          aria-orientation="vertical"
          aria-label={copy.resizeCard}
          title={copy.resizeCardHint}
          aria-valuemin={MIN_CARD_WIDTH}
          aria-valuemax={MAX_CARD_WIDTH}
          aria-valuenow={Math.round(cardWidth)}
          onPointerDown={(event) => handleCardPointerDown(event, 'right')}
          onPointerMove={(event) => handleCardPointerMove(event, 'right')}
          onPointerUp={handleCardPointerUp}
          onDoubleClick={handleToggleCardWidth}
          onKeyDown={(event) => {
            if (resizeCardFromKeyboard(event.key)) event.preventDefault()
          }}
        />
        <h1>{copy.title}</h1>
        <p>{copy.intro}</p>
        <p><strong>{statusLabel}</strong></p>
        <div className="workshop-card__split-actions">
          <a className="button secondary" href={`/rooms/${roomId}/campaigns/${campaignId}/lobby`}>
            {copy.backLobby}
          </a>
          <button
            type="button"
            className="button secondary session-table-card__width-toggle"
            onClick={handleToggleCardWidth}
            title={copy.resizeCardHint}
          >
            {cardWidth > DEFAULT_CARD_WIDTH + 60 ? copy.cardWidthDefault : copy.cardWidthExpand}
          </button>
        </div>
        {error ? <div className="error-banner">{error}</div> : null}
        {snapshot.status === 'active' ? (
          <SessionEventConnectionBanner status={eventConnectionStatus} copy={copy} />
        ) : null}

        {snapshot.status === 'active' ? (
          <SessionTableSurface
            roomId={roomId}
            campaignId={campaignId}
            sessionId={sessionId}
            token={token}
            snapshot={tableSnapshot}
            seats={sessionSeats}
            characters={characters}
            callerAccessSessionId={callerAccessSessionId}
            isCurrentDm={isCurrentDm}
            initialStage={initialStage}
            events={eventStream?.events ?? []}
            copy={copy}
            onError={handleSessionTableError}
          />
        ) : null}

        <h2>{copy.participants}</h2>
        <div className="workshop-list">
          {snapshot.participants.length === 0 ? <p>{copy.noParticipants}</p> : snapshot.participants.map((participant) => {
            const currentSeat = sessionSeats.find((item) => item.id === participant.seat_id)
            return (
              <article className="workshop-card" key={participant.id}>
                <h3>{seatLabel(participant.seat_id)}</h3>
                <p>
                  {participant.role === 'dm' ? copy.dm : participant.role === 'player' ? copy.player : copy.spectator}
                </p>
                {participant.role === 'player' ? <p>{characterName(participant.active_character_id)}</p> : null}
                {snapshot.status === 'active' && participant.role === 'player' && currentSeat ? (
                  <PlayerAIControlPanel
                    roomId={roomId}
                    campaignId={campaignId}
                    sessionId={sessionId}
                    seat={currentSeat}
                    roomToken={token}
                    callerAccessSessionId={callerAccessSessionId}
                    canSelfTakeBack={selfTakeBackSeatIds.has(currentSeat.id)}
                    canManage={canManage}
                    controllers={lobby?.controllers ?? []}
                    copy={copy}
                    onChanged={reload}
                  />
                ) : null}
              </article>
            )
          })}
        </div>

        {snapshot.status === 'active' && isCurrentDm ? (
          <section className="room-form">
            <h2>{copy.lateJoin}</h2>
            {lateJoinSeats.length === 0 ? <p>{copy.noLateJoinSeats}</p> : (
              <>
                <label>{copy.lateJoinSeat}
                  <select
                    disabled={pending}
                    value={lateJoinSeatId}
                    onChange={(event) => setLateJoinSeatId(event.target.value)}
                  >
                    <option value="">{copy.lateJoinSeat}</option>
                    {lateJoinSeats.map((seat) => (
                      <option value={seat.id} key={seat.id}>
                        {seatLabel(seat.id)} · {characterName(seat.selected_character_id)}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="button primary"
                  type="button"
                  disabled={pending || !lateJoinSeatId}
                  onClick={() => mutate(() => lateJoinSession(
                    roomId,
                    campaignId,
                    sessionId,
                    lateJoinSeatId,
                    token,
                  ))}
                >{copy.join}</button>
              </>
            )}
          </section>
        ) : null}

        {snapshot.status === 'active' ? <p>{copy.currentDmHint}</p> : null}
        {snapshot.status === 'active' && isOwner && !isCurrentDm ? <p>{copy.ownerAbandonHint}</p> : null}

        {snapshot.status === 'active' && (isCurrentDm || canAbandon) ? (
          <div className="workshop-card__split-actions">
            {isCurrentDm ? (
              <button
                className="button primary"
                disabled={pending}
                type="button"
                onClick={() => {
                  if (!window.confirm(copy.endConfirm)) return
                  mutate(() => endSession(roomId, campaignId, sessionId, token))
                }}
              >{copy.end}</button>
            ) : null}
            {canAbandon ? (
              <button
                className="button danger"
                disabled={pending}
                type="button"
                onClick={() => {
                  if (!window.confirm(copy.abandonConfirm)) return
                  mutate(() => abandonSession(roomId, campaignId, sessionId, token))
                }}
              >{copy.abandon}</button>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  )
}
