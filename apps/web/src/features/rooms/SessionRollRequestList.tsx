import { useEffect, useMemo, useState } from 'react'

import {
  listRollRequests,
  submitFormalRoll,
  type RollRequestView,
  type RollSubmissionResponse,
} from '../../api/p3c'
import type { TableEvent } from '../../api/sessions'
import type { SessionCopy } from './sessionCopy'

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
  const [rollingId, setRollingId] = useState<string | null>(null)

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

  const roll = async (request: RollRequestView) => {
    setRollingId(request.id)
    try {
      const submission = await submitFormalRoll(roomId, campaignId, sessionId, {
        roll_request_id: request.id,
        source: 'server',
        idempotency_key: `formal-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`,
      }, token)
      setSubmissions((current) => ({ ...current, [request.id]: submission }))
      await refresh()
    } catch (cause) {
      onError(cause)
    } finally {
      setRollingId(null)
    }
  }

  return (
    <section className="session-roll-requests" aria-label={copy.rollRequestsTitle}>
      <h3>{copy.rollRequestsTitle}</h3>
      {requests.length === 0 ? <p>{copy.rollNoRequests}</p> : null}
      {requests.map((request) => {
        const canRoll = request.status === 'pending' && (
          isCurrentDm || controlledSeatIds.includes(request.target_seat_id)
        )
        const submission = submissions[request.id]
        const eventTotal = visibleRollResultTotal(request.id, events)
        const visibleTotal = submission?.result?.total ?? eventTotal
        return (
          <article className="session-roll-request" key={request.id} data-roll-request-status={request.status}>
            <header>
              <strong>{request.request_type}</strong>
              <span>{statusLabel(request, copy)}</span>
              {isCurrentDm && request.dc !== null ? <span>DC {request.dc}</span> : null}
            </header>
            {request.skill_ref ? <p>{request.skill_ref}</p> : null}
            {request.ability_ref ? <p>{request.ability_ref}</p> : null}
            <p>{request.modifier_mode}</p>
            {visibleTotal !== null ? <p><strong>{copy.rollTotal}: {visibleTotal}</strong></p> : null}
            {submission?.hidden ? <p>{copy.rollHidden}</p> : null}
            {canRoll ? (
              <button
                className="button primary"
                type="button"
                disabled={rollingId !== null}
                onClick={() => void roll(request)}
              >
                {rollingId === request.id ? copy.rolling : copy.rollButton}
              </button>
            ) : null}
          </article>
        )
      })}
    </section>
  )
}
