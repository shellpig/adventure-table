import { useMemo, useState } from 'react'

import type { CombatDetailView, CombatEntryView, CombatantDetailView } from '../../api/combat'
import { conditionLabel, rollInitiative } from '../../api/combat'
import type { TableEvent } from '../../api/sessions'
import { SessionCombatActionBar } from './SessionCombatActionBar'
import { SessionCombatAdjudicationPanel } from './SessionCombatAdjudicationPanel'
import { SessionCombatDmControls } from './SessionCombatDmControls'
import {
  combatantFor,
  combatInjuryLabel,
  orderedEntries,
  useMonsterOptions,
  usePendingAdjudications,
  usePendingCombatRolls,
  useReactionWindows,
} from './sessionCombat'
import type { SessionCopy } from './sessionCopy'
import { requestId } from './SessionTableSurface'

type SessionCombatStageProps = {
  combat: CombatDetailView
  myEntryIds: string[]
  copy: SessionCopy
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  events: TableEvent[]
  isCurrentDm: boolean
  onError: (cause: unknown) => void
  refresh: () => void
}

function getStatusLabel(status: string, copy: SessionCopy): string {
  switch (status) {
    case 'active': return copy.combatStatusActive
    case 'withdrawn': return copy.combatStatusWithdrawn
    case 'down': return copy.combatStatusDown
    case 'dead': return copy.combatStatusDead
    case 'removed': return copy.combatStatusRemoved
    default: return status
  }
}

