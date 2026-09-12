import { useEffect, useMemo, useState } from 'react'

import {
  requestCheck,
  type RequestCheckInput,
  type RollModifierMode,
  type RollRequestType,
  type RollVisibility,
} from '../../api/p3c'
import type { SessionCopy } from './sessionCopy'
import type { CheckIntent } from './sessionCheckIntent'

const ABILITIES = [
  ['srd5.1:ability:str', 'STR'],
  ['srd5.1:ability:dex', 'DEX'],
  ['srd5.1:ability:con', 'CON'],
  ['srd5.1:ability:int', 'INT'],
  ['srd5.1:ability:wis', 'WIS'],
  ['srd5.1:ability:cha', 'CHA'],
] as const

const SKILLS = [
  'acrobatics', 'animal-handling', 'arcana', 'athletics', 'deception', 'history',
  'insight', 'intimidation', 'investigation', 'medicine', 'nature', 'perception',
  'performance', 'persuasion', 'religion', 'sleight-of-hand', 'stealth', 'survival',
] as const

function getAbilityOptions(copy: SessionCopy) {
  return [
    ['srd5.1:ability:str', copy.abilityStr],
    ['srd5.1:ability:dex', copy.abilityDex],
    ['srd5.1:ability:con', copy.abilityCon],
    ['srd5.1:ability:int', copy.abilityInt],
    ['srd5.1:ability:wis', copy.abilityWis],
    ['srd5.1:ability:cha', copy.abilityCha],
  ] as const
}

function getSkillOptions(copy: SessionCopy) {
  return [
    ['srd5.1:skill:acrobatics', copy.skillAcrobatics],
    ['srd5.1:skill:animal-handling', copy.skillAnimalHandling],
    ['srd5.1:skill:arcana', copy.skillArcana],
    ['srd5.1:skill:athletics', copy.skillAthletics],
    ['srd5.1:skill:deception', copy.skillDeception],
    ['srd5.1:skill:history', copy.skillHistory],
    ['srd5.1:skill:insight', copy.skillInsight],
    ['srd5.1:skill:intimidation', copy.skillIntimidation],
    ['srd5.1:skill:investigation', copy.skillInvestigation],
    ['srd5.1:skill:medicine', copy.skillMedicine],
    ['srd5.1:skill:nature', copy.skillNature],
    ['srd5.1:skill:perception', copy.skillPerception],
    ['srd5.1:skill:performance', copy.skillPerformance],
    ['srd5.1:skill:persuasion', copy.skillPersuasion],
    ['srd5.1:skill:religion', copy.skillReligion],
    ['srd5.1:skill:sleight-of-hand', copy.skillSleightOfHand],
    ['srd5.1:skill:stealth', copy.skillStealth],
    ['srd5.1:skill:survival', copy.skillSurvival],
  ] as const
}

export type CheckTargetOption = { seatId: string; label: string }

export type CheckRequestDraft = {
  targetSeatIds: string[]
  requestType: RollRequestType | ''
  abilityRef: string
  skillRef: string
  dc: string
  modifierMode: RollModifierMode
  flatAdjustment: string
  visibility: RollVisibility
  label: string
}

export function buildRequestCheckInput(draft: CheckRequestDraft): RequestCheckInput | null {
  if (draft.targetSeatIds.length === 0 || draft.requestType === '') return null
  if ((draft.requestType === 'ability' || draft.requestType === 'saving_throw') && !draft.abilityRef) return null
  if (draft.requestType === 'skill' && !draft.skillRef) return null
  const dc = draft.dc.trim() === '' ? null : Number(draft.dc)
  const flatAdjustment = draft.flatAdjustment.trim() === '' ? 0 : Number(draft.flatAdjustment)
  if ((dc !== null && (!Number.isInteger(dc) || dc < 0 || dc > 999)) || !Number.isInteger(flatAdjustment)) {
    return null
  }
  return {
    target_seat_ids: draft.targetSeatIds,
    request_type: draft.requestType,
    ability_ref: draft.requestType === 'ability' || draft.requestType === 'saving_throw'
      ? draft.abilityRef
      : null,
    skill_ref: draft.requestType === 'skill' ? draft.skillRef : null,
    dc,
    modifier_mode: draft.modifierMode,
    flat_adjustment: flatAdjustment,
    visibility: draft.visibility,
    label: draft.label.trim() || null,
  }
}

