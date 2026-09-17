import { useState } from 'react'

import {
  adjudicateAttackRange,
  adjudicateSpecialAttack,
  resolveAdjudication,
  type CombatAdjudicationView,
  type CombatDetailView,
} from '../../api/combat'
import { adjudicationKindLabel, runCombatMutation } from './sessionCombat'
import type { SessionCopy } from './sessionCopy'
import { requestId } from './SessionTableSurface'

type SessionCombatAdjudicationPanelProps = {
  combat: CombatDetailView
  adjudications: CombatAdjudicationView[]
  copy: SessionCopy
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  onError: (cause: unknown) => void
  refresh: () => void
}

type RollModeChoice = '' | 'normal' | 'advantage' | 'disadvantage'

function hintValue(value: unknown): string {
  if (value === null) return 'null'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value) ?? ''
}

export function SessionCombatAdjudicationPanel({
  combat,
  adjudications,
  copy,
  roomId,
  campaignId,
  sessionId,
  token,
  onError,
  refresh,
}: SessionCombatAdjudicationPanelProps) {
  const [pending, setPending] = useState(false)
  const [rangeModes, setRangeModes] = useState<Record<string, RollModeChoice>>({})
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [rulings, setRulings] = useState<Record<string, string>>({})

  const entryName = (entryId: string): string =>
    combat.entries.find((entry) => entry.id === entryId)?.display_name ?? copy.combatUnknownCombatant

  const runMutation = (mutation: () => Promise<void>) =>
    runCombatMutation(setPending, mutation, refresh, onError)

  const resolveRange = (item: CombatAdjudicationView, inRange: boolean) =>
    runMutation(async () => {
      const rollMode = rangeModes[item.action_id] ?? ''
      const note = (notes[item.action_id] ?? '').trim()
      await adjudicateAttackRange(
        roomId,
        campaignId,
        sessionId,
        {
          action_id: item.action_id,
          in_range: inRange,
          ...(rollMode ? { roll_mode: rollMode } : {}),
          ...(note ? { note } : {}),
          idempotency_key: requestId('attack-adjudicate'),
        },
        token,
      )
    })

  const resolveReach = (item: CombatAdjudicationView, inReach: boolean) =>
    runMutation(async () => {
      await adjudicateSpecialAttack(
        roomId,
        campaignId,
        sessionId,
        {
          action_id: item.action_id,
          in_reach: inReach,
          idempotency_key: requestId('reach-adjudicate'),
        },
        token,
      )
    })

  const resolveOpportunityAttack = (item: CombatAdjudicationView, trigger: boolean) =>
    runMutation(async () => {
      await resolveAdjudication(
        roomId,
        campaignId,
        sessionId,
        item.action_id,
        { trigger, idempotency_key: requestId('oa-adjudicate') },
        token,
      )
    })

  const resolveSpecial = (item: CombatAdjudicationView) => {
    const ruling = (rulings[item.action_id] ?? '').trim()
    if (!ruling) return Promise.resolve()
    return runMutation(async () => {
      await resolveAdjudication(
        roomId,
        campaignId,
        sessionId,
        item.action_id,
        { ruling, idempotency_key: requestId('special-adjudicate') },
        token,
      )
    })
  }

  return (
    <section className="session-combat-adjudications" data-combat-adjudications="true">
      <h3 className="session-combat__section-heading">{copy.combatAdjudicationPanelHeading}</h3>
      {adjudications.length === 0 ? (
        <p className="session-combat__empty">{copy.combatAdjudicationEmpty}</p>
      ) : (
        <div className="session-combat-adjudications__list">
          {adjudications.map((item) => {
            const targets = item.proposed_target_entry_ids.map(entryName)
            const ruling = rulings[item.action_id] ?? ''
            return (
              <article key={item.action_id} className="session-combat-adjudications__row" data-adjudication-kind={item.kind} data-adjudication-id={item.action_id}>
                <div className="session-combat-adjudications__summary">
                  <strong>{adjudicationKindLabel(item.kind, copy)}</strong>
                  <span>{entryName(item.subject_entry_id)}</span>
                  {targets.length > 0 ? <span>→ {targets.join(', ')}</span> : null}
                </div>

                {item.question ? <p>{item.question}</p> : null}

                {item.dm_hints ? (
                  <dl className="session-combat-adjudications__hints">
                    {Object.entries(item.dm_hints).map(([key, value]) => (
                      <div key={key}><dt>{key}</dt><dd>{hintValue(value)}</dd></div>
                    ))}
                  </dl>
                ) : null}

                {item.kind === 'range' ? (
                  <div className="session-combat-adjudications__controls">
                    <div className="session-combat__form-row">
                      <label>
                        <span>{copy.checkModifier}</span>
                        <select
                          value={rangeModes[item.action_id] ?? ''}
                          disabled={pending}
                          onChange={(event) => {
                            const value = event.target.value
                            const next: RollModeChoice = value === 'normal'
                              ? 'normal'
                              : value === 'advantage'
                                ? 'advantage'
                                : value === 'disadvantage'
                                  ? 'disadvantage'
                                  : ''
                            setRangeModes((current) => ({ ...current, [item.action_id]: next }))
                          }}
                        >
                          <option value="">—</option>
                          <option value="normal">{copy.checkNormal}</option>
                          <option value="advantage">{copy.checkAdvantage}</option>
                          <option value="disadvantage">{copy.checkDisadvantage}</option>
                        </select>
                      </label>
                      <label>
                        <span>{copy.combatAdjudicationNote}</span>
                        <input type="text" value={notes[item.action_id] ?? ''} maxLength={500} disabled={pending} onChange={(event) => setNotes((current) => ({ ...current, [item.action_id]: event.target.value }))} />
                      </label>
                    </div>
                    <div className="session-combat__form-actions">
                      <button type="button" className="button primary compact" disabled={pending} onClick={() => void resolveRange(item, true)}>{copy.combatInRange}</button>
                      <button type="button" className="button secondary compact" disabled={pending} onClick={() => void resolveRange(item, false)}>{copy.combatOutOfRange}</button>
                    </div>
                  </div>
                ) : item.kind === 'reach' ? (
                  <div className="session-combat__form-actions">
                    <button type="button" className="button primary compact" disabled={pending} onClick={() => void resolveReach(item, true)}>{copy.combatInReach}</button>
                    <button type="button" className="button secondary compact" disabled={pending} onClick={() => void resolveReach(item, false)}>{copy.combatOutOfReach}</button>
                  </div>
                ) : item.kind === 'opportunity_attack' ? (
                  <div className="session-combat__form-actions">
                    <button type="button" className="button primary compact" disabled={pending} onClick={() => void resolveOpportunityAttack(item, true)}>{copy.combatTrigger}</button>
                    <button type="button" className="button secondary compact" disabled={pending} onClick={() => void resolveOpportunityAttack(item, false)}>{copy.combatNoTrigger}</button>
                  </div>
                ) : item.kind === 'special' ? (
                  <div className="session-combat-adjudications__controls">
                    <label>
                      <span>{copy.combatRuling}</span>
                      <textarea value={ruling} maxLength={1000} required disabled={pending} onChange={(event) => setRulings((current) => ({ ...current, [item.action_id]: event.target.value }))} />
                    </label>
                    <div className="session-combat__form-actions">
                      <button type="button" className="button primary compact" disabled={pending || !ruling.trim()} onClick={() => void resolveSpecial(item)}>{copy.combatResolve}</button>
                    </div>
                  </div>
                ) : null}
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}
