import type { RollModifierMode, RollRequestType, RollRequestView } from '../../api/p3c'
import type { TableEvent } from '../../api/sessions'
import type { SessionCopy } from './sessionCopy'

export function formatRequestType(type: RollRequestType, copy: SessionCopy): string {
  switch (type) {
    case 'ability': return copy.checkAbilityType
    case 'skill': return copy.checkSkillType
    case 'saving_throw': return copy.checkSaveType
    case 'other': return copy.checkOtherType
    default: return type
  }
}

export function formatTargetRef(
  request: Pick<RollRequestView, 'skill_ref' | 'ability_ref'>,
  copy: SessionCopy,
): string | null {
  if (request.skill_ref) {
    const map: Record<string, string> = {
      'srd5.1:skill:acrobatics': copy.skillAcrobatics,
      'srd5.1:skill:animal-handling': copy.skillAnimalHandling,
      'srd5.1:skill:arcana': copy.skillArcana,
      'srd5.1:skill:athletics': copy.skillAthletics,
      'srd5.1:skill:deception': copy.skillDeception,
      'srd5.1:skill:history': copy.skillHistory,
      'srd5.1:skill:insight': copy.skillInsight,
      'srd5.1:skill:intimidation': copy.skillIntimidation,
      'srd5.1:skill:investigation': copy.skillInvestigation,
      'srd5.1:skill:medicine': copy.skillMedicine,
      'srd5.1:skill:nature': copy.skillNature,
      'srd5.1:skill:perception': copy.skillPerception,
      'srd5.1:skill:performance': copy.skillPerformance,
      'srd5.1:skill:persuasion': copy.skillPersuasion,
      'srd5.1:skill:religion': copy.skillReligion,
      'srd5.1:skill:sleight-of-hand': copy.skillSleightOfHand,
      'srd5.1:skill:stealth': copy.skillStealth,
      'srd5.1:skill:survival': copy.skillSurvival,
    }
    return map[request.skill_ref] ?? request.skill_ref
  }
  if (request.ability_ref) {
    const map: Record<string, string> = {
      'srd5.1:ability:str': copy.abilityStr,
      'srd5.1:ability:dex': copy.abilityDex,
      'srd5.1:ability:con': copy.abilityCon,
      'srd5.1:ability:int': copy.abilityInt,
      'srd5.1:ability:wis': copy.abilityWis,
      'srd5.1:ability:cha': copy.abilityCha,
    }
    return map[request.ability_ref] ?? request.ability_ref
  }
  return null
}

export function formatModifierMode(mode: RollModifierMode, copy: SessionCopy): string {
  switch (mode) {
    case 'advantage': return copy.checkAdvantage
    case 'disadvantage': return copy.checkDisadvantage
    case 'normal':
    default:
      return copy.checkNormal
  }
}

function template(source: string, values: Record<string, string>): string {
  return Object.entries(values).reduce(
    (result, [key, value]) => result.replaceAll(`{${key}}`, value),
    source,
  )
}

export function isRollRequestEvent(event: TableEvent): boolean {
  return event.kind === 'roll.requested'
}

export function formatRollRequestPrompt(
  event: TableEvent,
  targetLabels: string[],
  copy: SessionCopy,
): string {
  const requestType = event.payload.request_type
  const modifierMode = event.payload.modifier_mode
  const flatAdjustment = event.payload.flat_adjustment
  const skillRef = event.payload.skill_ref
  const abilityRef = event.payload.ability_ref
  const label = event.payload.label

  const type = typeof requestType === 'string'
    ? formatRequestType(requestType as RollRequestType, copy)
    : copy.checkOtherType
  const ref = formatTargetRef({
    skill_ref: typeof skillRef === 'string' ? skillRef : null,
    ability_ref: typeof abilityRef === 'string' ? abilityRef : null,
  }, copy)
  const check = ref ? template(copy.rollPromptCheckWithRef, { ref, type }) : type
  const details: string[] = []
  if (modifierMode === 'advantage' || modifierMode === 'disadvantage') {
    details.push(formatModifierMode(modifierMode, copy))
  }
  if (typeof flatAdjustment === 'number' && flatAdjustment !== 0) {
    details.push(template(copy.rollPromptAdjustment, {
      adjustment: `${flatAdjustment > 0 ? '+' : ''}${flatAdjustment}`,
    }))
  }

  return template(copy.rollPrompt, {
    targets: targetLabels.join(copy.rollPromptTargetSeparator),
    check,
    details: details.length > 0
      ? template(copy.rollPromptDetails, { details: details.join(copy.rollPromptDetailSeparator) })
      : '',
    label: typeof label === 'string' && label.trim()
      ? template(copy.rollPromptLabel, { label: label.trim() })
      : '',
  })
}
