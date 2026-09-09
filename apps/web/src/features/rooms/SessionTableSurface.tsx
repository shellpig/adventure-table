import { useEffect, useMemo, useState } from 'react'

import type { RoomCharacterSummary } from '../../api/campaigns'
import type { CampaignSeat } from '../../api/seats'
import {
  getSessionStageImage,
  replaceSessionStage,
  sendExplorationInput,
  type ExplorationInputKind,
  type SessionSnapshot,
  type StageImageUpload,
  type StageState,
  type TableEvent,
} from '../../api/sessions'
import {
  applyStageEvents,
  explorationEventText,
  isExplorationEvent,
  parseExplorationComposer,
} from './sessionExploration'
import type { SessionCopy } from './sessionCopy'
import './sessionTable.css'


type SessionTableSurfaceProps = {
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  snapshot: SessionSnapshot
  seats: CampaignSeat[]
  characters: RoomCharacterSummary[]
  callerAccessSessionId: string | null
  isCurrentDm: boolean
  initialStage: StageState | null
  events: TableEvent[]
  copy: SessionCopy
  onError: (cause: unknown) => void
}

type TableTab = 'chat' | 'dice' | 'log'

function requestId(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.()
  return random ? `${prefix}-${random}` : `${prefix}-${Date.now()}-${Math.random()}`
}

async function fileUpload(file: File): Promise<StageImageUpload> {
  const mediaType = file.type
  if (mediaType !== 'image/png' && mediaType !== 'image/jpeg' && mediaType !== 'image/webp') {
    throw new Error('unsupported_stage_image')
  }
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error ?? new Error('stage_image_read_failed'))
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.readAsDataURL(file)
  })
  const comma = dataUrl.indexOf(',')
  if (comma < 0) throw new Error('stage_image_read_failed')
  return {
    media_type: mediaType,
    filename: file.name || null,
    data_base64: dataUrl.slice(comma + 1),
  }
}

