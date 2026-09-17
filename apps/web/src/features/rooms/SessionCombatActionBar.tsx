import { useEffect, useState } from 'react'

import {
  listAttacks,
  requestAttack,
  rollAttack,
  rollConcentration,
  rollDeathSave,
  rollSavingThrow,
  rollSpecialAttack,
  type AttackDefinitionView,
  type AttackResolutionView,
  type CombatAdjudicationView,
  type CombatDetailView,
  type CombatPendingRollView,
  type ConcentrationCheckResultView,
  type DeathSaveResultView,
  type SavingThrowResultView,
} from '../../api/combat'
import {
  actingEntryId,
  adjudicationKindLabel,
  combatInjuryLabel,
  pendingCombatRollHandler,
  runCombatMutation,
  type PendingCombatRollDispatchTable,
} from './sessionCombat'
import type { SessionCopy } from './sessionCopy'
import { requestId } from './SessionTableSurface'

type CombatRollResult =
  | { kind: 'attack'; value: AttackResolutionView }
  | { kind: 'saving_throw'; value: SavingThrowResultView }
  | { kind: 'death_save'; value: DeathSaveResultView }
  | { kind: 'concentration'; value: ConcentrationCheckResultView }

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
  const [rollResult, setRollResult] = useState<CombatRollResult | null>(null)
  const [pendingActionId, setPendingActionId] = useState<string | null>(null)
  const [pendingActionSeen, setPendingActionSeen] = useState(false)

  useEffect(() => {
    setAttacks([])
    setAttackRef('')
    setTargetEntryId('')
    setModifierMode('normal')
    setRangeConfirmed(true)
    setLocalRollRequestId(null)
    setRollResult(null)
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
        setRollResult(null)
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

  const rollBody = (rollRequestId: string, prefix: string) => ({
    roll_request_id: rollRequestId,
    source: 'server' as const,
    idempotency_key: requestId(prefix),
  })

  const rollHandlers: PendingCombatRollDispatchTable = {
    attack: async (rollRequestId) => {
      const value = await rollAttack(
        roomId,
        campaignId,
        sessionId,
        rollBody(rollRequestId, 'attack-roll'),
        token,
      )
      setRollResult({ kind: 'attack', value })
      if (localRollRequestId === rollRequestId) {
        setLocalRollRequestId(null)
      }
    },
    saving_throw: async (rollRequestId) => {
      const value = await rollSavingThrow(
        roomId,
        campaignId,
        sessionId,
        rollBody(rollRequestId, 'saving-throw-roll'),
        token,
      )
      setRollResult({ kind: 'saving_throw', value })
    },
    death_save: async (rollRequestId) => {
      const value = await rollDeathSave(
        roomId,
        campaignId,
        sessionId,
        rollBody(rollRequestId, 'death-save-roll'),
        token,
      )
      setRollResult({ kind: 'death_save', value })
    },
    concentration: async (rollRequestId) => {
      const value = await rollConcentration(
        roomId,
        campaignId,
        sessionId,
        rollBody(rollRequestId, 'concentration-roll'),
        token,
      )
      setRollResult({ kind: 'concentration', value })
    },
    grapple: async (rollRequestId) => {
      await rollSpecialAttack(
        roomId,
        campaignId,
        sessionId,
        rollBody(rollRequestId, 'grapple-roll'),
        token,
      )
      setRollResult(null)
    },
    shove: async (rollRequestId) => {
      await rollSpecialAttack(
        roomId,
        campaignId,
        sessionId,
        rollBody(rollRequestId, 'shove-roll'),
        token,
      )
      setRollResult(null)
    },
  }

  const handlePendingRoll = (requestType: string, rollRequestId: string) => {
    const handler = pendingCombatRollHandler(requestType, rollHandlers)
    if (!handler) return Promise.resolve()
    return runCombatMutation(
      setPending,
      () => handler(rollRequestId),
      refresh,
      onError,
    )
  }

  const requestTypeLabel = (requestType: string): string => {
    switch (requestType) {
      case 'attack':
        return copy.combatRollTypeAttack
      case 'saving_throw':
        return copy.combatRollTypeSavingThrow
      case 'death_save':
        return copy.combatRollTypeDeathSave
      case 'concentration':
        return copy.combatRollTypeConcentration
      case 'grapple':
        return copy.combatRollTypeGrapple
      case 'shove':
        return copy.combatRollTypeShove
      default:
        return requestType
    }
  }

  const pendingRows = pendingRolls.filter(
    (roll) => roll.request_type !== 'initiative' && roll.id !== localRollRequestId,
  )

  const actionState = currentActingEntryId === null
    ? 'waiting'
    : pendingActionId !== null
      ? 'adjudication-pending'
      : 'ready'

  const attackResultStatus = rollResult?.kind === 'attack'
    ? rollResult.value.critical
      ? copy.combatAttackCritical
      : rollResult.value.hit
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
          onClick={() => void handlePendingRoll('attack', localRollRequestId)}
        >
          {copy.combatRollAttack}
        </button>
      ) : null}

      <div className="session-combat-actions__pending-rolls">
        <h4 className="session-combat__sub-heading">{copy.combatPendingRollsHeading}</h4>
        {pendingRows.map((roll) => {
          const handler = pendingCombatRollHandler(roll.request_type, rollHandlers)
          return (
            <div key={roll.id} className="session-combat-actions__pending-roll-row">
              <span>
                {roll.label ?? requestTypeLabel(roll.request_type)}
                {roll.request_type === 'saving_throw' && roll.ability_ref ? ` · ${roll.ability_ref}` : ''}
                {roll.request_type === 'saving_throw' && typeof roll.dc === 'number' ? ` · DC ${roll.dc}` : ''}
              </span>
              {handler ? (
                <button
                  type="button"
                  className="button secondary compact"
                  data-pending-roll={roll.id}
                  disabled={pending}
                  onClick={() => void handlePendingRoll(roll.request_type, roll.id)}
                >
                  {copy.combatRollPending}
                </button>
              ) : null}
            </div>
          )
        })}
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

      {rollResult?.kind === 'attack' && attackResultStatus ? (
        <p className="session-combat-actions__result" data-attack-result="true">
          <strong>{attackResultStatus}</strong>
          {' · '}
          {copy.combatAttackDamage.replace('{damage}', String(rollResult.value.damage_total))}
          {typeof rollResult.value.after_hp === 'number' ? (
            <> · {copy.combatHp}: {rollResult.value.after_hp}</>
          ) : rollResult.value.target_injury_level ? (
            <> · {combatInjuryLabel(rollResult.value.target_injury_level, copy)}</>
          ) : null}
        </p>
      ) : rollResult?.kind === 'saving_throw' ? (
        <p className="session-combat-actions__result" data-roll-result="saving_throw">
          {copy.combatSavingThrowResult.replace('{total}', String(rollResult.value.total))}
          {' · '}
          {rollResult.value.succeeded ? copy.combatSaveSuccess : copy.combatSaveFailure}
        </p>
      ) : rollResult?.kind === 'death_save' ? (
        <p className="session-combat-actions__result" data-roll-result="death_save">
          {copy.combatDeathSaveResult
            .replace('{d20}', String(rollResult.value.d20))
            .replace('{successes}', String(rollResult.value.successes))
            .replace('{failures}', String(rollResult.value.failures))}
          {rollResult.value.stable ? ` · ${copy.combatDeathSaveStable}` : null}
          {rollResult.value.dead ? ` · ${copy.combatDeathSaveDead}` : null}
        </p>
      ) : rollResult?.kind === 'concentration' ? (
        <p className="session-combat-actions__result" data-roll-result="concentration">
          {copy.combatConcentrationResult
            .replace('{total}', String(rollResult.value.total))
            .replace('{dc}', String(rollResult.value.dc))}
          {' · '}
          {rollResult.value.succeeded ? copy.combatConcentrationKept : copy.combatConcentrationLost}
        </p>
      ) : null}
    </section>
  )
}