export function SessionCombatStage({
  combat,
  myEntryIds,
  copy,
  roomId,
  campaignId,
  sessionId,
  token,
  events,
  isCurrentDm,
  onError,
  refresh,
}: SessionCombatStageProps) {
  const monsterOptions = useMonsterOptions(isCurrentDm)
  const [rollingEntryId, setRollingEntryId] = useState<string | null>(null)
  const { rolls, refresh: refreshRolls } = usePendingCombatRolls({ roomId, campaignId, sessionId, token, events, onError })
  const { adjudications, refresh: refreshAdjudications } = usePendingAdjudications({
    roomId,
    campaignId,
    sessionId,
    token,
    events,
    onError,
    enabled: combat.status === 'running',
  })
  const reactionEntryIds = useMemo(
    () => combat.status === 'running'
      ? isCurrentDm
        ? combat.entries.filter((entry) => entry.status === 'active').map((entry) => entry.id)
        : myEntryIds
      : [],
    [combat.status, combat.entries, isCurrentDm, myEntryIds],
  )
  const { windows: reactionWindows, refresh: refreshReactions } = useReactionWindows({
    roomId,
    campaignId,
    sessionId,
    token,
    events,
    onError,
    entryIds: reactionEntryIds,
  })

  const refreshCombatResources = () => {
    refresh()
    refreshRolls()
    refreshAdjudications()
    refreshReactions()
  }

  const roundText = typeof combat.round_number === 'number'
    ? copy.combatRound.replace('{round}', String(combat.round_number))
    : copy.combatPreInitiative
  const currentTurnEntry = combat.current_turn_entry_id
    ? combat.entries.find((entry) => entry.id === combat.current_turn_entry_id)
    : null
  const currentTurnName = currentTurnEntry ? currentTurnEntry.display_name : '-'
  const isMyTurn = Boolean(combat.current_turn_entry_id && myEntryIds.includes(combat.current_turn_entry_id))
  const entries = orderedEntries(combat)
  const combatantEntries: Array<{ entry: CombatEntryView; combatant: CombatantDetailView }> = []
  for (const entry of entries) {
    const combatant = combatantFor(combat, entry.id)
    if (combatant) combatantEntries.push({ entry, combatant })
  }

  const handleRollInitiative = async (entry: CombatEntryView) => {
    if (!entry.initiative_roll_request_id) return
    setRollingEntryId(entry.id)
    try {
      await rollInitiative(
        roomId,
        campaignId,
        sessionId,
        {
          roll_request_id: entry.initiative_roll_request_id,
          source: 'server',
          idempotency_key: requestId('roll-init'),
        },
        token,
      )
      refresh()
    } catch (cause) {
      onError(cause)
    } finally {
      setRollingEntryId(null)
    }
  }

  return (
    <section className="session-combat" aria-label={copy.combatTitle}>
      <header className="session-combat__header" data-combat-round={combat.round_number ?? 'pre-initiative'} data-combat-current-turn={currentTurnName}>
        <div className="session-combat__round-indicator"><span className="session-combat__round-badge">{roundText}</span></div>
        <div className="session-combat__turn-indicator">
          <span className="session-combat__turn-label">{copy.combatCurrentTurn}:</span>
          <span className="session-combat__turn-name">{currentTurnName}</span>
          {isMyTurn ? <span className="session-combat__your-turn-badge">{copy.combatYourTurn}</span> : null}
        </div>
      </header>

      {isCurrentDm ? (
        <SessionCombatDmControls
          combat={combat}
          copy={copy}
          roomId={roomId}
          campaignId={campaignId}
          sessionId={sessionId}
          token={token}
          monsterOptions={monsterOptions}
          onError={onError}
          refresh={refresh}
        />
      ) : null}

      <div className="session-combat__initiative">
        <h3 className="session-combat__section-heading">{copy.combatInitiativeHeading}</h3>
        <ol className="session-combat__initiative-list">
          {entries.map((entry) => {
            const combatant = combatantFor(combat, entry.id)
            const isHostile = combatant ? combatant.is_hostile : entry.subject_kind === 'monster'
            const isCurrent = entry.id === combat.current_turn_entry_id
            const turnOrderText = typeof entry.turn_order === 'number' ? String(entry.turn_order) : copy.combatAwaitingInitiative
            const hasInitTotal = typeof entry.initiative_total === 'number'
            const isInactive = entry.status !== 'active'
            const canRollInitiative = entry.initiative_roll_request_id !== null && entry.initiative_roll_result_id === null && (isCurrentDm || myEntryIds.includes(entry.id))
            return (
              <li key={entry.id} className={`session-combat__initiative-row${isCurrent ? ' session-combat__initiative-row--current' : ''}${isHostile ? ' session-combat__initiative-row--hostile' : ''}`} aria-current={isCurrent ? 'true' : undefined} data-combat-entry={entry.id}>
                <span className="session-combat__turn-order">{turnOrderText}</span>
                <span className="session-combat__entry-name">{entry.display_name}</span>
                {hasInitTotal ? <span className="session-combat__initiative-total">{entry.initiative_total}</span> : null}
                {canRollInitiative ? (
                  <button type="button" className="button secondary compact session-combat__roll-init-btn" data-initiative-roll={entry.id} disabled={rollingEntryId === entry.id} onClick={() => void handleRollInitiative(entry)}>
                    {rollingEntryId === entry.id ? copy.combatRollingInitiative : copy.combatRollInitiative}
                  </button>
                ) : null}
                {isHostile ? <span className="session-combat__hostile-badge">{copy.combatHostile}</span> : null}
                {isInactive ? <span className="session-combat__status-badge">{getStatusLabel(entry.status, copy)}</span> : null}
              </li>
            )
          })}
        </ol>
      </div>

      <div className="session-combat__combatants">
        <h3 className="session-combat__section-heading">{copy.combatantsHeading}</h3>
        {combatantEntries.length === 0 ? (
          <p className="session-combat__empty">{copy.combatNoCombatants}</p>
        ) : (
          <div className="session-combat__cards-grid">
            {combatantEntries.map(({ entry, combatant }) => {
              const proj = combatant.projection
              const isHostile = combatant.is_hostile
              const conditions = proj.conditions.map(conditionLabel).filter((label) => label.length > 0)
              let hpDisplay: string | null = null
              if (typeof proj.current_hp === 'number') {
                hpDisplay = typeof proj.max_hp === 'number' ? `${proj.current_hp}/${proj.max_hp}` : `${proj.current_hp}`
                if (typeof proj.temp_hp === 'number' && proj.temp_hp > 0) hpDisplay += ` (+${proj.temp_hp})`
              }
              const hasAc = typeof proj.armor_class === 'number'
              const hasPositionNote = typeof proj.position_note === 'string' && proj.position_note.trim().length > 0
              const hasDmNotes = typeof proj.dm_notes === 'string' && proj.dm_notes.trim().length > 0
              return (
                <div key={entry.id} className={`session-combat__card${isHostile ? ' session-combat__card--hostile' : ''}`} data-combat-entry={entry.id} data-hostile={isHostile ? 'true' : undefined}>
                  <div className="session-combat__card-header">
                    <span className="session-combat__card-name">{proj.name || entry.display_name}</span>
                    {isHostile ? <span className="session-combat__hostile-badge">{copy.combatHostile}</span> : null}
                  </div>
                  <div className="session-combat__economy">
                    <span className={`session-combat__economy-pill${entry.action_available ? ' session-combat__economy-pill--available' : ''}`}>{copy.combatActionShort}</span>
                    <span className={`session-combat__economy-pill${entry.bonus_action_available ? ' session-combat__economy-pill--available' : ''}`}>{copy.combatBonusActionShort}</span>
                    <span className={`session-combat__economy-pill${entry.reaction_available ? ' session-combat__economy-pill--available' : ''}`}>{copy.combatReactionShort}</span>
                    {entry.attacks_allowed > 1 ? <span className="session-combat__attacks">{entry.attacks_used}/{entry.attacks_allowed} {copy.combatAttacks}</span> : null}
                  </div>
                  <div className="session-combat__stats-row">
                    {hpDisplay !== null ? <span className="session-combat__stat"><span className="session-combat__stat-label">{copy.combatHp}:</span><span>{hpDisplay}</span></span> : null}
                    {hasAc ? <span className="session-combat__stat"><span className="session-combat__stat-label">{copy.combatAc}:</span><span>{proj.armor_class}</span></span> : null}
                    {proj.injury_level ? <span className="session-combat__stat"><span className="session-combat__injury-badge">{combatInjuryLabel(proj.injury_level, copy)}</span></span> : null}
                  </div>
                  {conditions.length > 0 ? <div className="session-combat__conditions">{conditions.map((conditionName, index) => <span key={`${conditionName}-${index}`} className="session-combat__condition-pill">{conditionName}</span>)}</div> : null}
                  {hasPositionNote ? <div className="session-combat__position-note"><span className="session-combat__stat-label">{copy.combatPositionNote}:</span><span>{proj.position_note}</span></div> : null}
                  {hasDmNotes ? <div className="session-combat__dm-notes"><span className="session-combat__stat-label">{copy.combatDmNotes}:</span><span>{proj.dm_notes}</span></div> : null}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {combat.status === 'running' ? (
        <>
          <SessionCombatActionBar
            combat={combat}
            myEntryIds={myEntryIds}
            pendingRolls={rolls}
            pendingAdjudications={adjudications}
            reactionEntryIds={reactionEntryIds}
            reactionWindows={reactionWindows}
            copy={copy}
            roomId={roomId}
            campaignId={campaignId}
            sessionId={sessionId}
            token={token}
            isCurrentDm={isCurrentDm}
            onError={onError}
            refresh={refreshCombatResources}
          />
          {isCurrentDm ? (
            <SessionCombatAdjudicationPanel
              combat={combat}
              adjudications={adjudications}
              copy={copy}
              roomId={roomId}
              campaignId={campaignId}
              sessionId={sessionId}
              token={token}
              onError={onError}
              refresh={refreshCombatResources}
            />
          ) : null}
        </>
      ) : null}
    </section>
  )
}
