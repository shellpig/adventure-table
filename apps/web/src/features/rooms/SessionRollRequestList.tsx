import { useEffect, useMemo, useState } from 'react'

import {
  listRollRequests,
  submitFormalRoll,
  type FormalRollSource,
  type RollModifierMode,
  type RollRequestView,
  type RollSubmissionResponse,
} from '../../api/p3c'
import type { TableEvent } from '../../api/sessions'
import type { SessionCopy } from './sessionCopy'
import { formatModifierMode, formatRequestType, formatTargetRef } from './sessionRollPresentation'

export function visibleRollResultTotal(
  requestId: string,
  events: TableEvent[],
): number | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (event.kind !== 'roll.resolved' || event.payload.roll_request_id !== requestId) continue
    return typeof event.payload.total === 'number' ? event.payload.total : null
  }
  return null
}

export function parsePhysicalD20(
  mode: RollModifierMode,
  raw: string,
): number[] | null {
  const values = raw.trim().split(/[\s,]+/).filter(Boolean).map(Number)
  const required = mode === 'normal' ? 1 : 2
  if (values.length !== required) return null
  if (values.some((value) => !Number.isInteger(value) || value < 1 || value > 20)) return null
  return values
}

function statusLabel(request: RollRequestView, copy: SessionCopy): string {
  if (request.status === 'pending') return copy.rollPending
  if (request.status === 'resolved') return copy.rollResolved
  return copy.rollCancelled
}

export function SessionRollRequestList({
  roomId,
  campaignId,
  sessionId,
  token,
  isCurrentDm,
  controlledSeatIds,
  events,
  copy,
  onError,
  initialRequests = [],
}: {
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  isCurrentDm: boolean
  controlledSeatIds: string[]
  events: TableEvent[]
  copy: SessionCopy
  onError: (cause: unknown) => void
  initialRequests?: RollRequestView[]
}) {
  const [requests, setRequests] = useState<RollRequestView[]>(initialRequests)
  const [submissions, setSubmissions] = useState<Record<string, RollSubmissionResponse>>({})
  const [rollingKey, setRollingKey] = useState<string | null>(null)
  const [physicalDice, setPhysicalDice] = useState<Record<string, string>>({})

  const rollEventSeq = useMemo(
    () => events.reduce((latest, event) => event.kind.startsWith('roll.') ? Math.max(latest, event.seq) : latest, 0),
    [events],
  )

  const refresh = async () => {
    const next = await listRollRequests(roomId, campaignId, sessionId, token)
    setRequests(next)
  }

  useEffect(() => {
    void refresh().catch(onError)
    // A visible roll event is a durable wake-up hint; canonical RollRequest rows
    // remain the status SSOT after reconnect/reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, campaignId, sessionId, token, rollEventSeq])

  const roll = async (
    request: RollRequestView,
    source: FormalRollSource,
    rawDice?: number[],
  ) => {
    const rollingKey = `${request.id}:${source}`
    setRollingKey(rollingKey)
    try {
      const submission = await submitFormalRoll(roomId, campaignId, sessionId, {
        roll_request_id: request.id,
        source,
        raw_dice: source === 'physical' ? rawDice : undefined,
        idempotency_key: `formal-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`,
      }, token)
      setSubmissions((current) => ({ ...current, [request.id]: submission }))
      await refresh()
    } catch (cause) {
      onError(cause)
    } finally {
      setRollingKey(null)
    }
  }

  return (
    <section className="session-roll-requests" aria-label={copy.rollRequestsTitle}>
      <h3>{copy.rollRequestsTitle}</h3>
      {requests.length === 0 ? <p>{copy.rollNoRequests}</p> : null}
      <div className="session-roll-request-list">
        {requests.map((request) => {
          const canRoll = request.status === 'pending' && (
            isCurrentDm || controlledSeatIds.includes(request.target_seat_id)
          )
          const submission = submissions[request.id]
          const eventTotal = visibleRollResultTotal(request.id, events)
          const visibleTotal = submission?.result?.total ?? eventTotal
          const rawDice = parsePhysicalD20(request.modifier_mode, physicalDice[request.id] ?? '')
          const targetRefText = formatTargetRef(request, copy)
          return (
            <article className="session-roll-request" key={request.id} data-roll-request-status={request.status}>
              <header>
                <div className="session-roll-request__title-group">
                  <strong className="session-roll-request__type">{formatRequestType(request.request_type, copy)}</strong>
                  {targetRefText ? <span className="session-roll-request__ref">{targetRefText}</span> : null}
                </div>
                <div className="session-roll-request__badges">
                  {isCurrentDm && request.dc !== null ? <span className="session-roll-badge dc">DC {request.dc}</span> : null}
                  <span className={`session-roll-badge status ${request.status}`}>{statusLabel(request, copy)}</span>
                </div>
              </header>

              <div className="session-roll-request__meta">
                <span className="session-roll-badge mode">{formatModifierMode(request.modifier_mode, copy)}</span>
                {request.flat_adjustment !== 0 ? (
                  <span className="session-roll-badge adjustment">{request.flat_adjustment > 0 ? `+${request.flat_adjustment}` : request.flat_adjustment}</span>
                ) : null}
              </div>

              {visibleTotal !== null ? (
                <p className="session-roll-request__total">
                  <strong>{copy.rollTotal}: {visibleTotal}</strong>
                </p>
              ) : null}
              {submission?.hidden ? <p className="session-roll-request__hidden">{copy.rollHidden}</p> : null}
              {canRoll ? (
                <div className="session-roll-request__actions">
                  <button
                    className="button primary session-roll-button"
                    type="button"
                    disabled={rollingKey !== null}
                    onClick={() => void roll(request, 'server')}
                  >
                    {rollingKey === `${request.id}:server` ? copy.rolling : copy.rollButton}
                  </button>
                  <div className="session-roll-physical-group">
                    <label className="session-field">
                      <span>{copy.rollPhysicalDice}</span>
                      <input
                        value={physicalDice[request.id] ?? ''}
                        disabled={rollingKey !== null}
                        placeholder={request.modifier_mode === 'normal' ? '12' : '12, 17'}
                        onChange={(event) => setPhysicalDice((current) => ({
                          ...current,
                          [request.id]: event.target.value,
                        }))}
                      />
                    </label>
                    <button
                      className="button secondary"
                      type="button"
                      disabled={rollingKey !== null || rawDice === null}
                      onClick={() => rawDice && void roll(request, 'physical', rawDice)}
                    >
                      {rollingKey === `${request.id}:physical` ? copy.rolling : copy.rollPhysicalSubmit}
                    </button>
                  </div>
                </div>
              ) : null}
            </article>
          )
        })}
      </div>
    </section>
  )
}
