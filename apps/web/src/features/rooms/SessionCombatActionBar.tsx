import { useEffect, useState } from 'react'

import {
  castSpell,
  conditionLabel,
  listAttacks,
  listCastableSpells,
  proposeAoeSpell,
  requestAttack,
  requestSpecialAttack,
  resolveReaction,
  rollAttack,
  rollConcentration,
  rollDeathSave,
  rollSavingThrow,
  rollSpecialAttack,
  type AttackDefinitionView,
  type AttackResolutionView,
  type CastableSpellView,
  type CombatAdjudicationView,
  type CombatDetailView,
  type CombatEntryView,
  type CombatPendingRollView,
  type ConcentrationCheckResultView,
  type DeathSaveResultView,
  type ReactionKind,
  type ReactionWindowView,
  type SavingThrowResultView,
  type SpecialAttackKind,
} from '../../api/combat'
import {
  actingEntryId,
  adjudicationKindLabel,
  combatInjuryLabel,
  combatantFor,
  eligibleReactionEntry,
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

type ActionKind =
  | 'attack'
  | 'grapple'
  | 'shove_prone'
  | 'shove_push'
  | 'escape_grapple'
  | 'spell'

const ACTION_KINDS: readonly ActionKind[] = [
  'attack',
  'grapple',
  'shove_prone',
  'shove_push',
  'escape_grapple',
  'spell',
]

function isActionKind(value: string): value is ActionKind {
  return (ACTION_KINDS as readonly string[]).includes(value)
}

function isSpecialAttackKind(kind: ActionKind): kind is SpecialAttackKind {
  return (
    kind === 'grapple' ||
    kind === 'shove_prone' ||
    kind === 'shove_push' ||
    kind === 'escape_grapple'
  )
}

type SpellActionFieldsProps = {
  spells: CastableSpellView[]
  spellRef: string
  slotLevel: number | null
  targetEntryId: string
  targetEntries: Array<{ id: string; display_name: string }>
  disabled: boolean
  copy: SessionCopy
  onSpellRefChange: (spellRef: string) => void
  onSlotLevelChange: (slotLevel: number) => void
  onTargetEntryIdChange: (entryId: string) => void
}

export function SpellActionFields({
  spells,
  spellRef,
  slotLevel,
  targetEntryId,
  targetEntries,
  disabled,
  copy,
  onSpellRefChange,
  onSlotLevelChange,
  onTargetEntryIdChange,
}: SpellActionFieldsProps) {
  const spell = spells.find((item) => item.spell_ref === spellRef) ?? null
  return (
    <>
      <label>
        <span>{copy.combatSpellLabel}</span>
        <select
          data-combat-spell="true"
          value={spellRef}
          disabled={disabled}
          onChange={(event) => onSpellRefChange(event.target.value)}
        >
          <option value="">—</option>
          {spells.map((item) => (
            <option key={item.spell_ref} value={item.spell_ref}>
              {`${item.name} (Lv ${item.level})`}
            </option>
          ))}
        </select>
      </label>
      {spell && spell.castable_slot_levels.length > 1 ? (
        <label>
          <span>{copy.combatSpellSlotLevel}</span>
          <select
            data-combat-spell-slot="true"
            value={slotLevel ?? spell.castable_slot_levels[0]}
            disabled={disabled}
            onChange={(event) => onSlotLevelChange(Number(event.target.value))}
          >
            {spell.castable_slot_levels.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {spell?.targeting === 'single' ? (
        <label>
          <span>{copy.combatTargetLabel}</span>
          <select
            data-combat-spell-target="true"
            value={targetEntryId}
            disabled={disabled}
            onChange={(event) => onTargetEntryIdChange(event.target.value)}
          >
            <option value="">—</option>
            {targetEntries.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.display_name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </>
  )
}

/** Heal / utility single-target spells may target the caster; attack / save spells never do. */
export function spellTargetEntries(
  selectedSpell: CastableSpellView | null,
  actingEntry: CombatEntryView | null,
  targetEntries: CombatEntryView[],
): CombatEntryView[] {
  if (
    selectedSpell !== null &&
    actingEntry !== null &&
    selectedSpell.targeting === 'single' &&
    (selectedSpell.cast_mode === 'heal' || selectedSpell.cast_mode === 'utility')
  ) {
    return [actingEntry, ...targetEntries]
  }
  return targetEntries
}

type SessionCombatActionBarProps = {
  combat: CombatDetailView
  myEntryIds: string[]
  pendingRolls: CombatPendingRollView[]
  pendingAdjudications: CombatAdjudicationView[]
  reactionEntryIds: string[]
  reactionWindows: ReactionWindowView[]
  copy: SessionCopy
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  isCurrentDm: boolean
  onError: (cause: unknown) => void
  refresh: () => void
}

function reactionKindLabel(kind: ReactionKind, copy: SessionCopy): string {
  switch (kind) {
    case 'opportunity_attack':
      return copy.combatReactionKindOpportunityAttack
    case 'shield':
      return copy.combatReactionKindShield
    case 'counterspell':
      return copy.combatReactionKindCounterspell
    case 'ready':
      return copy.combatReactionKindReady
    case 'legendary_action':
      return copy.combatReactionKindLegendaryAction
    case 'other':
      return copy.combatReactionKindOther
  }
}

function payloadValue(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  if (value === null) return 'null'
  return JSON.stringify(value) ?? ''
}

export function SessionCombatActionBar({
  combat,
  myEntryIds,
  pendingRolls,
  pendingAdjudications,
  reactionEntryIds,
  reactionWindows,
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
    ? (combat.entries.find((entry) => entry.id === currentActingEntryId) ?? null)
    : null
  const actingCombatant = currentActingEntryId
    ? combatantFor(combat, currentActingEntryId)
    : undefined
  const actingIsGrappled = Boolean(
    actingCombatant?.projection.conditions.some(
      (item) => conditionLabel(item) === 'srd5.1:condition:grappled',
    ),
  )
  const currentTurnEntry = combat.current_turn_entry_id
    ? (combat.entries.find((entry) => entry.id === combat.current_turn_entry_id) ?? null)
    : null
  const currentTurnName = currentTurnEntry?.display_name ?? copy.combatUnknownCombatant

  const [attacks, setAttacks] = useState<AttackDefinitionView[]>([])
  const [spells, setSpells] = useState<CastableSpellView[]>([])
  const [actionKind, setActionKind] = useState<ActionKind>('attack')
  const [attackRef, setAttackRef] = useState('')
  const [spellRef, setSpellRef] = useState('')
  const [slotLevel, setSlotLevel] = useState<number | null>(null)
  const [targetEntryId, setTargetEntryId] = useState('')
  const [modifierMode, setModifierMode] = useState<'normal' | 'advantage' | 'disadvantage'>(
    'normal',
  )
  const [rangeConfirmed, setRangeConfirmed] = useState(true)
  const [pending, setPending] = useState(false)
  const [localRollRequestId, setLocalRollRequestId] = useState<string | null>(null)
  const [rollResult, setRollResult] = useState<CombatRollResult | null>(null)
  const [spellStatus, setSpellStatus] = useState<{ castMode: string; status: string } | null>(null)
  const [pendingActionId, setPendingActionId] = useState<string | null>(null)
  const [pendingActionSeen, setPendingActionSeen] = useState(false)

  useEffect(() => {
    if (actionKind === 'escape_grapple' && !actingIsGrappled) {
      setActionKind('attack')
      setTargetEntryId('')
    }
  }, [actionKind, actingIsGrappled])

  useEffect(() => {
    setAttacks([])
    setSpells([])
    setActionKind('attack')
    setAttackRef('')
    setSpellRef('')
    setSlotLevel(null)
    setTargetEntryId('')
    setModifierMode('normal')
    setRangeConfirmed(true)
    setLocalRollRequestId(null)
    setRollResult(null)
    setSpellStatus(null)
    setPendingActionId(null)
    setPendingActionSeen(false)
    if (currentActingEntryId === null) return

    let active = true
    void Promise.all([
      listAttacks(roomId, campaignId, sessionId, currentActingEntryId, token),
      listCastableSpells(roomId, campaignId, sessionId, currentActingEntryId, token),
    ])
      .then(([attackItems, spellItems]) => {
        if (!active) return
        setAttacks(attackItems)
        setAttackRef(attackItems[0]?.source_ref ?? '')
        setSpells(spellItems)
        setSpellRef(spellItems[0]?.spell_ref ?? '')
        setSlotLevel(spellItems[0]?.castable_slot_levels[0] ?? null)
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
  const selectedSpell = spells.find((spell) => spell.spell_ref === spellRef) ?? null
  const castTargetEntries = spellTargetEntries(selectedSpell, actingEntry, targetEntries)
  const hasAttackEconomy = Boolean(
    actingEntry &&
    actingEntry.action_available &&
    actingEntry.attacks_used < actingEntry.attacks_allowed,
  )
  const formDisabled = pending || !hasAttackEconomy

  const clearActionForm = () => {
    setAttackRef(attacks[0]?.source_ref ?? '')
    setSpellRef(spells[0]?.spell_ref ?? '')
    setSlotLevel(spells[0]?.castable_slot_levels[0] ?? null)
    setTargetEntryId('')
    setModifierMode('normal')
    setRangeConfirmed(true)
  }

  const handleSpellRefChange = (nextSpellRef: string) => {
    setSpellRef(nextSpellRef)
    const spell = spells.find((item) => item.spell_ref === nextSpellRef)
    setSlotLevel(spell?.castable_slot_levels[0] ?? null)
    setTargetEntryId('')
  }

  const handleRequestAction = async (event: React.FormEvent) => {
    event.preventDefault()
    if (currentActingEntryId === null || !hasAttackEconomy) return
    if (actionKind === 'attack' && (!targetEntryId || !attackRef)) return
    if (isSpecialAttackKind(actionKind) && !targetEntryId) return
    if (actionKind === 'spell') {
      if (!selectedSpell) return
      if (selectedSpell.targeting === 'single' && !targetEntryId) return
    }

    await runCombatMutation(
      setPending,
      async () => {
        setRollResult(null)
        setSpellStatus(null)
        if (actionKind === 'attack') {
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
          if (response.roll_request_id !== null) {
            setLocalRollRequestId(response.roll_request_id)
            setPendingActionId(null)
            setPendingActionSeen(false)
          } else {
            setLocalRollRequestId(null)
            setPendingActionId(response.action_id)
            setPendingActionSeen(false)
            clearActionForm()
          }
          return
        }

        if (actionKind === 'spell') {
          if (!selectedSpell) return
          const selectedSlotLevel = slotLevel ?? selectedSpell.castable_slot_levels[0] ?? null
          if (selectedSpell.targeting === 'aoe') {
            const response = await proposeAoeSpell(
              roomId,
              campaignId,
              sessionId,
              {
                caster_entry_id: currentActingEntryId,
                spell_ref: selectedSpell.spell_ref,
                slot_level: selectedSlotLevel,
                ...(selectedSpell.profile_id ? { profile_id: selectedSpell.profile_id } : {}),
                proposed_target_ids: targetEntries.map((entry) => entry.id),
                idempotency_key: requestId('aoe-propose'),
              },
              token,
            )
            setLocalRollRequestId(null)
            setPendingActionId(response.action_id)
            setPendingActionSeen(false)
            clearActionForm()
            return
          }

          const response = await castSpell(
            roomId,
            campaignId,
            sessionId,
            {
              caster_entry_id: currentActingEntryId,
              target_entry_id: selectedSpell.targeting === 'self' ? null : targetEntryId,
              spell_ref: selectedSpell.spell_ref,
              slot_level: selectedSlotLevel,
              ...(selectedSpell.profile_id ? { profile_id: selectedSpell.profile_id } : {}),
              attack_mode: modifierMode,
              idempotency_key: requestId('spell-cast'),
            },
            token,
          )
          setPendingActionId(null)
          setPendingActionSeen(false)
          if (response.roll_request_id !== null) {
            setLocalRollRequestId(response.roll_request_id)
          } else {
            setLocalRollRequestId(null)
            setSpellStatus({ castMode: response.cast_mode, status: response.status })
            clearActionForm()
          }
          return
        }

        const response = await requestSpecialAttack(
          roomId,
          campaignId,
          sessionId,
          {
            attacker_entry_id: currentActingEntryId,
            target_entry_id: targetEntryId,
            kind: actionKind,
            attacker_modifier_mode: modifierMode,
            idempotency_key: requestId('special-attack'),
          },
          token,
        )
        setLocalRollRequestId(null)
        if (response.attacker_roll_request_id !== null) {
          setPendingActionId(null)
          setPendingActionSeen(false)
        } else {
          setPendingActionId(response.action_id)
          setPendingActionSeen(false)
        }
        clearActionForm()
      },
      refresh,
      onError,
    )
  }

  const resolveWindow = (window: ReactionWindowView, actorEntryId: string, accept: boolean) =>
    runCombatMutation(
      setPending,
      async () => {
        await resolveReaction(
          roomId,
          campaignId,
          sessionId,
          {
            owner_entry_id: window.entry_id,
            actor_entry_id: actorEntryId,
            accept,
            idempotency_key: requestId('reaction'),
          },
          token,
        )
      },
      refresh,
      onError,
    )

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
      if (localRollRequestId === rollRequestId) setLocalRollRequestId(null)
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
    escape_grapple: async (rollRequestId) => {
      await rollSpecialAttack(
        roomId,
        campaignId,
        sessionId,
        rollBody(rollRequestId, 'escape-roll'),
        token,
      )
      setRollResult(null)
    },
  }

  const handlePendingRoll = (requestType: string, rollRequestId: string) => {
    const handler = pendingCombatRollHandler(requestType, rollHandlers)
    if (!handler) return Promise.resolve()
    // A fresh roll replaces whatever result line is showing, including a resolved spell cast.
    setSpellStatus(null)
    return runCombatMutation(setPending, () => handler(rollRequestId), refresh, onError)
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
      case 'escape_grapple':
        return copy.combatRollTypeEscapeGrapple
      default:
        return requestType
    }
  }

  const spellModeLabel = (castMode: string): string => {
    switch (castMode) {
      case 'attack':
        return copy.combatSpellModeAttack
      case 'save':
        return copy.combatSpellModeSave
      case 'heal':
        return copy.combatSpellModeHeal
      default:
        return copy.combatSpellModeUtility
    }
  }

  const pendingRows = pendingRolls.filter(
    (roll) => roll.request_type !== 'initiative' && roll.id !== localRollRequestId,
  )
  const eligibleWindows = reactionWindows.flatMap((window) => {
    const actorEntryId = eligibleReactionEntry(window, reactionEntryIds)
    return actorEntryId === null ? [] : [{ window, actorEntryId }]
  })

  const actionState =
    currentActingEntryId === null
      ? 'waiting'
      : pendingActionId !== null
        ? 'adjudication-pending'
        : 'ready'

  const attackResultStatus =
    rollResult?.kind === 'attack'
      ? rollResult.value.critical
        ? copy.combatAttackCritical
        : rollResult.value.hit
          ? copy.combatAttackHit
          : copy.combatAttackMiss
      : null

  const submitLabel =
    actionKind === 'attack'
      ? copy.combatRequestAttack
      : actionKind === 'grapple'
        ? copy.combatActionKindGrapple
        : actionKind === 'shove_prone'
          ? copy.combatActionKindShoveProne
          : actionKind === 'shove_push'
            ? copy.combatActionKindShovePush
            : actionKind === 'escape_grapple'
              ? copy.combatActionKindEscapeGrapple
              : copy.combatCastSpell
  const submitDisabled =
    formDisabled ||
    (actionKind === 'attack' && (!targetEntryId || !attackRef)) ||
    (isSpecialAttackKind(actionKind) && !targetEntryId) ||
    (actionKind === 'spell' &&
      (!selectedSpell || (selectedSpell.targeting === 'single' && !targetEntryId)))

  return (
    <section
      className="session-combat-actions"
      data-combat-action-bar="true"
      data-combat-action-state={actionState}
    >
      <h3 className="session-combat__section-heading">{copy.combatActionBarHeading}</h3>

      {eligibleWindows.length > 0 ? (
        <div className="session-combat-actions__reactions" data-combat-reactions="true">
          <h4 className="session-combat__sub-heading">{copy.combatReactionsHeading}</h4>
          {eligibleWindows.map(({ window, actorEntryId }) => {
            const sourceName = window.source_entry_id
              ? (combat.entries.find((entry) => entry.id === window.source_entry_id)
                  ?.display_name ?? copy.combatUnknownCombatant)
              : copy.combatUnknownCombatant
            const payload = window.safe_payload ? Object.entries(window.safe_payload) : []
            return (
              <article key={window.window_id} className="session-combat-actions__reaction-row">
                <div>
                  <strong>{reactionKindLabel(window.kind, copy)}</strong>
                  {' · '}
                  {window.reason}
                  {' · '}
                  {sourceName}
                </div>
                {payload.length > 0 ? (
                  <div className="session-combat-actions__reaction-payload">
                    {payload.map(([key, value]) => (
                      <span key={key}>
                        {key}: {payloadValue(value)}
                      </span>
                    ))}
                  </div>
                ) : null}
                <div className="session-combat__form-actions">
                  <button
                    type="button"
                    className="button primary compact"
                    data-reaction-window={window.window_id}
                    disabled={pending}
                    onClick={() => void resolveWindow(window, actorEntryId, true)}
                  >
                    {copy.combatReactionAccept}
                  </button>
                  <button
                    type="button"
                    className="button secondary compact"
                    data-reaction-window={window.window_id}
                    disabled={pending}
                    onClick={() => void resolveWindow(window, actorEntryId, false)}
                  >
                    {copy.combatReactionDecline}
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      ) : null}

      {currentActingEntryId === null ? (
        <p className="session-combat-actions__waiting">
          {copy.combatWaitingForTurn.replace('{name}', currentTurnName)}
        </p>
      ) : pendingActionId !== null ? (
        <p className="session-combat-actions__waiting">{copy.combatAwaitingAdjudication}</p>
      ) : (
        <form
          className="session-combat__form session-combat-actions__form"
          onSubmit={handleRequestAction}
        >
          <div className="session-combat__form-row">
            <label>
              <span>{copy.combatActionKindLabel}</span>
              <select
                data-combat-action-kind="true"
                value={actionKind}
                disabled={formDisabled}
                onChange={(event) => {
                  const value = event.target.value
                  const next: ActionKind = isActionKind(value) ? value : 'attack'
                  setActionKind(next)
                  setTargetEntryId('')
                }}
              >
                <option value="attack">{copy.combatActionKindAttack}</option>
                <option value="grapple">{copy.combatActionKindGrapple}</option>
                <option value="shove_prone">{copy.combatActionKindShoveProne}</option>
                <option value="shove_push">{copy.combatActionKindShovePush}</option>
                {actingIsGrappled ? (
                  <option value="escape_grapple">{copy.combatActionKindEscapeGrapple}</option>
                ) : null}
                <option value="spell">{copy.combatActionKindSpell}</option>
              </select>
            </label>
            {actionKind === 'attack' ? (
              <label>
                <span>{copy.combatAttackLabel}</span>
                <select
                  value={attackRef}
                  disabled={formDisabled}
                  onChange={(event) => setAttackRef(event.target.value)}
                >
                  {attacks.map((attack) => (
                    <option
                      key={attack.source_ref}
                      value={attack.source_ref}
                    >{`${attack.name} (+${attack.attack_bonus})`}</option>
                  ))}
                </select>
              </label>
            ) : actionKind === 'spell' ? (
              <SpellActionFields
                spells={spells}
                spellRef={spellRef}
                slotLevel={slotLevel}
                targetEntryId={targetEntryId}
                targetEntries={castTargetEntries}
                disabled={formDisabled}
                copy={copy}
                onSpellRefChange={handleSpellRefChange}
                onSlotLevelChange={setSlotLevel}
                onTargetEntryIdChange={setTargetEntryId}
              />
            ) : (
              <label>
                <span>{copy.combatTargetLabel}</span>
                <select
                  value={targetEntryId}
                  disabled={formDisabled}
                  onChange={(event) => setTargetEntryId(event.target.value)}
                >
                  <option value="">—</option>
                  {targetEntries.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.display_name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {actionKind === 'attack' ? (
              <label>
                <span>{copy.combatTargetLabel}</span>
                <select
                  value={targetEntryId}
                  disabled={formDisabled}
                  onChange={(event) => setTargetEntryId(event.target.value)}
                >
                  <option value="">—</option>
                  {targetEntries.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.display_name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
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
          {isCurrentDm && actionKind === 'attack' ? (
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
              disabled={submitDisabled}
            >
              {pending ? copy.sending : submitLabel}
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
                {roll.request_type === 'saving_throw' && roll.ability_ref
                  ? ` · ${roll.ability_ref}`
                  : ''}
                {roll.request_type === 'saving_throw' && typeof roll.dc === 'number'
                  ? ` · DC ${roll.dc}`
                  : ''}
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

      {spellStatus ? (
        <p className="session-combat-actions__result" data-spell-result="true">
          {copy.combatSpellResolved} · {spellModeLabel(spellStatus.castMode)} · {spellStatus.status}
        </p>
      ) : rollResult?.kind === 'attack' && attackResultStatus ? (
        <p className="session-combat-actions__result" data-attack-result="true">
          <strong>{attackResultStatus}</strong>
          {' · '}
          {copy.combatAttackDamage.replace('{damage}', String(rollResult.value.damage_total))}
          {typeof rollResult.value.after_hp === 'number' ? (
            <>
              {' '}
              · {copy.combatHp}: {rollResult.value.after_hp}
            </>
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