export function SessionTableSurface({
  roomId,
  campaignId,
  sessionId,
  token,
  snapshot,
  seats,
  characters,
  callerAccessSessionId,
  isCurrentDm,
  initialStage,
  events,
  copy,
  onError,
}: SessionTableSurfaceProps) {
  const projectedStage = useMemo(
    () => applyStageEvents(initialStage, events),
    [initialStage, events],
  )
  const [stage, setStage] = useState<StageState | null>(projectedStage)
  const [stageText, setStageText] = useState(projectedStage?.text ?? '')
  const [stageFile, setStageFile] = useState<File | null>(null)
  const [stagePending, setStagePending] = useState(false)
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [tab, setTab] = useState<TableTab>('chat')
  const [composerKind, setComposerKind] = useState<ExplorationInputKind>('dialogue')
  const [subjectSeatId, setSubjectSeatId] = useState('')
  const [composerText, setComposerText] = useState('')
  const [composerPending, setComposerPending] = useState(false)
  const [composerHint, setComposerHint] = useState<string | null>(null)

  useEffect(() => {
    setStage(projectedStage)
    setStageText(projectedStage?.text ?? '')
  }, [projectedStage?.revision, projectedStage?.text, projectedStage?.image_id])

  useEffect(() => {
    const imageId = stage?.image_id
    if (!imageId) {
      setImageUrl(null)
      return
    }
    let active = true
    let objectUrl: string | null = null
    void getSessionStageImage(roomId, campaignId, sessionId, imageId, token)
      .then((blob) => {
        if (!active) return
        objectUrl = URL.createObjectURL(blob)
        setImageUrl(objectUrl)
      })
      .catch(onError)
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [roomId, campaignId, sessionId, stage?.image_id, token, onError])

  const playerParticipants = useMemo(
    () => snapshot.participants.filter(
      (participant) => participant.role === 'player' && participant.active_character_id !== null,
    ),
    [snapshot.participants],
  )
  const subjectParticipants = useMemo(
    () => playerParticipants.filter(
      (participant) => isCurrentDm || (
        callerAccessSessionId !== null &&
        participant.controller_access_session_id_at_join === callerAccessSessionId
      ),
    ),
    [playerParticipants, isCurrentDm, callerAccessSessionId],
  )

  useEffect(() => {
    if (subjectSeatId && subjectParticipants.some((item) => item.seat_id === subjectSeatId)) return
    setSubjectSeatId(subjectParticipants[0]?.seat_id ?? '')
  }, [subjectParticipants, subjectSeatId])

  const seatLabel = (seatId: string) => {
    const seat = seats.find((item) => item.id === seatId)
    return seat?.label || copy.player
  }
  const characterName = (characterId: string | null) =>
    characters.find((item) => item.id === characterId)?.name ?? copy.noCharacter

  const explorationEvents = useMemo(
    () => events.filter(isExplorationEvent).slice(-100),
    [events],
  )

  const saveStage = async (clear = false) => {
    setStagePending(true)
    try {
      const image = !clear && stageFile ? await fileUpload(stageFile) : null
      const expectedRevision = stage?.revision ?? 0
      const next = await replaceSessionStage(
        roomId,
        campaignId,
        sessionId,
        clear
          ? {
              expected_revision: expectedRevision,
              text: null,
              image_id: null,
              idempotency_key: requestId('stage-clear'),
            }
          : {
              expected_revision: expectedRevision,
              text: stageText.trim() || null,
              image_id: image ? null : (stage?.image_id ?? null),
              image,
              idempotency_key: requestId('stage-save'),
            },
        token,
      )
      setStage(next)
      setStageText(next.text ?? '')
      setStageFile(null)
    } catch (cause) {
      onError(cause)
    } finally {
      setStagePending(false)
    }
  }

  const send = async () => {
    setComposerHint(null)
    const parsed = parseExplorationComposer(
      composerText,
      composerKind,
      subjectSeatId || null,
    )
    if (parsed.type === 'blocked_check') {
      setComposerHint(copy.checkDeferred)
      return
    }
    if (parsed.type === 'invalid') {
      setComposerHint(parsed.reason === 'missing_subject' ? copy.subjectRequired : copy.composerPlaceholder)
      return
    }
    setComposerPending(true)
    try {
      await sendExplorationInput(
        roomId,
        campaignId,
        sessionId,
        { ...parsed.request, idempotency_key: requestId('input') },
        token,
      )
      setComposerText('')
    } catch (cause) {
      onError(cause)
    } finally {
      setComposerPending(false)
    }
  }

  return (
    <section className="session-table" data-session-table="true">
      <div className="session-table__characters" aria-label={copy.tableCharacters}>
        <strong>{copy.tableCharacters}</strong>
        {playerParticipants.map((participant) => (
          <span className="session-table__character-chip" key={participant.id}>
            {seatLabel(participant.seat_id)} · {characterName(participant.active_character_id)}
          </span>
        ))}
      </div>

      <div className="session-table__layout">
        <section className="session-stage" aria-label={copy.mainStage}>
          <header><h2>{copy.mainStage}</h2></header>
          <div className="session-stage__canvas">
            {imageUrl ? <img src={imageUrl} alt={stage?.image_filename || copy.mainStage} /> : null}
            {stage?.text ? <p>{stage.text}</p> : null}
            {!stage?.text && !stage?.image_id ? <p className="session-stage__empty">{copy.stageEmpty}</p> : null}
          </div>

          {isCurrentDm ? (
            <div className="session-stage__editor">
              <label>
                <span>{copy.stageTextLabel}</span>
                <textarea
                  value={stageText}
                  maxLength={12000}
                  disabled={stagePending}
                  onChange={(event) => setStageText(event.target.value)}
                />
              </label>
              <label>
                <span>{copy.stageImageLabel}</span>
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  disabled={stagePending}
                  onChange={(event) => setStageFile(event.target.files?.[0] ?? null)}
                />
              </label>
              <div className="session-stage__actions">
                <button className="button primary" type="button" disabled={stagePending} onClick={() => void saveStage(false)}>
                  {stagePending ? copy.stageSaving : copy.stageSave}
                </button>
                <button className="button secondary" type="button" disabled={stagePending} onClick={() => void saveStage(true)}>
                  {copy.stageClear}
                </button>
              </div>
            </div>
          ) : null}
        </section>

        <aside className="session-side-panel">
          <nav className="session-side-panel__tabs" aria-label={copy.chat}>
            {(['chat', 'dice', 'log'] as const).map((nextTab) => (
              <button
                type="button"
                key={nextTab}
                className={tab === nextTab ? 'active' : ''}
                onClick={() => setTab(nextTab)}
              >
                {nextTab === 'chat' ? copy.chat : nextTab === 'dice' ? copy.dice : copy.log}
              </button>
            ))}
          </nav>

          {tab === 'chat' ? (
            <div className="session-chat">
              <div className="session-chat__messages" aria-live="polite">
                {explorationEvents.length === 0 ? <p className="session-stage__empty">{copy.noMessages}</p> : null}
                {explorationEvents.map((event) => (
                  <article className="session-chat__message" key={`${event.session_id}:${event.seq}`}>
                    <header>
                      <strong>{event.subject_seat_id ? seatLabel(event.subject_seat_id) : event.kind === 'exploration.narration' ? copy.dm : copy.ooc}</strong>
                      {event.execution_mode === 'dm_proxy' ? <span>{copy.dmProxy}</span> : null}
                      {event.kind === 'exploration.whisper_dm' ? <span>{copy.whisperPrivate}</span> : null}
                    </header>
                    <p>{explorationEventText(event)}</p>
                  </article>
                ))}
              </div>

              <div className="session-composer">
                <div className="session-composer__row">
                  <label>
                    <span>{copy.composerKind}</span>
                    <select value={composerKind} onChange={(event) => setComposerKind(event.target.value as ExplorationInputKind)}>
                      <option value="dialogue">{copy.dialogue}</option>
                      <option value="action">{copy.action}</option>
                      <option value="ooc">{copy.ooc}</option>
                      <option value="whisper_dm">{copy.whisper}</option>
                      {isCurrentDm ? <option value="narration">{copy.narration}</option> : null}
                    </select>
                  </label>
                  <label>
                    <span>{copy.composerSubject}</span>
                    <select
                      value={subjectSeatId}
                      disabled={subjectParticipants.length === 0}
                      onChange={(event) => setSubjectSeatId(event.target.value)}
                    >
                      <option value="">—</option>
                      {subjectParticipants.map((participant) => (
                        <option key={participant.seat_id} value={participant.seat_id}>
                          {seatLabel(participant.seat_id)} · {characterName(participant.active_character_id)}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <textarea
                  value={composerText}
                  disabled={composerPending}
                  placeholder={copy.composerPlaceholder}
                  onChange={(event) => setComposerText(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      void send()
                    }
                  }}
                />
                {composerHint ? <p className="session-composer__hint">{composerHint}</p> : null}
                <button className="button primary" type="button" disabled={composerPending} onClick={() => void send()}>
                  {composerPending ? copy.sending : copy.send}
                </button>
              </div>
            </div>
          ) : tab === 'dice' ? (
            <div className="session-side-panel__placeholder"><p>{copy.dicePlaceholder}</p></div>
          ) : (
            <div className="session-log">
              {events.slice(-100).map((event) => (
                <p key={`log:${event.session_id}:${event.seq}`}><code>#{event.seq}</code> {event.kind}</p>
              ))}
            </div>
          )}
        </aside>
      </div>
    </section>
  )
}
