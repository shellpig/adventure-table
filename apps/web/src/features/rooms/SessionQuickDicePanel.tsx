import { useMemo, useState } from 'react'

import {
  submitQuickRoll,
  type QuickRollInput,
  type RollVisibility,
} from '../../api/p3c'
import type { SessionCopy } from './sessionCopy'

export type QuickDiceTarget = { seatId: string; label: string }

export type QuickDiceDraft = {
  subjectSeatId: string
  diceCount: string
  dieSides: string
  flatAdjustment: string
  visibility: RollVisibility
}

export function buildQuickRollInput(draft: QuickDiceDraft): QuickRollInput | null {
  const diceCount = Number(draft.diceCount)
  const dieSides = Number(draft.dieSides)
  const flatAdjustment = Number(draft.flatAdjustment)
  if (!draft.subjectSeatId) return null
  if (!Number.isInteger(diceCount) || diceCount < 1 || diceCount > 20) return null
  if (!Number.isInteger(dieSides) || dieSides < 2 || dieSides > 1000) return null
  if (!Number.isInteger(flatAdjustment) || flatAdjustment < -1000 || flatAdjustment > 1000) return null
  return {
    subject_seat_id: draft.subjectSeatId,
    dice_count: diceCount,
    die_sides: dieSides,
    flat_adjustment: flatAdjustment,
    visibility: draft.visibility,
  }
}

export function SessionQuickDicePanel({
  roomId,
  campaignId,
  sessionId,
  token,
  targets,
  copy,
  onError,
}: {
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  targets: QuickDiceTarget[]
  copy: SessionCopy
  onError: (cause: unknown) => void
}) {
  const [subjectSeatId, setSubjectSeatId] = useState(targets[0]?.seatId ?? '')
  const [diceCount, setDiceCount] = useState('1')
  const [dieSides, setDieSides] = useState('20')
  const [flatAdjustment, setFlatAdjustment] = useState('0')
  const [visibility, setVisibility] = useState<RollVisibility>('public')
  const [pending, setPending] = useState(false)
  const [resultText, setResultText] = useState<string | null>(null)

  const input = useMemo(() => buildQuickRollInput({
    subjectSeatId,
    diceCount,
    dieSides,
    flatAdjustment,
    visibility,
  }), [subjectSeatId, diceCount, dieSides, flatAdjustment, visibility])

  if (targets.length === 0) return null

  const submit = async () => {
    if (!input) return
    setPending(true)
    setResultText(null)
    try {
      const response = await submitQuickRoll(roomId, campaignId, sessionId, {
        ...input,
        idempotency_key: `quick-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`,
      }, token)
      setResultText(
        response.hidden
          ? copy.rollHidden
          : `${copy.quickResult}: ${response.result?.total ?? '—'}`,
      )
    } catch (cause) {
      onError(cause)
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="session-quick-dice" aria-label={copy.quickDiceTitle}>
      <h3>{copy.quickDiceTitle}</h3>
      <label>
        <span>{copy.quickTarget}</span>
        <select value={subjectSeatId} disabled={pending} onChange={(event) => setSubjectSeatId(event.target.value)}>
          {targets.map((target) => <option value={target.seatId} key={target.seatId}>{target.label}</option>)}
        </select>
      </label>
      <label>
        <span>{copy.quickCount}</span>
        <input type="number" min="1" max="20" value={diceCount} disabled={pending} onChange={(event) => setDiceCount(event.target.value)} />
      </label>
      <label>
        <span>{copy.quickSides}</span>
        <input type="number" min="2" max="1000" value={dieSides} disabled={pending} onChange={(event) => setDieSides(event.target.value)} />
      </label>
      <label>
        <span>{copy.quickAdjustment}</span>
        <input type="number" min="-1000" max="1000" value={flatAdjustment} disabled={pending} onChange={(event) => setFlatAdjustment(event.target.value)} />
      </label>
      <label>
        <span>{copy.checkVisibility}</span>
        <select value={visibility} disabled={pending} onChange={(event) => setVisibility(event.target.value as RollVisibility)}>
          <option value="public">{copy.checkPublic}</option>
          <option value="roller_and_dm">{copy.checkRollerDm}</option>
          <option value="dm_only">{copy.checkDmOnly}</option>
        </select>
      </label>
      <button className="button secondary" type="button" disabled={pending || input === null} onClick={() => void submit()}>
        {pending ? copy.quickRolling : copy.quickRoll}
      </button>
      {resultText ? <p role="status">{resultText}</p> : null}
    </section>
  )
}
