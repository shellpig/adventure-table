import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'

import type { RoomCharacterSummary } from '../../api/campaigns'
import { createPendingAction } from '../../api/p3c'
import type { CampaignSeat } from '../../api/seats'
import {
  SessionApiError,
  getSessionStageImage,
  replaceSessionStage,
  sendExplorationInput,
  type ExplorationInputKind,
  type SessionSnapshot,
  type StageImageUpload,
  type StageState,
  type TableEvent,
} from '../../api/sessions'
import { SessionCheckRequestPanel } from './SessionCheckRequestPanel'
import { SessionQuickDicePanel } from './SessionQuickDicePanel'
import { SessionRollRequestList } from './SessionRollRequestList'
import {
  applyStageEvents,
  explorationEventText,
  isExplorationEvent,
  parseExplorationComposer,
} from './sessionExploration'
import {
  checkIntentDisposition,
  type CheckIntent,
} from './sessionCheckIntent'
import {
  MAX_SIDE_PANEL_WIDTH,
  MIN_SIDE_PANEL_WIDTH,
  clampSidePanelWidth,
  readSidePanelWidth,
  resolveKeyboardSidePanelWidth,
  writeSidePanelWidth,
} from './sessionTableLayout'
import type { SessionCopy } from './sessionCopy'
import {
  CHAT_COLOR_PALETTE,
  DEFAULT_CHAT_COLOR,
  readSpeakerColors,
  writeSpeakerColor,
} from './chatColors'
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
type SessionLayoutStyle = CSSProperties & { '--session-side-width': string }

function requestId(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.()
  return random ? `${prefix}-${random}` : `${prefix}-${Date.now()}-${Math.random()}`
}

