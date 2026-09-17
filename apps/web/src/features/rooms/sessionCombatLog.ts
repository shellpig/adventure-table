import type { TableEvent } from '../../api/sessions'
import type { Locale } from '../../i18n/locale'
import type { ContentNameResolver } from '../../i18n/useContentPresentations'

export type CombatEntryLabelResolver = (entryId: string) => string | null

export type CombatLogPresentation = {
  summary: string
  detail: string | null
}

type CombatLogCopy = {
  combatStarted: string
  combatEnded: string
  initiative: string
  turn: string
  round: string
  attack: string
  hit: string
  miss: string
  critical: string
  damage: string
  healing: string
  spell: string
  condition: string
  concentration: string
  concentrationStarted: string
  concentrationMaintained: string
  concentrationLost: string
  reaction: string
  reactionRequested: string
  reactionAccepted: string
  reactionDeclined: string
  adjudication: string
  adjudicationRequested: string
  adjudicationResolved: string
  resolved: string
  hp: string
  ac: string
  dc: string
  total: string
  injury: string
  targets: string
  injuryHealthy: string
  injuryWounded: string
  injuryCritical: string
  injuryDown: string
  reactionOpportunityAttack: string
  reactionShield: string
  reactionCounterspell: string
  reactionReady: string
  reactionLegendaryAction: string
  reactionOther: string
  adjudicationRange: string
  adjudicationReach: string
  adjudicationAffectedTargets: string
  adjudicationOpportunityAttack: string
  adjudicationSpecial: string
}

const COMBAT_LOG_COPY = {
  'zh-TW': {
    combatStarted: '戰鬥開始',
    combatEnded: '戰鬥結束',
    initiative: '先攻順序確定',
    turn: '回合',
    round: '第 {round} 輪',
    attack: '攻擊',
    hit: '命中',
    miss: '未命中',
    critical: '致命一擊',
    damage: '傷害',
    healing: '治療',
    spell: '法術',
    condition: '狀態',
    concentration: '專注',
    concentrationStarted: '開始專注',
    concentrationMaintained: '專注維持',
    concentrationLost: '專注中斷',
    reaction: '反應',
    reactionRequested: '等待反應',
    reactionAccepted: '已使用反應',
    reactionDeclined: '未使用反應',
    adjudication: '裁定',
    adjudicationRequested: '等待 DM 裁定',
    adjudicationResolved: '裁定完成',
    resolved: '已解決',
    hp: 'HP',
    ac: 'AC',
    dc: 'DC',
    total: '總值',
    injury: '傷勢',
    targets: '個目標',
    injuryHealthy: '健康',
    injuryWounded: '受傷',
    injuryCritical: '危急',
    injuryDown: '倒下',
    reactionOpportunityAttack: '機會攻擊',
    reactionShield: '護盾術',
    reactionCounterspell: '反制法術',
    reactionReady: '準備動作',
    reactionLegendaryAction: '傳奇動作',
    reactionOther: '其他反應',
    adjudicationRange: '射程',
    adjudicationReach: '觸及',
    adjudicationAffectedTargets: '受影響目標',
    adjudicationOpportunityAttack: '機會攻擊',
    adjudicationSpecial: '特殊裁定',
  },
  en: {
    combatStarted: 'Combat started',
    combatEnded: 'Combat ended',
    initiative: 'Initiative order set',
    turn: 'Turn',
    round: 'Round {round}',
    attack: 'Attack',
    hit: 'Hit',
    miss: 'Miss',
    critical: 'Critical hit',
    damage: 'Damage',
    healing: 'Healing',
    spell: 'Spell',
    condition: 'Condition',
    concentration: 'Concentration',
    concentrationStarted: 'Concentration started',
    concentrationMaintained: 'Concentration maintained',
    concentrationLost: 'Concentration lost',
    reaction: 'Reaction',
    reactionRequested: 'Reaction requested',
    reactionAccepted: 'Reaction used',
    reactionDeclined: 'Reaction declined',
    adjudication: 'Adjudication',
    adjudicationRequested: 'Awaiting DM adjudication',
    adjudicationResolved: 'Adjudication resolved',
    resolved: 'Resolved',
    hp: 'HP',
    ac: 'AC',
    dc: 'DC',
    total: 'Total',
    injury: 'Injury',
    targets: 'targets',
    injuryHealthy: 'Healthy',
    injuryWounded: 'Wounded',
    injuryCritical: 'Critical',
    injuryDown: 'Down',
    reactionOpportunityAttack: 'Opportunity attack',
    reactionShield: 'Shield',
    reactionCounterspell: 'Counterspell',
    reactionReady: 'Ready',
    reactionLegendaryAction: 'Legendary action',
    reactionOther: 'Other reaction',
    adjudicationRange: 'Range',
    adjudicationReach: 'Reach',
    adjudicationAffectedTargets: 'Affected targets',
    adjudicationOpportunityAttack: 'Opportunity attack',
    adjudicationSpecial: 'Special',
  },
} satisfies Record<Locale, CombatLogCopy>

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function stringField(source: Record<string, unknown>, key: string): string | null {
  const value = source[key]
  return typeof value === 'string' && value.length > 0 ? value : null
}

