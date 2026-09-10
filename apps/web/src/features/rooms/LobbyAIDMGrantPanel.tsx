import { useEffect, useState } from 'react'

import {
  configurePreSessionAiDm,
  revokePreSessionAiDm,
  type AIControllerGrantView,
} from '../../api/aiControllers'
import type { CampaignSeat } from '../../api/seats'
import { lobbyCopy } from './lobbyCopy'


type LobbyAIDMGrantPanelProps = {
  roomId: string
  campaignId: string
  seat: CampaignSeat
  roomToken: string
  copy: ReturnType<typeof lobbyCopy>
  onChanged: () => Promise<void>
}

export function LobbyAIDMGrantPanel({
  roomId,
  campaignId,
  seat,
  roomToken,
  copy,
  onChanged,
}: LobbyAIDMGrantPanelProps) {
  const [issued, setIssued] = useState<AIControllerGrantView | null>(null)
  const [pending, setPending] = useState(false)
  const [copied, setCopied] = useState(false)
  const [expired, setExpired] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setExpired(false)
    const expiresAt = issued?.expires_at
    if (!expiresAt) return
    const remaining = Date.parse(expiresAt) - Date.now()
    if (remaining <= 0) {
      setExpired(true)
      return
    }
    const timer = window.setTimeout(
      () => setExpired(true),
      Math.min(remaining, 2_147_483_647),
    )
    return () => window.clearTimeout(timer)
  }, [issued?.expires_at])

  const issue = async () => {
    setPending(true)
    setError(null)
    setCopied(false)
    try {
      const next = await configurePreSessionAiDm(
        roomId,
        campaignId,
        seat.id,
        roomToken,
      )
      setIssued(next)
      await onChanged()
    } catch {
      setError(copy.aiDmFailed)
    } finally {
      setPending(false)
    }
  }

  const revoke = async () => {
    setPending(true)
    setError(null)
    try {
      await revokePreSessionAiDm(roomId, campaignId, seat.id, roomToken)
      setIssued(null)
      setExpired(false)
      await onChanged()
    } catch {
      setError(copy.aiDmFailed)
    } finally {
      setPending(false)
    }
  }

  const copyToken = async () => {
    if (!issued) return
    try {
      await navigator.clipboard.writeText(issued.token)
      setCopied(true)
    } catch {
      setError(copy.aiDmCopyFailed)
    }
  }

  const configured = seat.controller_kind === 'ai'

  return (
    <section className="room-form" data-ai-dm-grant-panel={seat.id}>
      <h3>{copy.aiDmTitle}</h3>
      <p>{copy.aiDmFiniteHint}</p>
      {configured ? <p><strong>{copy.aiDmConfigured}</strong></p> : null}

      <div className="workshop-card__split-actions">
        <button
          className="button secondary"
          type="button"
          disabled={pending}
          onClick={() => void issue()}
        >
          {configured ? copy.aiDmRotate : copy.aiDmCreate}
        </button>
        {configured ? (
          <button
            className="button danger"
            type="button"
            disabled={pending}
            onClick={() => void revoke()}
          >{copy.aiDmRevoke}</button>
        ) : null}
      </div>

      {issued ? (
        <div className="notice-banner" role="status" data-ai-dm-token-once="true">
          <strong>{copy.aiDmTokenOnceTitle}</strong>
          <p>{copy.aiDmTokenOnceHint}</p>
          {issued.expires_at ? (
            <p>
              {copy.aiDmExpiresAt}: <time dateTime={issued.expires_at}>{issued.expires_at}</time>
              {expired ? ` · ${copy.aiDmExpired}` : ''}
            </p>
          ) : null}
          <textarea readOnly value={issued.token} aria-label={copy.aiDmTokenOnceTitle} />
          <button className="button secondary" type="button" onClick={() => void copyToken()}>
            {copied ? copy.aiDmCopied : copy.aiDmCopy}
          </button>
        </div>
      ) : null}

      {error ? <div className="error-banner" role="alert">{error}</div> : null}
    </section>
  )
}
