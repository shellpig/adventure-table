import type { TableEvent } from '../../api/sessions'
import type { Locale } from '../../i18n/locale'
import type { ContentFieldResolver, ContentNameResolver } from '../../i18n/useContentPresentations'

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
  savingThrow: string
  saveSuccess: string
  saveFailure: string
  deathSave: string
  deathSaveSuccesses: string
  deathSaveFailures: string
  stable: string
  dead: string
  natural20Recovery: string
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
  entryAdded: string
  entryWithdrawn: string
  entryRemoved: string
  initiativeReordered: string
  actionUsed: string
  actionDash: string
  actionDisengage: string
  actionDodge: string
  actionHelp: string
  actionHide: string
  actionReady: string
  actionSearch: string
  actionUseObject: string
  actionOther: string
  reactionWindowOpened: string
  reactionWindowClosed: string
  specialAttack: string
  grapple: string
  shove: string
  shoveProne: string
  shovePush: string
  waitingForRoll: string
  success: string
  failure: string
  inReach: string
  outOfReach: string
  savesRequested: string
  attackerTotal: string
  targetTotal: string
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
    savingThrow: '豁免',
    saveSuccess: '成功',
    saveFailure: '失敗',
    deathSave: '死亡豁免',
    deathSaveSuccesses: '成功',
    deathSaveFailures: '失敗',
    stable: '穩定',
    dead: '死亡',
    natural20Recovery: '自然 20 恢復',
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
    entryAdded: '加入戰鬥',
    entryWithdrawn: '脫離戰鬥',
    entryRemoved: '移出戰鬥',
    initiativeReordered: '先攻順序調整',
    actionUsed: '執行動作',
    actionDash: '疾走',
    actionDisengage: '撤離',
    actionDodge: '閃避',
    actionHelp: '協助',
    actionHide: '躲藏',
    actionReady: '準備動作',
    actionSearch: '搜尋',
    actionUseObject: '使用物品',
    actionOther: '其他動作',
    reactionWindowOpened: '反應窗口開啟',
    reactionWindowClosed: '反應窗口關閉',
    specialAttack: '特殊攻擊',
    grapple: '擒抱',
    shove: '推撞',
    shoveProne: '推倒',
    shovePush: '推開',
    waitingForRoll: '等待對抗擲骰',
    success: '成功',
    failure: '失敗',
    inReach: '在觸及範圍內',
    outOfReach: '超出觸及範圍',
    savesRequested: '等待豁免檢定',
    attackerTotal: '攻擊方總值',
    targetTotal: '目標總值',
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
    savingThrow: 'Saving throw',
    saveSuccess: 'Success',
    saveFailure: 'Failure',
    deathSave: 'Death save',
    deathSaveSuccesses: 'Successes',
    deathSaveFailures: 'Failures',
    stable: 'Stable',
    dead: 'Dead',
    natural20Recovery: 'Natural 20 recovery',
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
    entryAdded: 'Joined combat',
    entryWithdrawn: 'Withdrawn',
    entryRemoved: 'Removed from combat',
    initiativeReordered: 'Initiative reordered',
    actionUsed: 'Action used',
    actionDash: 'Dash',
    actionDisengage: 'Disengage',
    actionDodge: 'Dodge',
    actionHelp: 'Help',
    actionHide: 'Hide',
    actionReady: 'Ready',
    actionSearch: 'Search',
    actionUseObject: 'Use object',
    actionOther: 'Other action',
    reactionWindowOpened: 'Reaction window opened',
    reactionWindowClosed: 'Reaction window closed',
    specialAttack: 'Special attack',
    grapple: 'Grapple',
    shove: 'Shove',
    shoveProne: 'Shove prone',
    shovePush: 'Shove push',
    waitingForRoll: 'Awaiting contest roll',
    success: 'Success',
    failure: 'Failure',
    inReach: 'In reach',
    outOfReach: 'Out of reach',
    savesRequested: 'Saving throws requested',
    attackerTotal: 'Attacker total',
    targetTotal: 'Target total',
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