async function fileUpload(file: File): Promise<StageImageUpload> {
  const mediaType = file.type
  if (mediaType !== 'image/png' && mediaType !== 'image/jpeg' && mediaType !== 'image/webp') {
    throw new SessionApiError(
      422,
      'invalid_stage_image',
      'Stage image must be PNG, JPEG, or WebP.',
    )
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

function getSpeakerKey(event: TableEvent, dmSeatId?: string | null): string {
  if (event.kind === 'exploration.narration') return 'dm'
  if (event.acting_seat_id && dmSeatId && event.acting_seat_id === dmSeatId && !event.subject_seat_id) return 'dm'
  return event.subject_seat_id ?? event.acting_seat_id ?? 'dm'
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
  const [checkDraft, setCheckDraft] = useState<CheckIntent | null>(null)
  const [sidePanelWidth, setSidePanelWidth] = useState(() => readSidePanelWidth())
  const layoutRef = useRef<HTMLDivElement>(null)
  const [speakerColors, setSpeakerColors] = useState<Record<string, string>>(() => readSpeakerColors())
  const [colorPickerOpen, setColorPickerOpen] = useState(false)
  const [colorPickerSpeakerKey, setColorPickerSpeakerKey] = useState<string | null>(null)
  const colorPickerRef = useRef<HTMLDivElement>(null)

  const callerSeatId = useMemo(() => {
    if (isCurrentDm) return snapshot.dm_seat_id
    if (callerAccessSessionId) {
      const match = snapshot.participants.find(
        (p) => p.controller_access_session_id_at_join === callerAccessSessionId,
      )
      if (match) return match.seat_id
      const seatMatch = seats.find(
        (s) => s.controller_access_session_id === callerAccessSessionId,
      )
      if (seatMatch) return seatMatch.id
    }
    return null
  }, [isCurrentDm, snapshot.dm_seat_id, snapshot.participants, seats, callerAccessSessionId])

  const fallbackSpeakerKey = isCurrentDm ? 'dm' : (callerSeatId || 'dm')
  const activeSpeakerKey = composerKind === 'narration' ? 'dm' : (subjectSeatId || fallbackSpeakerKey)
  const activeTargetSpeakerKey = colorPickerSpeakerKey || activeSpeakerKey
  const activeColor = speakerColors[activeTargetSpeakerKey] || DEFAULT_CHAT_COLOR

  const handleSelectColor = (color: string) => {
    const targetKey = colorPickerSpeakerKey || activeSpeakerKey
    writeSpeakerColor(targetKey, color)
    setSpeakerColors((prev) => ({ ...prev, [targetKey]: color }))
    setColorPickerOpen(false)
    setColorPickerSpeakerKey(null)
  }

  useEffect(() => {
    if (!colorPickerOpen) return
    const handleClickOutside = (event: MouseEvent) => {
      if (colorPickerRef.current && !colorPickerRef.current.contains(event.target as Node)) {
        setColorPickerOpen(false)
        setColorPickerSpeakerKey(null)
      }
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setColorPickerOpen(false)
        setColorPickerSpeakerKey(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [colorPickerOpen])

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
  const controlledParticipants = useMemo(
    () => playerParticipants.filter(
      (participant) => callerAccessSessionId !== null &&
        participant.controller_access_session_id_at_join === callerAccessSessionId,
    ),
    [playerParticipants, callerAccessSessionId],
  )
  const subjectParticipants = useMemo(
    () => isCurrentDm ? playerParticipants : controlledParticipants,
    [playerParticipants, controlledParticipants, isCurrentDm],
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
  const speakerLabel = (event: TableEvent) => {
    if (event.kind === 'exploration.narration') return copy.dm
    const speakerSeatId = event.subject_seat_id ?? event.acting_seat_id
    return speakerSeatId ? seatLabel(speakerSeatId) : copy.ooc
  }

  const explorationEvents = useMemo(
    () => events.filter(isExplorationEvent).slice(-100),
    [events],
  )

  const applySidePanelWidth = (nextWidth: number) => {
    setSidePanelWidth(nextWidth)
    writeSidePanelWidth(nextWidth)
  }

  const resizeFromPointer = (clientX: number) => {
    const layout = layoutRef.current
    if (!layout) return
    const bounds = layout.getBoundingClientRect()
    applySidePanelWidth(clampSidePanelWidth(bounds.right - clientX, bounds.width))
  }

  const resizeFromKeyboard = (key: string): boolean => {
    const layout = layoutRef.current
    if (!layout) return false
    const nextWidth = resolveKeyboardSidePanelWidth(
      sidePanelWidth,
      key,
      layout.getBoundingClientRect().width,
    )
    if (nextWidth === null) return false
    applySidePanelWidth(nextWidth)
    return true
  }

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
    if (parsed.type === 'invalid') {
      setComposerHint(parsed.reason === 'missing_subject' ? copy.subjectRequired : copy.composerPlaceholder)
      return
    }
    if (parsed.type === 'check_intent') {
      const disposition = checkIntentDisposition(isCurrentDm, parsed)
      if (disposition.type === 'dm_request_check') {
        setCheckDraft(disposition.draft)
        setTab('dice')
        return
      }
      setComposerPending(true)
      try {
        await createPendingAction(
          roomId,
          campaignId,
          sessionId,
          {
            ...disposition.input,
            idempotency_key: requestId('check-intent'),
          },
          token,
        )
        setComposerText('')
        setComposerHint(copy.checkDeferred)
      } catch (cause) {
        onError(cause)
      } finally {
        setComposerPending(false)
      }
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

  const layoutStyle: SessionLayoutStyle = {
    '--session-side-width': `${sidePanelWidth}px`,
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

      <div ref={layoutRef} className="session-table__layout" style={layoutStyle}>
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

        <div
          className="session-table__divider"
          role="separator"
          tabIndex={0}
          aria-orientation="vertical"
          aria-label={`${copy.mainStage} / ${copy.chat}`}
          aria-valuemin={MIN_SIDE_PANEL_WIDTH}
          aria-valuemax={MAX_SIDE_PANEL_WIDTH}
          aria-valuenow={Math.round(sidePanelWidth)}
          onKeyDown={(event) => {
            if (resizeFromKeyboard(event.key)) event.preventDefault()
          }}
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId)
            resizeFromPointer(event.clientX)
          }}
          onPointerMove={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) {
              resizeFromPointer(event.clientX)
            }
          }}
          onPointerUp={(event) => event.currentTarget.releasePointerCapture(event.pointerId)}
        />

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
                {explorationEvents.map((event) => {
                  const speakerKey = getSpeakerKey(event, snapshot.dm_seat_id)
                  const speakerColor = speakerColors[speakerKey]
                  return (
                    <article className="session-chat__message" key={`${event.session_id}:${event.seq}`}>
                      <header>
                        <button
                          type="button"
                          className="session-chat__color-dot-btn"
                          style={{ backgroundColor: speakerColor || DEFAULT_CHAT_COLOR }}
                          title={`${speakerLabel(event)}: ${copy.selectChatColor}`}
                          aria-label={`${speakerLabel(event)}: ${copy.selectChatColor}`}
                          onClick={() => {
                            setColorPickerSpeakerKey(speakerKey)
                            setColorPickerOpen(true)
                          }}
                        />
                        <strong style={speakerColor ? { color: speakerColor } : undefined}>
                          {speakerLabel(event)}
                        </strong>
                        {event.kind === 'exploration.ooc' ? <span>{copy.ooc}</span> : null}
                        {event.execution_mode === 'dm_proxy' ? <span>{copy.dmProxy}</span> : null}
                        {event.kind === 'exploration.whisper_dm' ? <span>{copy.whisperPrivate}</span> : null}
                      </header>
                      <p style={speakerColor ? { color: speakerColor } : undefined}>{explorationEventText(event)}</p>
                    </article>
                  )
                })}
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
                      onChange={(event) => {
                        setSubjectSeatId(event.target.value)
                        setColorPickerSpeakerKey(null)
                      }}
                    >
                      <option value="">—</option>
                      {subjectParticipants.map((participant) => (
                        <option key={participant.seat_id} value={participant.seat_id}>
                          {seatLabel(participant.seat_id)} · {characterName(participant.active_character_id)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="session-composer__color-wrap" ref={colorPickerRef}>
                    <label>
                      <span>{copy.chatTextColor}</span>
                      <button
                        type="button"
                        className="session-composer__color-btn"
                        onClick={() => {
                          setColorPickerSpeakerKey(null)
                          setColorPickerOpen(!colorPickerOpen)
                        }}
                        title={copy.selectChatColor}
                        aria-label={copy.selectChatColor}
                      >
                        <span
                          className="session-composer__color-swatch-sample"
                          style={{ backgroundColor: activeColor }}
                        />
                      </button>
                    </label>

                    {colorPickerOpen ? (
                      <div className="session-color-picker-popover" role="dialog" aria-label={copy.selectChatColor}>
                        <div className="session-color-picker-header">
                          <span>{copy.selectChatColor}</span>
                          <button
                            type="button"
                            className="session-color-picker-close"
                            onClick={() => {
                              setColorPickerOpen(false)
                              setColorPickerSpeakerKey(null)
                            }}
                            aria-label={copy.close}
                          >×</button>
                        </div>
                        <div className="session-color-picker-grid">
                          {CHAT_COLOR_PALETTE.map((item) => (
                            <button
                              key={item.value}
                              type="button"
                              className={`session-color-palette-item ${activeColor === item.value ? 'selected' : ''}`}
                              style={{ backgroundColor: item.value }}
                              title={item.label[copy.locale]}
                              aria-label={item.label[copy.locale]}
                              onClick={() => handleSelectColor(item.value)}
                            >
                              {activeColor === item.value ? (
                                <span className="session-color-palette-check">✓</span>
                              ) : null}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
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
            <div className="session-dice-panel">
              {isCurrentDm ? (
                <SessionCheckRequestPanel
                  roomId={roomId}
                  campaignId={campaignId}
                  sessionId={sessionId}
                  token={token}
                  targets={playerParticipants.map((participant) => ({
                    seatId: participant.seat_id,
                    label: `${seatLabel(participant.seat_id)} · ${characterName(participant.active_character_id)}`,
                  }))}
                  intent={checkDraft}
                  copy={copy}
                  onError={onError}
                />
              ) : <p>{copy.dicePlaceholder}</p>}
              <SessionRollRequestList
                roomId={roomId}
                campaignId={campaignId}
                sessionId={sessionId}
                token={token}
                isCurrentDm={isCurrentDm}
                controlledSeatIds={controlledParticipants.map((participant) => participant.seat_id)}
                events={events}
                copy={copy}
                onError={onError}
              />
              <SessionQuickDicePanel
                roomId={roomId}
                campaignId={campaignId}
                sessionId={sessionId}
                token={token}
                targets={controlledParticipants.map((participant) => ({
                  seatId: participant.seat_id,
                  label: `${seatLabel(participant.seat_id)} · ${characterName(participant.active_character_id)}`,
                }))}
                copy={copy}
                onError={onError}
              />
            </div>
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
