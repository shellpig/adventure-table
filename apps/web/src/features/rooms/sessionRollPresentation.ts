import type { RollModifierMode, RollRequestType, RollRequestView } from '../../api/p3c'
import type { TableEvent } from '../../api/sessions'
import type { ContentFieldResolver, ContentNameResolver } from '../../i18n/useContentPresentations'
import { isContentReference } from './sessionCombatLog'
import type { SessionCopy } from './sessionCopy'

// Combat roll.requested events (P4) reuse the P3 chat prompt with server-side
// request types and English labels; these are presented via copy instead.
type CombatRollRequestType = 'initiative' | 'attack' | 'death_save'

const SERVER_LABEL_BY_TYPE: Record<CombatRollRequestType, string> = {
  initiative: 'Initiative',
  attack: 'Attack: ',
  death_save: 'Death Save',
}

export type RollRequestPromptResolvers = {
  entryLabel?: (entryId: string) => string | null
  contentName?: ContentNameResolver
  contentField?: ContentFieldResolver
}

export function formatRequestType(type: RollRequestType | CombatRollRequestType, copy: SessionCopy): string {
  switch (type) {
    case 'ability': return copy.checkAbilityType
    case 'skill': return copy.checkSkillType
    case 'saving_throw': return copy.checkSaveType
    case 'other': return copy.checkOtherType
    case 'initiative': return copy.checkInitiativeType
    case 'attack': return copy.checkAttackType
    case 'death_save': return copy.checkDeathSaveType
    default: return type
  }
}

function isCombatRollRequestType(type: unknown): type is CombatRollRequestType {
  return type === 'initiative' || type === 'attack' || type === 'death_save'
}

function combatEntryTargets(event: TableEvent, requestType: CombatRollRequestType): string[] {
  const payload = event.payload
  const ids: string[] = []
  if (requestType === 'initiative' && Array.isArray(payload.combat_entry_ids)) {
    for (const unit of payload.combat_entry_ids) {
      if (Array.isArray(unit)) ids.push(...unit.filter((id): id is string => typeof id === 'string'))
    }
  } else if (requestType === 'attack' && typeof payload.attacker_entry_id === 'string') {
    ids.push(payload.attacker_entry_id)
  } else if (requestType === 'death_save' && typeof payload.target_entry_id === 'string') {
    ids.push(payload.target_entry_id)
  }
  return ids
}

function combatRollLabel(
  event: TableEvent,
  requestType: CombatRollRequestType,
  resolvers: RollRequestPromptResolvers,
): string | null {
  const rawLabel = typeof event.payload.label === 'string' ? event.payload.label.trim() : ''
  if (requestType !== 'attack') {
    return rawLabel && rawLabel !== SERVER_LABEL_BY_TYPE[requestType] ? rawLabel : null
  }
  const fallback = rawLabel.startsWith(SERVER_LABEL_BY_TYPE.attack)
    ? rawLabel.slice(SERVER_LABEL_BY_TYPE.attack.length).trim()
    : rawLabel
  const contentRef = typeof event.payload.content_ref === 'string' ? event.payload.content_ref : null
  const presentationField = typeof event.payload.presentation_field === 'string'
    ? event.payload.presentation_field
    : null
  const sourceRef = typeof event.payload.source_ref === 'string' ? event.payload.source_ref : null
  if (contentRef && presentationField && resolvers.contentField) {
    return resolvers.contentField(contentRef, presentationField, fallback)
  }
  if (contentRef && resolvers.contentName) return resolvers.contentName(contentRef, fallback)
  if (sourceRef && isContentReference(sourceRef) && resolvers.contentName) {
    return resolvers.contentName(sourceRef, fallback)
  }
  return fallback || null
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
  resolvers: RollRequestPromptResolvers = {},
): string {
  const requestType = event.payload.request_type
  const modifierMode = event.payload.modifier_mode
  const flatAdjustment = event.payload.flat_adjustment
  const skillRef = event.payload.skill_ref
  const abilityRef = event.payload.ability_ref
  const combatType = isCombatRollRequestType(requestType) ? requestType : null
  const label = combatType ? combatRollLabel(event, combatType, resolvers) : event.payload.label
  if (combatType && targetLabels.length === 0 && resolvers.entryLabel) {
    targetLabels = combatEntryTargets(event, combatType)
      .map((entryId) => resolvers.entryLabel?.(entryId) ?? null)
      .filter((value): value is string => Boolean(value))
  }

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