function actionKindLabel(kind: string | null, copy: CombatLogCopy): string {
  switch (kind) {
    case 'dash':
      return copy.actionDash
    case 'disengage':
      return copy.actionDisengage
    case 'dodge':
      return copy.actionDodge
    case 'help':
      return copy.actionHelp
    case 'hide':
      return copy.actionHide
    case 'ready':
      return copy.actionReady
    case 'search':
      return copy.actionSearch
    case 'use_object':
      return copy.actionUseObject
    case 'attack':
      return copy.attack
    case 'spell':
    case 'cast_spell':
      return copy.spell
    case 'grapple':
      return copy.grapple
    case 'shove':
      return copy.shove
    default:
      return copy.actionOther
  }
}

function specialAttackKindLabel(kind: string | null, copy: CombatLogCopy): string {
  switch (kind) {
    case 'grapple':
      return copy.grapple
    case 'shove_prone':
      return copy.shoveProne
    case 'shove_push':
      return copy.shovePush
    case 'shove':
      return copy.shove
    default:
      return copy.specialAttack
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

function isContentReference(reference: string): boolean {
  return !reference.startsWith('inventory:')
    && !reference.startsWith('monster-action:')
    && /^[^:]+:[^:]+:[^:]+$/.test(reference)
}

export function combatLogContentReferences(events: readonly TableEvent[]): string[] {
  const references = new Set<string>()
  for (const event of events) {
    const abilityRef = stringField(event.payload, 'ability_ref')
    if (event.kind === 'combat.saves_requested' && abilityRef) references.add(abilityRef)
    const spellRef = stringField(event.payload, 'spell_ref')
    if (spellRef) references.add(spellRef)

    if (event.kind === 'roll.resolved' && typeof event.payload.combat_id === 'string') {
      const resolution = asRecord(event.payload.attack_resolution)
      const attack = resolution ? asRecord(resolution.attack) : null
      const contentRef = attack ? stringField(attack, 'content_ref') : null
      if (contentRef) {
        references.add(contentRef)
      } else {
        const attackSourceRef = attack ? stringField(attack, 'source_ref') : null
        if (attackSourceRef && isContentReference(attackSourceRef)) references.add(attackSourceRef)
      }
    }

    if (event.kind === 'combat.special_attack_roll_resolved') {
      const res = asRecord(event.payload.resolution_result)
      const condition = res ? stringField(res, 'condition_to_apply') : null
      if (condition) references.add(`srd5.1:condition:${condition}`)
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

export function combatLogContentFields(events: readonly TableEvent[]): Record<string, string[]> {
  const fieldsByRef: Record<string, Set<string>> = {}
  for (const event of events) {
    if (event.kind === 'roll.resolved' && typeof event.payload.combat_id === 'string') {
      const resolution = asRecord(event.payload.attack_resolution)
      const attack = resolution ? asRecord(resolution.attack) : null
      const contentRef = attack ? stringField(attack, 'content_ref') : null
      const presentationField = attack ? stringField(attack, 'presentation_field') : null
      if (contentRef && presentationField) {
        if (!fieldsByRef[contentRef]) fieldsByRef[contentRef] = new Set()
        fieldsByRef[contentRef].add(presentationField)
      }
    }
  }
  const result: Record<string, string[]> = {}
  for (const [ref, fields] of Object.entries(fieldsByRef)) {
    result[ref] = [...fields]
  }
  return result
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
  resolveContentField: ContentFieldResolver,
): CombatLogPresentation | null {
  const resolution = asRecord(payload.attack_resolution)
  if (!resolution) return null
  const attack = asRecord(resolution.attack)
  if (!attack) return null
  const damage = asRecord(resolution.damage)
  const attacker = entryLabel(payload, 'attacker_entry_id', resolveEntryLabel)
  const target = entryLabel(payload, 'target_entry_id', resolveEntryLabel)
  const attackSourceRef = stringField(attack, 'source_ref')
  const contentRef = stringField(attack, 'content_ref')
  const presentationField = stringField(attack, 'presentation_field')

  let attackName: string
  if (contentRef && presentationField) {
    attackName = resolveContentField(contentRef, presentationField, copy.attack)
  } else if (contentRef) {
    attackName = resolveContentName(contentRef, copy.attack)
  } else if (attackSourceRef && isContentReference(attackSourceRef)) {
    attackName = resolveContentName(attackSourceRef, copy.attack)
  } else {
    attackName = stringField(attack, 'name') ?? copy.attack
  }

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

function spellDomainEventAmount(source: Record<string, unknown>, type: 'damage' | 'heal'): number | null {
  const domainEvents = source.domain_events
  if (!Array.isArray(domainEvents)) return null
  for (const raw of domainEvents) {
    const domainEvent = asRecord(raw)
    if (!domainEvent || stringField(domainEvent, 'type') !== type) continue
    const amount = numberField(domainEvent, type === 'heal' ? 'restored' : 'amount')
    if (amount !== null) return amount
  }
  return null
}

function spellOutcomeDetails(
  source: Record<string, unknown>,
  copy: CombatLogCopy,
  resolveEntryLabel: CombatEntryLabelResolver,
): string[] {
  const outcomes = source.outcomes
  if (!Array.isArray(outcomes)) return []

  const details: string[] = []
  for (const raw of outcomes) {
    const outcome = asRecord(raw)
    if (!outcome) continue
    const target = entryLabel(outcome, 'target_entry_id', resolveEntryLabel)
    const damage = numberField(outcome, 'damage')
    const currentHp = numberField(outcome, 'current_hp')
    const detail = [
      target,
      damage === null ? null : `${copy.damage} ${damage}`,
      currentHp === null ? null : `${copy.hp} ${currentHp}`,
    ].filter(Boolean).join(' · ')
    if (detail) details.push(detail)
  }
  return details
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
  const outcomeDetails = spellOutcomeDetails(source, copy, resolveEntryLabel)
  if (count !== null) detailParts.push(`${count} ${copy.targets}`)
  if (outcomeDetails.length > 0) {
    detailParts.push(...outcomeDetails)
  } else {
    const domainDamage = spellDomainEventAmount(source, 'damage')
    const payloadDamage = numberField(source, 'damage')
    const damage = domainDamage ?? (payloadDamage !== null && payloadDamage > 0 ? payloadDamage : null)
    if (damage !== null) detailParts.push(`${copy.damage} ${damage}`)
    const currentHp = numberField(source, 'target_current_hp')
    if (currentHp !== null) detailParts.push(`${copy.hp} ${currentHp}`)
  }
  const healing = spellDomainEventAmount(source, 'heal')
  if (healing !== null) detailParts.push(`${copy.healing} ${healing}`)
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

function formatSave(
  source: Record<string, unknown>,
  copy: CombatLogCopy,
  resolveEntryLabel: CombatEntryLabelResolver,
): CombatLogPresentation {
  const target = entryLabel(source, 'target_entry_id', resolveEntryLabel)
  const succeeded = booleanField(source, 'succeeded')
  const outcome = succeeded === true
    ? copy.saveSuccess
    : succeeded === false
      ? copy.saveFailure
      : null
  const total = numberField(source, 'total')
  return {
    summary: [target, copy.savingThrow, outcome].filter(Boolean).join(' · ') || copy.savingThrow,
    detail: total === null ? null : `${copy.total} ${total}`,
  }
}

function formatDeathSave(
  source: Record<string, unknown>,
  copy: CombatLogCopy,
  resolveEntryLabel: CombatEntryLabelResolver,
): CombatLogPresentation {
  const target = entryLabel(source, 'target_entry_id', resolveEntryLabel)
  const d20 = numberField(source, 'd20')
  const currentHp = numberField(source, 'current_hp')
  const successes = numberField(source, 'successes')
  const failures = numberField(source, 'failures')
  const detail = [
    d20 === null ? null : `d20 ${d20}`,
    currentHp === null ? null : `${copy.hp} ${currentHp}`,
    successes === null ? null : `${copy.deathSaveSuccesses} ${successes}`,
    failures === null ? null : `${copy.deathSaveFailures} ${failures}`,
    booleanField(source, 'stable') === true ? copy.stable : null,
    booleanField(source, 'dead') === true ? copy.dead : null,
    booleanField(source, 'natural_20_recovery') === true ? copy.natural20Recovery : null,
  ].filter(Boolean).join(' · ')
  return {
    summary: [target, copy.deathSave].filter(Boolean).join(' · ') || copy.deathSave,
    detail: detail || null,
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
  resolveContentField: ContentFieldResolver,
): CombatLogPresentation | null {
  const copy = COMBAT_LOG_COPY[locale]
  const payload = event.payload

  switch (event.kind) {
    case 'combat.started':
      return { summary: copy.combatStarted, detail: null }
    case 'combat.ended':
      return { summary: copy.combatEnded, detail: null }
    case 'combat.entry_added': {
      const displayName = stringField(payload, 'display_name')
      const target = displayName ?? entryLabel(payload, 'entry_id', resolveEntryLabel)
      return {
        summary: [target, copy.entryAdded].filter(Boolean).join(' · ') || copy.entryAdded,
        detail: null,
      }
    }
    case 'combat.entry_withdrawn': {
      const target = entryLabel(payload, 'entry_id', resolveEntryLabel)
      return {
        summary: [target, copy.entryWithdrawn].filter(Boolean).join(' · ') || copy.entryWithdrawn,
        detail: null,
      }
    }
    case 'combat.entry_removed': {
      const target = entryLabel(payload, 'entry_id', resolveEntryLabel)
      return {
        summary: [target, copy.entryRemoved].filter(Boolean).join(' · ') || copy.entryRemoved,
        detail: null,
      }
    }
    case 'combat.initiative_ordered': {
      const round = numberField(payload, 'round')
      return {
        summary: copy.initiative,
        detail: round === null ? null : localizedTemplate(copy.round, 'round', round),
      }
    }
    case 'combat.initiative_reordered': {
      const ids = Array.isArray(payload.ordered_entry_ids) ? payload.ordered_entry_ids : []
      const names = ids
        .map((id) => (typeof id === 'string' ? resolveEntryLabel(id) : null))
        .filter(Boolean)
      return {
        summary: copy.initiativeReordered,
        detail: names.length > 0 ? names.join(' → ') : null,
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
    case 'combat.action_used': {
      const actor = entryLabel(payload, 'entry_id', resolveEntryLabel)
      const kind = actionKindLabel(stringField(payload, 'action_kind'), copy)
      return {
        summary: [actor, kind].filter(Boolean).join(' · ') || copy.actionUsed,
        detail: null,
      }
    }
    case 'combat.reaction_window': {
      const actor = entryLabel(payload, 'entry_id', resolveEntryLabel)
      const open = booleanField(payload, 'open')
      const windowStatus = open === true ? copy.reactionWindowOpened : copy.reactionWindowClosed
      return {
        summary: [actor, windowStatus].filter(Boolean).join(' · ') || copy.reaction,
        detail: null,
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
    case 'combat.saves_requested': {
      const targetIds = Array.isArray(payload.target_entry_ids) ? payload.target_entry_ids : []
      const targetLabels = targetIds
        .map((id) => (typeof id === 'string' ? resolveEntryLabel(id) : null))
        .filter(Boolean)
      const targetText = targetLabels.length > 0
        ? targetLabels.join(', ')
        : targetIds.length > 0
          ? `${targetIds.length} ${copy.targets}`
          : null
      const abilityRef = stringField(payload, 'ability_ref')
      const abilityFallback = abilityRef?.split(':').pop()?.toUpperCase() ?? null
      return {
        summary: [targetText, copy.savingThrow, copy.savesRequested].filter(Boolean).join(' · '),
        detail: abilityRef ? resolveContentName(abilityRef, abilityFallback ?? abilityRef) : null,
      }
    }
    case 'combat.save_resolved':
      return formatSave(payload, copy, resolveEntryLabel)
    case 'combat.death_save_resolved':
      return formatDeathSave(payload, copy, resolveEntryLabel)
    case 'combat.reaction_requested':
      return formatReaction(payload, copy, resolveEntryLabel, false)
    case 'combat.reaction_resolved':
      return formatReaction(payload, copy, resolveEntryLabel, true)
    case 'combat.adjudication_requested':
      return formatAdjudication(payload, copy, resolveEntryLabel, false)
    case 'combat.adjudication_resolved':
      return formatAdjudication(payload, copy, resolveEntryLabel, true)
    case 'combat.special_attack_adjudication_requested': {
      const attacker = entryLabel(payload, 'attacker_entry_id', resolveEntryLabel)
      const target = entryLabel(payload, 'target_entry_id', resolveEntryLabel)
      const kind = specialAttackKindLabel(stringField(payload, 'kind'), copy)
      return {
        summary: [
          attacker,
          `${copy.adjudication}: ${kind}`,
          target ? `→ ${target}` : null,
          copy.adjudicationRequested,
        ]
          .filter(Boolean)
          .join(' · '),
        detail: null,
      }
    }
    case 'combat.special_attack_adjudicated': {
      const attacker = entryLabel(payload, 'attacker_entry_id', resolveEntryLabel)
      const target = entryLabel(payload, 'target_entry_id', resolveEntryLabel)
      const kind = specialAttackKindLabel(stringField(payload, 'kind'), copy)
      const inReach = booleanField(payload, 'in_reach')
      const reachStatus = inReach === true ? copy.inReach : inReach === false ? copy.outOfReach : null
      return {
        summary: [
          attacker,
          kind ? `${copy.adjudication}: ${kind}` : copy.adjudication,
          reachStatus,
          target ? `→ ${target}` : null,
        ]
          .filter(Boolean)
          .join(' · '),
        detail: null,
      }
    }
    case 'combat.special_attack_roll_resolved': {
      const target = entryLabel(payload, 'target_entry_id', resolveEntryLabel)
      const total = numberField(payload, 'total')
      const res = asRecord(payload.resolution_result)
      if (!res || stringField(payload, 'status') === 'waiting_for_roll') {
        return {
          summary: [target, copy.specialAttack, copy.waitingForRoll].filter(Boolean).join(' · '),
          detail: total === null ? null : `${copy.total} ${total}`,
        }
      }
      const outcomeStatus = stringField(res, 'status')
      const outcome = outcomeStatus === 'success'
        ? copy.success
        : outcomeStatus === 'failure'
          ? copy.failure
          : null
      const kind = specialAttackKindLabel(stringField(res, 'kind'), copy)
      const attackerTotal = numberField(res, 'attacker_total')
      const targetTotal = numberField(res, 'target_total')
      const pushDistance = numberField(res, 'push_distance_ft')
      const condition = stringField(res, 'condition_to_apply')
      let conditionLabel: string | null = null
      if (condition) {
        const resolved = resolveContentName(`srd5.1:condition:${condition}`, copy.condition)
        conditionLabel = resolved === copy.condition ? copy.condition : `${copy.condition}: ${resolved}`
      }

      const summaryParts = [target, kind, outcome].filter(Boolean)
      const detailParts = [
        attackerTotal !== null ? `${copy.attackerTotal} ${attackerTotal}` : null,
        targetTotal !== null ? `${copy.targetTotal} ${targetTotal}` : null,
        pushDistance !== null && pushDistance > 0 ? `${pushDistance} ft` : null,
        conditionLabel,
      ].filter(Boolean)

      return {
        summary: summaryParts.join(' · ') || copy.specialAttack,
        detail: detailParts.length > 0 ? detailParts.join(' · ') : null,
      }
    }
    case 'roll.resolved':
      return typeof payload.combat_id === 'string'
        ? formatAttack(payload, copy, resolveEntryLabel, resolveContentName, resolveContentField)
        : null
    default:
      return null
  }
}