function numberField(source: Record<string, unknown> | null, key: string): number | null {
  if (!source) return null
  const value = source[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function booleanField(source: Record<string, unknown> | null, key: string): boolean | null {
  if (!source) return null
  const value = source[key]
  return typeof value === 'boolean' ? value : null
}

function localizedTemplate(template: string, key: string, value: string | number): string {
  return template.replace(`{${key}}`, String(value))
}

function entryLabel(
  source: Record<string, unknown>,
  key: string,
  resolveEntryLabel: CombatEntryLabelResolver,
): string | null {
  const entryId = stringField(source, key)
  return entryId ? resolveEntryLabel(entryId) : null
}

function injuryLabel(level: string | null, copy: CombatLogCopy): string | null {
  switch (level) {
    case 'healthy':
      return copy.injuryHealthy
    case 'wounded':
      return copy.injuryWounded
    case 'critical':
      return copy.injuryCritical
    case 'down':
      return copy.injuryDown
    default:
      return null
  }
}

function reactionKindLabel(kind: string | null, copy: CombatLogCopy): string {
  switch (kind) {
    case 'opportunity_attack':
      return copy.reactionOpportunityAttack
    case 'shield':
      return copy.reactionShield
    case 'counterspell':
      return copy.reactionCounterspell
    case 'ready':
      return copy.reactionReady
    case 'legendary_action':
      return copy.reactionLegendaryAction
    default:
      return copy.reactionOther
  }
}

function adjudicationKindLabel(kind: string | null, copy: CombatLogCopy): string {
  switch (kind) {
    case 'range':
      return copy.adjudicationRange
    case 'reach':
      return copy.adjudicationReach
    case 'affected_targets':
      return copy.adjudicationAffectedTargets
    case 'opportunity_attack':
      return copy.adjudicationOpportunityAttack
    case 'special':
      return copy.adjudicationSpecial
    default:
      return copy.adjudication
  }
}

function hpDetail(source: Record<string, unknown>, copy: CombatLogCopy): string | null {
  const after = asRecord(source.after)
  const currentHp = numberField(after, 'current_hp')
  const maxHp = numberField(after, 'max_hp')
  if (currentHp === null) return null
  return maxHp === null ? `${copy.hp} ${currentHp}` : `${copy.hp} ${currentHp}/${maxHp}`
}

function conditionContentReference(event: Record<string, unknown>): string | null {
  const type = stringField(event, 'type')
  if (!type?.includes('condition')) return null
  const direct = stringField(event, 'condition_ref') ?? stringField(event, 'condition')
  if (direct) return direct
  const tag = stringField(event, 'tag')
  return tag ? `srd5.1:condition:${tag}` : null
}

function conditionDetail(
  source: Record<string, unknown>,
  copy: CombatLogCopy,
  resolveContentName: ContentNameResolver,
): string | null {
  const domainEvents = source.domain_events
  if (!Array.isArray(domainEvents)) return null

  const conditions = new Set<string>()
  for (const raw of domainEvents) {
    const event = asRecord(raw)
    if (!event) continue
    const conditionRef = conditionContentReference(event)
    if (!conditionRef) continue
    conditions.add(resolveContentName(conditionRef, copy.condition))
  }
  if (conditions.size === 0) return null

  const labels = [...conditions]
  if (labels.length === 1 && labels[0] === copy.condition) return copy.condition
  return `${copy.condition}: ${labels.join(', ')}`
}

function targetCount(source: Record<string, unknown>): number | null {
  const outcomes = source.outcomes
  if (Array.isArray(outcomes)) return outcomes.length
  const confirmed = source.confirmed_target_ids
  if (Array.isArray(confirmed)) return confirmed.length
  const proposed = source.proposed_target_ids
  return Array.isArray(proposed) ? proposed.length : null
}

export function combatLogContentReferences(events: readonly TableEvent[]): string[] {
  const references = new Set<string>()
  for (const event of events) {
    const spellRef = stringField(event.payload, 'spell_ref')
    if (spellRef) references.add(spellRef)

    if (event.kind === 'roll.resolved' && typeof event.payload.combat_id === 'string') {
      const resolution = asRecord(event.payload.attack_resolution)
      const attack = resolution ? asRecord(resolution.attack) : null
      const attackSourceRef = attack ? stringField(attack, 'source_ref') : null
      if (attackSourceRef) references.add(attackSourceRef)
    }

    const domainEvents = event.payload.domain_events
    if (!Array.isArray(domainEvents)) continue
    for (const raw of domainEvents) {
      const domainEvent = asRecord(raw)
      if (!domainEvent) continue
      const conditionRef = conditionContentReference(domainEvent)
      if (conditionRef) references.add(conditionRef)
    }
  }
  return [...references]
}

function formatDamageOrHealing(
  source: Record<string, unknown>,
  copy: CombatLogCopy,
  resolveEntryLabel: CombatEntryLabelResolver,
  resolveContentName: ContentNameResolver,
  kind: 'damage' | 'healing',
): CombatLogPresentation {
  const label = kind === 'damage' ? copy.damage : copy.healing
  const target = entryLabel(source, 'target_entry_id', resolveEntryLabel)
  const amount = numberField(source, 'amount')
  const summary = [target, label, amount === null ? null : String(amount)].filter(Boolean).join(' · ')
  const injury = injuryLabel(stringField(source, 'target_injury_level'), copy)
  const detail = [
    hpDetail(source, copy),
    injury ? `${copy.injury}: ${injury}` : null,
    conditionDetail(source, copy, resolveContentName),
  ].filter(Boolean).join(' · ')
  return { summary, detail: detail || null }
}

function formatAttack(
  payload: Record<string, unknown>,
  copy: CombatLogCopy,
  resolveEntryLabel: CombatEntryLabelResolver,
  resolveContentName: ContentNameResolver,
): CombatLogPresentation | null {
  const resolution = asRecord(payload.attack_resolution)
  if (!resolution) return null
  const attack = asRecord(resolution.attack)
  if (!attack) return null
  const damage = asRecord(resolution.damage)
  const attacker = entryLabel(payload, 'attacker_entry_id', resolveEntryLabel)
  const target = entryLabel(payload, 'target_entry_id', resolveEntryLabel)
  const attackSourceRef = stringField(attack, 'source_ref')
  const attackName = attackSourceRef
    ? resolveContentName(attackSourceRef, copy.attack)
    : stringField(attack, 'name') ?? copy.attack
  const hit = booleanField(attack, 'hit')
  const critical = booleanField(attack, 'critical') === true
  const outcome = critical ? copy.critical : hit === true ? copy.hit : hit === false ? copy.miss : null
  const subject = [attacker, attackName, target ? `→ ${target}` : null].filter(Boolean).join(' · ')
  const summary = [subject || copy.attack, outcome].filter(Boolean).join(' · ')

  const total = numberField(attack, 'total')
  const targetAc = numberField(attack, 'target_ac')
  const damageAmount = numberField(damage, 'adjusted_total')
  const after = damage ? asRecord(damage.after) : null
  const currentHp = numberField(after, 'current_hp')
  const maxHp = numberField(after, 'max_hp')
  const injury = injuryLabel(stringField(payload, 'target_injury_level'), copy)
  const detail = [
    total === null ? null : `${copy.total} ${total}`,
    targetAc === null ? null : `${copy.ac} ${targetAc}`,
    damageAmount === null ? null : `${copy.damage} ${damageAmount}`,
    currentHp === null ? null : maxHp === null ? `${copy.hp} ${currentHp}` : `${copy.hp} ${currentHp}/${maxHp}`,
    injury ? `${copy.injury}: ${injury}` : null,
  ].filter(Boolean).join(' · ')
  return { summary, detail: detail || null }
}

function formatSpell(
  source: Record<string, unknown>,
  copy: CombatLogCopy,
  resolveEntryLabel: CombatEntryLabelResolver,
  resolveContentName: ContentNameResolver,
  adjudicationRequested: boolean,
): CombatLogPresentation {
  const caster = entryLabel(source, 'caster_entry_id', resolveEntryLabel)
  const target = entryLabel(source, 'target_entry_id', resolveEntryLabel)
  const spellRef = stringField(source, 'spell_ref')
  const spellName = spellRef ? resolveContentName(spellRef, copy.spell) : copy.spell
  const spellLabel = spellName === copy.spell ? copy.spell : `${copy.spell}: ${spellName}`
  const count = targetCount(source)
  const subject = [caster, spellLabel, target ? `→ ${target}` : null].filter(Boolean).join(' · ')
  const detailParts: Array<string | null> = []
  if (count !== null) detailParts.push(`${count} ${copy.targets}`)
  if (adjudicationRequested) detailParts.push(copy.adjudicationRequested)
  if (source.concentration_started === true) detailParts.push(copy.concentrationStarted)
  const injury = injuryLabel(stringField(source, 'target_injury_level'), copy)
  if (injury) detailParts.push(`${copy.injury}: ${injury}`)
  const condition = conditionDetail(source, copy, resolveContentName)
  if (condition) detailParts.push(condition)
  return { summary: subject || copy.spell, detail: detailParts.filter(Boolean).join(' · ') || null }
}

function formatConcentration(
  source: Record<string, unknown>,
  copy: CombatLogCopy,
  resolveEntryLabel: CombatEntryLabelResolver,
): CombatLogPresentation {
  const target = entryLabel(source, 'target_entry_id', resolveEntryLabel)
  const succeeded = booleanField(source, 'succeeded')
  const outcome = succeeded === true
    ? copy.concentrationMaintained
    : succeeded === false
      ? copy.concentrationLost
      : copy.concentration
  const summary = [target, outcome].filter(Boolean).join(' · ') || copy.concentration
  const total = numberField(source, 'total')
  const dc = numberField(source, 'dc')
  const detail = [
    total === null ? null : `${copy.total} ${total}`,
    dc === null ? null : `${copy.dc} ${dc}`,
  ].filter(Boolean).join(' · ')
  return { summary, detail: detail || null }
}

function formatConcentrationChange(
  source: Record<string, unknown>,
  copy: CombatLogCopy,
  resolveEntryLabel: CombatEntryLabelResolver,
): CombatLogPresentation {
  const actor = entryLabel(source, 'entry_id', resolveEntryLabel)
  const dropped = booleanField(source, 'dropped')
  const outcome = dropped === true
    ? copy.concentrationLost
    : dropped === false
      ? copy.concentrationMaintained
      : copy.concentration
  return {
    summary: [actor, outcome].filter(Boolean).join(' · ') || copy.concentration,
    detail: null,
  }
}

function formatReaction(
  source: Record<string, unknown>,
  copy: CombatLogCopy,
  resolveEntryLabel: CombatEntryLabelResolver,
  resolved: boolean,
): CombatLogPresentation {
  const actor = resolved
    ? entryLabel(source, 'actor_entry_id', resolveEntryLabel)
    : entryLabel(source, 'entry_id', resolveEntryLabel)
  const reaction = reactionKindLabel(stringField(source, 'kind'), copy)
  const accepted = booleanField(source, 'accepted')
  const status = resolved
    ? accepted === true
      ? copy.reactionAccepted
      : accepted === false
        ? copy.reactionDeclined
        : copy.resolved
    : copy.reactionRequested
  return {
    summary: [actor, `${copy.reaction}: ${reaction}`, status].filter(Boolean).join(' · '),
    detail: null,
  }
}

function formatAdjudication(
  source: Record<string, unknown>,
  copy: CombatLogCopy,
  resolveEntryLabel: CombatEntryLabelResolver,
  resolved: boolean,
): CombatLogPresentation {
  const actor = entryLabel(source, 'attacker_entry_id', resolveEntryLabel)
    ?? entryLabel(source, 'entry_id', resolveEntryLabel)
  const target = entryLabel(source, 'target_entry_id', resolveEntryLabel)
  const kind = adjudicationKindLabel(stringField(source, 'kind'), copy)
  const status = resolved ? copy.adjudicationResolved : copy.adjudicationRequested
  const summary = [actor, `${copy.adjudication}: ${kind}`, target ? `→ ${target}` : null, status]
    .filter(Boolean)
    .join(' · ')
  return { summary, detail: null }
}

export function formatCombatLogEvent(
  event: TableEvent,
  locale: Locale,
  resolveEntryLabel: CombatEntryLabelResolver,
  resolveContentName: ContentNameResolver,
): CombatLogPresentation | null {
  const copy = COMBAT_LOG_COPY[locale]
  const payload = event.payload

  switch (event.kind) {
    case 'combat.started':
      return { summary: copy.combatStarted, detail: null }
    case 'combat.ended':
      return { summary: copy.combatEnded, detail: null }
    case 'combat.initiative_ordered': {
      const round = numberField(payload, 'round')
      return {
        summary: copy.initiative,
        detail: round === null ? null : localizedTemplate(copy.round, 'round', round),
      }
    }
    case 'combat.turn_advanced': {
      const turnEntry = entryLabel(payload, 'current_turn_entry_id', resolveEntryLabel)
      const round = numberField(payload, 'round')
      return {
        summary: [copy.turn, turnEntry].filter(Boolean).join(' · '),
        detail: round === null ? null : localizedTemplate(copy.round, 'round', round),
      }
    }
    case 'combat.damage_applied':
      return formatDamageOrHealing(payload, copy, resolveEntryLabel, resolveContentName, 'damage')
    case 'combat.healing_applied':
      return formatDamageOrHealing(payload, copy, resolveEntryLabel, resolveContentName, 'healing')
    case 'combat.spell_cast_resolved':
    case 'combat.spell_aoe_resolved':
      return formatSpell(payload, copy, resolveEntryLabel, resolveContentName, false)
    case 'combat.spell_aoe_adjudication_requested':
      return formatSpell(payload, copy, resolveEntryLabel, resolveContentName, true)
    case 'combat.concentration_resolved':
      return formatConcentration(payload, copy, resolveEntryLabel)
    case 'combat.concentration_changed':
      return formatConcentrationChange(payload, copy, resolveEntryLabel)
    case 'combat.reaction_requested':
      return formatReaction(payload, copy, resolveEntryLabel, false)
    case 'combat.reaction_resolved':
      return formatReaction(payload, copy, resolveEntryLabel, true)
    case 'combat.adjudication_requested':
      return formatAdjudication(payload, copy, resolveEntryLabel, false)
    case 'combat.adjudication_resolved':
      return formatAdjudication(payload, copy, resolveEntryLabel, true)
    case 'roll.resolved':
      return typeof payload.combat_id === 'string'
        ? formatAttack(payload, copy, resolveEntryLabel, resolveContentName)
        : null
    default:
      return null
  }
}
