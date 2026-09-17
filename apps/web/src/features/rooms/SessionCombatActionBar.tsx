import { useEffect, useState } from 'react'

import {
  listAttacks,
  requestAttack,
  rollAttack,
  type AttackDefinitionView,
  type AttackResolutionView,
  type CombatAdjudicationView,
  type CombatDetailView,
  type CombatPendingRollView,
} from '../../api/combat'
import {
  actingEntryId,
  adjudicationKindLabel,
  combatInjuryLabel,
  runCombatMutation,
} from './sessionCombat'
import type { SessionCopy } from './sessionCopy'
import { requestId } from './SessionTableSurface'

type SessionCombatActionBarProps = {
  combat: CombatDetailView
  myEntryIds: string[]
  pendingRolls: CombatPendingRollView[]
  pendingAdjudications: CombatAdjudicationView[]
  copy: SessionCopy
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  isCurrentDm: boolean
  onError: (cause: unknown) => void
  refresh: () => void
}

export function SessionCombatActionBar({
  combat,
  myEntryIds,
  pendingRolls,
  pendingAdjudications,
  copy,
  roomId,
  campaignId,
  sessionId,
  token,
  isCurrentDm,
  onError,
  refresh,
}: SessionCombatActionBarProps) {
  const currentActingEntryId = actingEntryId(combat, myEntryIds, isCurrentDm)
  const actingEntry = currentActingEntryId
    ? combat.entries.find((entry) => entry.id === currentActingEntryId) ?? null
    : null
  const currentTurnEntry = combat.current_turn_entry_id
    ? combat.entries.find((entry) => entry.id === combat.current_turn_entry_id) ?? null
    : null
  const currentTurnName = currentTurnEntry?.display_name ?? copy.combatUnknownCombatant

  const [attacks, setAttacks] = useState<AttackDefinitionView[]>([])
  const [attackRef, setAttackRef] = useState('')
  const [targetEntryId, setTargetEntryId] = useState('')
  const [modifierMode, setModifierMode] = useState<'normal' | 'advantage' | 'disadvantage'>('normal')
  const [rangeConfirmed, setRangeConfirmed] = useState(true)
  const [pending, setPending] = useState(false)
  const [localRollRequestId, setLocalRollRequestId] = useState<string | null>(null)
  const [resolution, setResolution] = useState<AttackResolutionView | null>(null)
  const [pendingActionId, setPendingActionId] = useState<string | null>(null)
  const [pendingActionSeen, setPendingActionSeen] = useState(false)

  useEffect(() => {
    setAttacks([])
    setAttackRef('')
    setTargetEntryId('')
    setModifierMode('normal')
    setRangeConfirmed(true)
    setLocalRollRequestId(null)
    setResolution(null)
    setPendingActionId(null)
    setPendingActionSeen(false)
    if (currentActingEntryId === null) return

    let active = true
    void listAttacks(roomId, campaignId, sessionId, currentActingEntryId, token)
      .then((items) => {
        if (!active) return
        setAttacks(items)
        setAttackRef(items[0]?.source_ref ?? '')
      })
      .catch((cause) => {
        if (active) onError(cause)
      })

    return () => {
      active = false
    }
  }, [roomId, campaignId, sessionId, token, currentActingEntryId, onError])

  useEffect(() => {
    if (pendingActionId === null) return
    const isListed = pendingAdjudications.some((item) => item.action_id === pendingActionId)
    if (isListed && !pendingActionSeen) {
      setPendingActionSeen(true)
    } else if (!isListed && pendingActionSeen) {
      setPendingActionId(null)
      setPendingActionSeen(false)
    }
  }, [pendingActionId, pendingActionSeen, pendingAdjudications])

  const targetEntries = combat.entries.filter(
    (entry) => entry.id !== currentActingEntryId && entry.status === 'active',
  )
  const hasAttackEconomy = Boolean(
    actingEntry &&
      actingEntry.action_available &&
      actingEntry.attacks_used < actingEntry.attacks_allowed,
  )
  const formDisabled = pending || !hasAttackEconomy

  const clearAttackForm = () => {
    setAttackRef('')
    setTargetEntryId('')
    setModifierMode('normal')
    setRangeConfirmed(true)
  }

  const handleRequestAttack = async (event: React.FormEvent) => {
    event.preventDefault()
    if (currentActingEntryId === null || !attackRef || !targetEntryId || !hasAttackEconomy) return

    await runCombatMutation(
      setPending,
      async () => {
        const response = await requestAttack(
          roomId,
          campaignId,
          sessionId,
          {
            attacker_entry_id: currentActingEntryId,
            target_entry_id: targetEntryId,
            source_ref: attackRef,
            modifier_mode: modifierMode,
            ...(isCurrentDm && rangeConfirmed ? { range_confirmed: true } : {}),
            idempotency_key: requestId('attack-request'),
          },
          token,
        )
        setResolution(null)
        if (response.roll_request_id !== null) {
          setLocalRollRequestId(response.roll_request_id)
          setPendingActionId(null)
          setPendingActionSeen(false)
        } else {
          setLocalRollRequestId(null)
          setPendingActionId(response.action_id)
          setPendingActionSeen(false)
          clearAttackForm()
        }
      },
      refresh,
      onError,
    )
  }

  const handleRollAttack = (rollRequestId: string) =>
    runCombatMutation(
      setPending,
      async () => {
        const result = await rollAttack(
          roomId,
          campaignId,
          sessionId,
          {
            roll_request_id: rollRequestId,
            source: 'server',
            idempotency_key: requestId('attack-roll'),
          },
          token,
        )
        setResolution(result)
        if (localRollRequestId === rollRequestId) {
          setLocalRollRequestId(null)
        }
      },
      refresh,
      onError,
    )

  // E10c owns saving throws, death saves, concentration rolls, and other Combat roll types.
  const attackRolls = pendingRolls.filter(
    (roll) => roll.request_type === 'attack' && roll.id !== localRollRequestId,
  )

  const actionState = currentActingEntryId === null
    ? 'waiting'
    : pendingActionId !== null
      ? 'adjudication-pending'
      : 'ready'

  const resultStatus = resolution
    ? resolution.critical
      ? copy.combatAttackCritical
      : resolution.hit
        ? copy.combatAttackHit
        : copy.combatAttackMiss
    : null

  return (
    <section
      className="session-combat-actions"
      data-combat-action-bar="true"
      data-combat-action-state={actionState}
    >
      <h3 className="session-combat__section-heading">{copy.combatActionBarHeading}</h3>

      {currentActingEntryId === null ? (
        <p className="session-combat-actions__waiting">
          {copy.combatWaitingForTurn.replace('{name}', currentTurnName)}
        </p>
      ) : pendingActionId !== null ? (
        <p className="session-combat-actions__waiting">{copy.combatAwaitingAdjudication}</p>
      ) : (
        <form className="session-combat__form session-combat-actions__form" onSubmit={handleRequestAttack}>
          <div className="session-combat__form-row">
            <label>
              <span>{copy.combatAttackLabel}</span>
              <select
                value={attackRef}
                disabled={formDisabled}
                onChange={(event) => setAttackRef(event.target.value)}
              >
                {attacks.map((attack) => (
                  <option key={attack.source_ref} value={attack.source_ref}>
                    {`${attack.name} (+${attack.attack_bonus})`}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>{copy.combatTargetLabel}</span>
              <select
                value={targetEntryId}
                disabled={formDisabled}
                onChange={(event) => setTargetEntryId(event.target.value)}
              >
                <option value="">—</option>
                {targetEntries.map((entry) => (
                  <option key={entry.id} value={entry.id}>{entry.display_name}</option>
                ))}
              </select>
            </label>
            <label>
              <span>{copy.checkModifier}</span>
              <select
                value={modifierMode}
                disabled={formDisabled}
                onChange={(event) =>
                  setModifierMode(
                    event.target.value === 'advantage'
                      ? 'advantage'
                      : event.target.value === 'disadvantage'
                        ? 'disadvantage'
                        : 'normal',
                  )
                }
              >
                <option value="normal">{copy.checkNormal}</option>
                <option value="advantage">{copy.checkAdvantage}</option>
                <option value="disadvantage">{copy.checkDisadvantage}</option>
              </select>
            </label>
          </div>
          {isCurrentDm ? (
            <label className="session-combat-actions__range-confirmed">
              <input
                type="checkbox"
                checked={rangeConfirmed}
                disabled={formDisabled}
                onChange={(event) => setRangeConfirmed(event.target.checked)}
              />
              <span>{copy.combatRangeConfirmed}</span>
            </label>
          ) : null}
          <div className="session-combat__form-actions">
            <button
              type="submit"
              className="button primary compact"
              disabled={formDisabled || !attackRef || !targetEntryId}
            >
              {pending ? copy.sending : copy.combatRequestAttack}
            </button>
          </div>
        </form>
      )}

      {localRollRequestId !== null ? (
        <button
          type="button"
          className="button primary compact"
          data-attack-roll={localRollRequestId}
          disabled={pending}
          onClick={() => void handleRollAttack(localRollRequestId)}
        >
          {copy.combatRollAttack}
        </button>
      ) : null}

      <div className="session-combat-actions__pending-rolls">
        <h4 className="session-combat__sub-heading">{copy.combatPendingAttackRollsHeading}</h4>
        {attackRolls.map((roll) => (
          <button
            key={roll.id}
            type="button"
            className="button secondary compact"
            data-pending-roll={roll.id}
            disabled={pending}
            onClick={() => void handleRollAttack(roll.id)}
          >
            {copy.combatRollAttack}
          </button>
        ))}
      </div>

      {!isCurrentDm ? (
        <div className="session-combat-actions__pending-adjudications">
          {pendingAdjudications.map((item) => (
            <p key={item.action_id} data-adjudication-pending={item.action_id}>
              {copy.combatAwaitingDmRuling.replace(
                '{kind}',
                adjudicationKindLabel(item.kind, copy),
              )}
            </p>
          ))}
        </div>
      ) : null}

      {resolution && resultStatus ? (
        <p className="session-combat-actions__result" data-attack-result="true">
          <strong>{resultStatus}</strong>
          {' · '}
          {copy.combatAttackDamage.replace('{damage}', String(resolution.damage_total))}
          {typeof resolution.after_hp === 'number' ? (
            <> · {copy.combatHp}: {resolution.after_hp}</>
          ) : resolution.target_injury_level ? (
            <> · {combatInjuryLabel(resolution.target_injury_level, copy)}</>
          ) : null}
        </p>
      ) : null}
    </section>
  )
}
