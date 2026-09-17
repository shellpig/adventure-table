import { useState } from 'react'

import {
  setMonsterOutcome,
  updateMonsterInstance,
  type CombatantProjection,
  type CombatDetailView,
  type CombatEntryView,
  type MonsterInstancePatchInput,
  type MonsterOutcome,
} from '../../api/combat'
import { runCombatMutation } from './sessionCombat'
import type { SessionCopy } from './sessionCopy'
import { requestId } from './SessionTableSurface'

export type SessionCombatMonsterControlsProps = {
  combat: CombatDetailView
  entry: CombatEntryView
  projection: CombatantProjection
  instanceId: string
  copy: SessionCopy
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  onError: (cause: unknown) => void
  refresh: () => void
}

export function SessionCombatMonsterControls({
  combat,
  entry,
  projection,
  instanceId,
  copy,
  roomId,
  campaignId,
  sessionId,
  token,
  onError,
  refresh,
}: SessionCombatMonsterControlsProps) {
  const [pending, setPending] = useState(false)
  const [name, setName] = useState(projection.name)
  const [positionNote, setPositionNote] = useState(projection.position_note ?? '')
  const [outcome, setOutcome] = useState<MonsterOutcome>('dead')
  const [outcomeNote, setOutcomeNote] = useState('')

  const runMutation = (mutation: () => Promise<void>) =>
    runCombatMutation(setPending, mutation, refresh, onError)

  const handleToggleReveal = (
    field: 'armor_class' | 'description' | 'position_note',
    checked: boolean,
  ) => {
    void runMutation(async () => {
      await updateMonsterInstance(
        roomId,
        campaignId,
        sessionId,
        instanceId,
        {
          reveal: { [field]: checked },
          idempotency_key: requestId('monster-reveal'),
        },
        token,
      )
    })
  }

  const handleToggleVisibility = () => {
    const nextVisibility = projection.visibility === 'hidden' ? 'public' : 'hidden'
    void runMutation(async () => {
      await updateMonsterInstance(
        roomId,
        campaignId,
        sessionId,
        instanceId,
        {
          visibility: nextVisibility,
          idempotency_key: requestId('monster-visibility'),
        },
        token,
      )
    })
  }

  const handleSaveInfo = async (event: React.FormEvent) => {
    event.preventDefault()
    const trimmedName = name.trim()
    if (!trimmedName) return

    const trimmedNote = positionNote.trim()
    const currentNote = (projection.position_note ?? '').trim()

    const patch: MonsterInstancePatchInput = {
      idempotency_key: requestId('monster-update'),
    }

    let changed = false
    if (trimmedName !== projection.name) {
      patch.name = trimmedName
      changed = true
    }
    if (trimmedNote !== currentNote) {
      patch.position_note = trimmedNote.length > 0 ? trimmedNote : null
      changed = true
    }

    if (!changed) return

    await runMutation(async () => {
      await updateMonsterInstance(
        roomId,
        campaignId,
        sessionId,
        instanceId,
        patch,
        token,
      )
    })
  }

  const isCurrentTurn =
    combat.status === 'running' && combat.current_turn_entry_id === entry.id
  const isOtherBlank = outcome === 'other' && !outcomeNote.trim()
  const outcomeSubmitDisabled = pending || isCurrentTurn || isOtherBlank

  const handleApplyOutcome = async (event: React.FormEvent) => {
    event.preventDefault()
    if (outcomeSubmitDisabled) return
    const trimmed = outcomeNote.trim()
    await runMutation(async () => {
      await setMonsterOutcome(
        roomId,
        campaignId,
        sessionId,
        entry.id,
        {
          outcome,
          note: trimmed || null,
          idempotency_key: requestId('monster-outcome'),
        },
        token,
      )
    })
  }

  const reveal = projection.reveal ?? null

  return (
    <div
      className="session-combat__monster-controls"
      data-monster-controls={entry.id}
    >
      <div className="session-combat__sub-heading">
        {copy.combatMonsterControlsHeading}
      </div>

      {reveal ? (
        <div className="session-combat__reveal-row">
          <span className="session-combat__stat-label">
            {copy.combatRevealHeading}:
          </span>
          <label>
            <input
              type="checkbox"
              data-monster-reveal="armor_class"
              checked={reveal.armor_class}
              disabled={pending}
              onChange={(e) =>
                handleToggleReveal('armor_class', e.target.checked)
              }
            />
            <span>{copy.combatRevealAc}</span>
          </label>
          <label>
            <input
              type="checkbox"
              data-monster-reveal="description"
              checked={reveal.description}
              disabled={pending}
              onChange={(e) =>
                handleToggleReveal('description', e.target.checked)
              }
            />
            <span>{copy.combatRevealDescription}</span>
          </label>
          <label>
            <input
              type="checkbox"
              data-monster-reveal="position_note"
              checked={reveal.position_note}
              disabled={pending}
              onChange={(e) =>
                handleToggleReveal('position_note', e.target.checked)
              }
            />
            <span>{copy.combatRevealPositionNote}</span>
          </label>
        </div>
      ) : null}

      <div>
        <button
          type="button"
          className="button secondary compact"
          data-monster-visibility
          disabled={pending}
          onClick={handleToggleVisibility}
        >
          {projection.visibility === 'hidden'
            ? copy.combatMonsterSetPublic
            : copy.combatMonsterSetHidden}
        </button>
      </div>

      <form className="session-combat__form" onSubmit={handleSaveInfo}>
        <div className="session-combat__form-row">
          <label>
            <span>{copy.combatDisplayName}</span>
            <input
              type="text"
              value={name}
              maxLength={120}
              required
              disabled={pending}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            <span>{copy.combatPositionNote}</span>
            <input
              type="text"
              value={positionNote}
              maxLength={500}
              placeholder={copy.combatPositionNotePlaceholder}
              disabled={pending}
              onChange={(e) => setPositionNote(e.target.value)}
            />
          </label>
        </div>
        <div className="session-combat__form-actions">
          <button
            type="submit"
            className="button secondary compact"
            data-monster-save
            disabled={pending || !name.trim()}
          >
            {pending ? copy.combatMonsterSaving : copy.combatMonsterSave}
          </button>
        </div>
      </form>

      {entry.status === 'active' ? (
        <form className="session-combat__form" onSubmit={handleApplyOutcome}>
          <div className="session-combat__form-row">
            <label>
              <span>{copy.combatOutcomeHeading}</span>
              <select
                data-monster-outcome
                value={outcome}
                disabled={pending}
                onChange={(e) =>
                  setOutcome(e.target.value as MonsterOutcome)
                }
              >
                <option value="dead">{copy.combatOutcomeDead}</option>
                <option value="unconscious">
                  {copy.combatOutcomeUnconscious}
                </option>
                <option value="surrendered">
                  {copy.combatOutcomeSurrendered}
                </option>
                <option value="fled">{copy.combatOutcomeFled}</option>
                <option value="other">{copy.combatOutcomeOther}</option>
              </select>
            </label>
            <label>
              <span>{copy.combatOutcomeNote}</span>
              <input
                type="text"
                data-monster-outcome-note
                value={outcomeNote}
                maxLength={500}
                placeholder={copy.combatOutcomeNotePlaceholder}
                required={outcome === 'other'}
                disabled={pending}
                onChange={(e) => setOutcomeNote(e.target.value)}
              />
            </label>
          </div>
          <div className="session-combat__form-actions">
            {isCurrentTurn ? (
              <span className="session-combat__dm-hint">
                {copy.combatOutcomeCurrentTurnHint}
              </span>
            ) : null}
            <button
              type="submit"
              className="button secondary compact"
              data-monster-outcome-submit
              disabled={outcomeSubmitDisabled}
            >
              {copy.combatOutcomeSubmit}
            </button>
          </div>
        </form>
      ) : null}
    </div>
  )
}