export function SessionCheckRequestPanel({
  roomId,
  campaignId,
  sessionId,
  token,
  targets,
  intent,
  copy,
  onError,
}: {
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  targets: CheckTargetOption[]
  intent: CheckIntent | null
  copy: SessionCopy
  onError: (cause: unknown) => void
}) {
  const [targetSeatIds, setTargetSeatIds] = useState<string[]>(
    intent ? [intent.subject_seat_id] : targets[0] ? [targets[0].seatId] : [],
  )
  const [requestType, setRequestType] = useState<RollRequestType | ''>('')
  const [abilityRef, setAbilityRef] = useState('')
  const [skillRef, setSkillRef] = useState('')
  const [dc, setDc] = useState('')
  const [modifierMode, setModifierMode] = useState<RollModifierMode>('normal')
  const [flatAdjustment, setFlatAdjustment] = useState('0')
  const [visibility, setVisibility] = useState<RollVisibility>('public')
  const [label, setLabel] = useState(intent?.text ?? '')
  const [pending, setPending] = useState(false)
  const [createdCount, setCreatedCount] = useState<number | null>(null)

  useEffect(() => {
    if (!intent) return
    setTargetSeatIds([intent.subject_seat_id])
    setLabel(intent.text)
  }, [intent?.subject_seat_id, intent?.text])

  const draft = useMemo<CheckRequestDraft>(() => ({
    targetSeatIds,
    requestType,
    abilityRef,
    skillRef,
    dc,
    modifierMode,
    flatAdjustment,
    visibility,
    label,
  }), [targetSeatIds, requestType, abilityRef, skillRef, dc, modifierMode, flatAdjustment, visibility, label])
  const payload = useMemo(() => buildRequestCheckInput(draft), [draft])

  const toggleTarget = (seatId: string) => {
    setTargetSeatIds((current) => current.includes(seatId)
      ? current.filter((value) => value !== seatId)
      : [...current, seatId])
  }

  const submit = async () => {
    if (!payload) return
    setPending(true)
    setCreatedCount(null)
    try {
      const response = await requestCheck(
        roomId,
        campaignId,
        sessionId,
        { ...payload, idempotency_key: `check-${globalThis.crypto?.randomUUID?.() ?? Date.now()}` },
        token,
      )
      setCreatedCount(response.requests.length)
    } catch (cause) {
      onError(cause)
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="session-check-request" aria-label={copy.checkRequestTitle}>
      <h3>{copy.checkRequestTitle}</h3>
      {intent ? (
        <div className="session-check-request__intent">
          <strong>{copy.checkIntentLabel}:</strong> {intent.text}
        </div>
      ) : null}

      <fieldset disabled={pending} className="session-check-request__fieldset">
        <legend>{copy.checkTargets}</legend>
        <div className="session-check-request__targets">
          {targets.map((target) => (
            <label key={target.seatId} className="session-check-request__target-chip">
              <input
                type="checkbox"
                checked={targetSeatIds.includes(target.seatId)}
                onChange={() => toggleTarget(target.seatId)}
              />
              <span>{target.label}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="session-form-grid">
        <label className={`session-field ${requestType === '' || requestType === 'other' ? 'full-width' : ''}`}>
          <span>{copy.checkType}</span>
          <select value={requestType} disabled={pending} onChange={(event) => setRequestType(event.target.value as RollRequestType | '')}>
            <option value="">{copy.checkChooseType}</option>
            <option value="ability">{copy.checkAbilityType}</option>
            <option value="skill">{copy.checkSkillType}</option>
            <option value="saving_throw">{copy.checkSaveType}</option>
            <option value="other">{copy.checkOtherType}</option>
          </select>
        </label>

        {requestType === 'ability' || requestType === 'saving_throw' ? (
          <label className="session-field">
            <span>{copy.checkAbility}</span>
            <select value={abilityRef} disabled={pending} onChange={(event) => setAbilityRef(event.target.value)}>
              <option value="">—</option>
              {getAbilityOptions(copy).map(([ref, labelText]) => <option value={ref} key={ref}>{labelText}</option>)}
            </select>
          </label>
        ) : null}

        {requestType === 'skill' ? (
          <label className="session-field">
            <span>{copy.checkSkill}</span>
            <select value={skillRef} disabled={pending} onChange={(event) => setSkillRef(event.target.value)}>
              <option value="">—</option>
              {getSkillOptions(copy).map(([ref, labelText]) => (
                <option value={ref} key={ref}>{labelText}</option>
              ))}
            </select>
          </label>
        ) : null}

        <label className="session-field">
          <span>{copy.checkDc}</span>
          <input type="number" min="0" max="999" value={dc} disabled={pending} placeholder="10" onChange={(event) => setDc(event.target.value)} />
        </label>
        <label className="session-field">
          <span>{copy.checkModifier}</span>
          <select value={modifierMode} disabled={pending} onChange={(event) => setModifierMode(event.target.value as RollModifierMode)}>
            <option value="normal">{copy.checkNormal}</option>
            <option value="advantage">{copy.checkAdvantage}</option>
            <option value="disadvantage">{copy.checkDisadvantage}</option>
          </select>
        </label>
        <label className="session-field">
          <span>{copy.checkAdjustment}</span>
          <input type="number" min="-100" max="100" value={flatAdjustment} disabled={pending} onChange={(event) => setFlatAdjustment(event.target.value)} />
        </label>
        <label className="session-field">
          <span>{copy.checkVisibility}</span>
          <select value={visibility} disabled={pending} onChange={(event) => setVisibility(event.target.value as RollVisibility)}>
            <option value="public">{copy.checkPublic}</option>
            <option value="roller_and_dm">{copy.checkRollerDm}</option>
            <option value="dm_only">{copy.checkDmOnly}</option>
          </select>
        </label>
        <label className="session-field full-width">
          <span>{copy.checkLabel}</span>
          <input value={label} maxLength={160} disabled={pending} placeholder={copy.checkLabelPlaceholder} onChange={(event) => setLabel(event.target.value)} />
        </label>
      </div>

      <button className="button primary session-check-request__submit" type="button" disabled={pending || payload === null} onClick={() => void submit()}>
        {pending ? copy.checkSubmitting : copy.checkSubmit}
      </button>
      {createdCount !== null ? <div className="session-check-request__success" role="status">{copy.checkCreated.replace('{count}', String(createdCount))}</div> : null}
    </section>
  )
}
