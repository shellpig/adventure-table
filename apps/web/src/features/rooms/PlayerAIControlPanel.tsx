import { useEffect, useState } from 'react'

import {
  AIControllerApiError,
  administrativelyReassignPlayer,
  letAiControlPlayer,
  takeBackPlayer,
  type AIControllerGrantView,
} from '../../api/aiControllers'
import type { CampaignSeat, LobbyController } from '../../api/seats'
import type { SessionCopy } from './sessionCopy'


type PlayerAIControlPanelProps = {
  roomId: string
  campaignId: string
  sessionId: string
  seat: CampaignSeat
  roomToken: string
  callerAccessSessionId: string | null
  canSelfTakeBack: boolean
  canManage: boolean
  controllers: LobbyController[]
  copy: SessionCopy
  onChanged: () => Promise<void>
}

export function PlayerAIControlPanel({
  roomId,
  campaignId,
  sessionId,
  seat,
  roomToken,
  callerAccessSessionId,
  canSelfTakeBack,
  canManage,
  controllers,
  copy,
  onChanged,
}: PlayerAIControlPanelProps) {
  const [instruction, setInstruction] = useState('')
  const [issued, setIssued] = useState<AIControllerGrantView | null>(null)
  const [recoveryTarget, setRecoveryTarget] = useState('')
  const [pending, setPending] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isHumanSelf = (
    seat.controller_kind === 'human' &&
    callerAccessSessionId !== null &&
    seat.controller_access_session_id === callerAccessSessionId
  )

  useEffect(() => {
    if (seat.controller_kind !== 'ai') {
      setIssued(null)
      setRecoveryTarget('')
    }
  }, [seat.controller_kind])

  const fail = (cause: unknown, takeBack = false) => {
    if (takeBack && cause instanceof AIControllerApiError) {
      setError(copy.aiTakeBackFailedRecovery)
      return
    }
    setError(copy.aiControllerFailed)
  }

  const handoff = async () => {
    setPending(true)
    setError(null)
    setCopied(false)
    try {
      const next = await letAiControlPlayer(
        roomId,
        campaignId,
        sessionId,
        seat.id,
        roomToken,
        instruction.trim() || null,
      )
      setIssued(next)
      setInstruction('')
      await onChanged()
    } catch (cause) {
      fail(cause)
    } finally {
      setPending(false)
    }
  }

  const takeBack = async () => {
    setPending(true)
    setError(null)
    try {
      await takeBackPlayer(roomId, campaignId, sessionId, seat.id, roomToken)
      setIssued(null)
      await onChanged()
    } catch (cause) {
      fail(cause, true)
    } finally {
      setPending(false)
    }
  }

  const recover = async () => {
    if (!recoveryTarget) return
    setPending(true)
    setError(null)
    try {
      await administrativelyReassignPlayer(
        roomId,
        campaignId,
        sessionId,
        seat.id,
        roomToken,
        recoveryTarget,
      )
      setIssued(null)
      setRecoveryTarget('')
      await onChanged()
    } catch (cause) {
      fail(cause)
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
      setError(copy.aiCopyFailed)
    }
  }

  if (!isHumanSelf && seat.controller_kind !== 'ai') return null

  return (
    <section className="room-form" data-ai-controller-panel={seat.id}>
      <h4>{copy.aiControlTitle}</h4>
      {isHumanSelf ? (
        <>
          <label>
            {copy.aiHandoffInstruction}
            <textarea
              value={instruction}
              maxLength={2000}
              disabled={pending}
              placeholder={copy.aiHandoffInstructionPlaceholder}
              onChange={(event) => setInstruction(event.target.value)}
            />
          </label>
          <button
            className="button secondary"
            type="button"
            disabled={pending}
            onClick={() => void handoff()}
          >{copy.letAiControl}</button>
        </>
      ) : null}

      {seat.controller_kind === 'ai' ? (
        <>
          <p><strong>{copy.aiControlling}</strong></p>
          <p>{canSelfTakeBack ? copy.takeBackExactOriginHint : copy.aiTakeBackFailedRecovery}</p>
          {canSelfTakeBack ? (
            <button
              className="button secondary"
              type="button"
              disabled={pending}
              onClick={() => void takeBack()}
            >{copy.takeBackControl}</button>
          ) : null}
        </>
      ) : null}

      {issued ? (
        <div className="notice-banner" role="status" data-ai-token-once="true">
          <strong>{copy.aiTokenOnceTitle}</strong>
          <p>{copy.aiTokenOnceHint}</p>
          <textarea readOnly value={issued.token} aria-label={copy.aiTokenOnceTitle} />
          <button className="button secondary" type="button" onClick={() => void copyToken()}>
            {copied ? copy.aiTokenCopied : copy.aiCopyToken}
          </button>
        </div>
      ) : null}

      {seat.controller_kind === 'ai' && canManage ? (
        <div className="room-form" data-ai-recovery="true">
          <h4>{copy.aiRecoveryTitle}</h4>
          <p>{copy.aiRecoveryHint}</p>
          <label>
            {copy.aiRecoveryTarget}
            <select
              value={recoveryTarget}
              disabled={pending}
              onChange={(event) => setRecoveryTarget(event.target.value)}
            >
              <option value="">{copy.aiRecoveryChoose}</option>
              {controllers.map((controller) => (
                <option key={controller.access_session_id} value={controller.access_session_id}>
                  {controller.display_name || controller.access_session_id}
                  {' · '}
                  {controller.presence === 'connected' ? copy.aiConnected : copy.aiOffline}
                </option>
              ))}
            </select>
          </label>
          <button
            className="button secondary"
            type="button"
            disabled={pending || !recoveryTarget}
            onClick={() => void recover()}
          >{copy.aiRecoverToHuman}</button>
        </div>
      ) : null}

      {error ? <div className="error-banner" role="alert">{error}</div> : null}
    </section>
  )
}
