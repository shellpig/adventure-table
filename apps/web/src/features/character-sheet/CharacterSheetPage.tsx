import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getCharacterSheet,
  listContent,
  patchCharacterState,
} from '../../api/character'
import type {
  CharacterSheetDTO,
  CharacterStatePatch,
  ContentEntry,
  InventoryDTO,
  InventoryStateEntry,
  PreparedSpellSelection,
  ResourceCounter,
} from '../../api/character'
import { ExportCharacterButton } from '../character-io/ExportCharacterButton'
import { SearchableSelect } from '../../components/SearchableSelect'
import type { SearchOption } from '../../components/SearchableSelect'
import type { UiCopyKey } from '../../i18n/uiCopy'
import { passiveInvestigationLabel } from '../../i18n/m01kCharacterSheetCopy'
import { type ContentNameResolver, useContentPresentations } from '../../i18n/useContentPresentations'
import { useUiCopy, type UiTranslator } from '../../i18n/useUiCopy'

type CharacterTab = 'attributes' | 'spells' | 'inventory'
type StructuredRuleKind = 'damage-type' | 'equipment-category'
type StructuredRuleReference = { index?: unknown; name?: unknown }

type CharacterSheetViewProps = {
  sheet: CharacterSheetDTO
  conditionContent?: ContentEntry[]
  inventoryContent?: ContentEntry[]
  initialTab?: CharacterTab
  busy?: boolean
  errorMessage?: string | null
  onPatch?: (patch: CharacterStatePatch) => Promise<void> | void
  /** Sheet-owned header actions (M03-B export, later M03-C import). */
  headerActions?: ReactNode
}

const ABILITY_KEYS: Record<string, UiCopyKey> = {
  strength: 'sheet.ability.strength',
  dexterity: 'sheet.ability.dexterity',
  constitution: 'sheet.ability.constitution',
  intelligence: 'sheet.ability.intelligence',
  wisdom: 'sheet.ability.wisdom',
  charisma: 'sheet.ability.charisma',
}

const ACCESS_KEYS: Record<string, UiCopyKey> = {
  known: 'sheet.access.known',
  spellbook: 'sheet.access.spellbook',
  prepared: 'sheet.access.prepared',
  always_prepared: 'sheet.access.always_prepared',
  granted: 'sheet.access.granted',
}

function abilityLabel(key: string, t: UiTranslator) {
  const copyKey = ABILITY_KEYS[key]
  return copyKey ? t(copyKey) : titleCase(key)
}

function accessLabel(key: string, t: UiTranslator) {
  const copyKey = ACCESS_KEYS[key]
  return copyKey ? t(copyKey) : key
}

function signed(value: number) {
  return value >= 0 ? `+${value}` : String(value)
}

function titleCase(value: string) {
  return value
    .replaceAll('-', ' ')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function inventoryState(inventory: InventoryDTO[]): InventoryStateEntry[] {
  return inventory.map(({ entry_id, item_ref, quantity, equipped, carried }) => ({
    entry_id,
    item_ref,
    quantity,
    equipped,
    carried,
  }))
}

function countersToPatch(source: Record<string, ResourceCounter>) {
  return Object.fromEntries(
    Object.entries(source).map(([key, value]) => [key, { ...value }]),
  )
}

function structuredRuleReference(
  rules: Record<string, unknown>,
  kind: StructuredRuleKind,
): StructuredRuleReference | undefined {
  if (kind === 'equipment-category') {
    const raw = rules.equipment_category
    return raw && typeof raw === 'object' ? (raw as StructuredRuleReference) : undefined
  }
  const damage = rules.damage
  if (!damage || typeof damage !== 'object') return undefined
  const raw = (damage as { damage_type?: unknown }).damage_type
  return raw && typeof raw === 'object' ? (raw as StructuredRuleReference) : undefined
}

function structuredRuleKey(
  kind: StructuredRuleKind,
  reference: StructuredRuleReference | undefined,
): string | null {
  const index = reference?.index
  return typeof index === 'string' && index.trim() ? `srd5.1:${kind}:${index}` : null
}

function structuredRuleName(
  rules: Record<string, unknown>,
  kind: StructuredRuleKind,
  nameFor: ContentNameResolver,
): string {
  const reference = structuredRuleReference(rules, kind)
  const fallback = typeof reference?.name === 'string' ? reference.name : ''
  const key = structuredRuleKey(kind, reference)
  return key ? nameFor(key, fallback) : fallback
}

function structuredRuleReferences(rules: Record<string, unknown>): string[] {
  return (['equipment-category', 'damage-type'] as const).flatMap((kind) => {
    const key = structuredRuleKey(kind, structuredRuleReference(rules, kind))
    return key ? [key] : []
  })
}

function describeRules(
  rules: Record<string, unknown>,
  t: UiTranslator,
  nameFor: ContentNameResolver,
): string[] {
  const details: string[] = []
  const damage = rules.damage as { damage_dice?: unknown } | undefined
  const armorClass = rules.armor_class as { base?: unknown; dex_bonus?: unknown; max_bonus?: unknown } | undefined
  const cost = rules.cost as { quantity?: unknown; unit?: unknown } | undefined
  const categoryName = structuredRuleName(rules, 'equipment-category', nameFor)
  const damageTypeName = structuredRuleName(rules, 'damage-type', nameFor)

  if (categoryName) details.push(categoryName)
  if (damage?.damage_dice) {
    details.push(
      `${String(damage.damage_dice)}${damageTypeName ? ` ${damageTypeName}` : ''}`,
    )
  }
  if (armorClass?.base) {
    const dex = armorClass.dex_bonus ? t('sheet.rule.dex') : ''
    const cap = armorClass.max_bonus ? ` (+${String(armorClass.max_bonus)})` : ''
    details.push(`${t('sheet.rule.ac', { value: String(armorClass.base) })}${dex}${cap}`)
  }
  if (cost?.quantity !== undefined && cost?.unit) {
    details.push(`${String(cost.quantity)} ${String(cost.unit)}`)
  }
  return details.slice(0, 3)
}

function resourceLabel(key: string, t: UiTranslator): string {
  const pactSlot = key.match(/:slot:(\d+)$/)
  if (pactSlot) return t('sheet.levelLabel', { level: pactSlot[1] })
  return titleCase(key.split(':').at(-1) ?? key)
}

function NumberSaveField({
  label,
  value,
  min = 0,
  max,
  busy,
  testId,
  onSave,
}: {
  label: string
  value: number
  min?: number
  max?: number
  busy?: boolean
  testId?: string
  onSave: (value: number) => Promise<void> | void
}) {
  const { t } = useUiCopy()
  const [draft, setDraft] = useState(String(value))

  return (
    <form
      className="number-save"
      onSubmit={(event) => {
        event.preventDefault()
        const next = Number(draft)
        if (Number.isFinite(next)) void onSave(next)
      }}
    >
      <label>
        <span>{label}</span>
        <input
          data-testid={testId}
          type="number"
          min={min}
          max={max}
          value={draft}
          disabled={busy}
          onChange={(event) => setDraft(event.target.value)}
        />
      </label>
      <button
        className="button secondary compact"
        type="submit"
        data-testid={testId ? `${testId}-save` : undefined}
        disabled={busy || draft === String(value)}
      >
        {t('shared.save')}
      </button>
    </form>
  )
}

export function CharacterSheetView({
  sheet,
  conditionContent = [],
  inventoryContent = [],
  initialTab = 'attributes',
  busy = false,
  errorMessage = null,
  onPatch = async () => {},
  headerActions = null,
}: CharacterSheetViewProps) {
  const { locale, t } = useUiCopy()
  const [tab, setTab] = useState<CharacterTab>(initialTab)
  const [conditionRef, setConditionRef] = useState('')
  const [conditionNote, setConditionNote] = useState('')
  const [itemRef, setItemRef] = useState('')
  const [spellFilter, setSpellFilter] = useState('')
  const [inventoryFilter, setInventoryFilter] = useState('')
  const contentReferences = [
    ...conditionContent.map((entry) => entry.key),
    ...inventoryContent.map((entry) => entry.key),
    ...inventoryContent.flatMap((entry) => structuredRuleReferences(entry.data)),
    ...sheet.classes.map((entry) => entry.class_ref),
    ...sheet.features.map((feature) => feature.key),
    ...sheet.conditions.map((condition) => condition.condition_ref),
    ...sheet.spells.flatMap((spell) => [spell.spell_key, spell.source_key]),
    ...sheet.spellcasting.map((source) => source.source_key),
    ...sheet.inventory.map((item) => item.item_ref),
    ...sheet.inventory.flatMap((item) => structuredRuleReferences(item.rules)),
    ...Object.keys(sheet.skills).map((skill) => `srd5.1:skill:${skill}`),
  ]
  const { nameFor } = useContentPresentations(contentReferences)

  const conditionOptions = useMemo<SearchOption[]>(
    () =>
      conditionContent.map((entry) => ({
        value: entry.key,
        label: nameFor(entry.key, entry.name),
      })),
    [conditionContent, nameFor],
  )

  const inventoryOptions = useMemo<SearchOption[]>(
    () =>
      inventoryContent.map((entry) => ({
        value: entry.key,
        label: nameFor(entry.key, entry.name),
        description: structuredRuleName(entry.data, 'equipment-category', nameFor),
      })),
    [inventoryContent, nameFor],
  )

  const classSummary = sheet.classes
    .map((entry) => `${nameFor(entry.class_ref, entry.name)} ${entry.level}`)
    .join(' / ')
  const classNameByRef = new Map(
    sheet.classes.map((entry) => [entry.class_ref, nameFor(entry.class_ref, entry.name)]),
  )
  const preparedIds = sheet.spells
    .filter((spell) => spell.access_type === 'spellbook' && spell.prepared && !spell.source_profile_id)
    .map((spell) => spell.entry_id)
  const preparedSelections: PreparedSpellSelection[] = sheet.spells
    .filter(
      (spell) =>
        spell.prepared &&
        Boolean(spell.source_profile_id) &&
        (spell.access_type === 'spellbook' || spell.access_type === 'prepared'),
    )
    .map((spell) => ({
      spell_key: spell.spell_key,
      source_profile_id: spell.source_profile_id as string,
      source_access_entry_id: spell.source_access_entry_id ?? undefined,
    }))
  const filteredSpells = sheet.spells.filter((spell) =>
    `${nameFor(spell.spell_key, spell.name)} ${accessLabel(spell.access_type, t)}`
      .toLocaleLowerCase()
      .includes(spellFilter.toLocaleLowerCase()),
  )
  const filteredInventory = sheet.inventory.filter((item) =>
    nameFor(item.item_ref, item.name)
      .toLocaleLowerCase()
      .includes(inventoryFilter.toLocaleLowerCase()),
  )

  const patchInventory = (next: InventoryStateEntry[]) => onPatch({ inventory_state: next })
  const mutateInventoryItem = (entryId: string, update: Partial<InventoryStateEntry>) => {
    const next = inventoryState(sheet.inventory).map((entry) =>
      entry.entry_id === entryId ? { ...entry, ...update } : entry,
    )
    return patchInventory(next)
  }

  const updateCounter = (
    key: string,
    source: Record<string, ResourceCounter>,
    direction: 'use' | 'restore',
    field: 'spell_slots' | 'resources',
  ) => {
    const current = source[key]
    if (!current) return
    const next = countersToPatch(source)
    if (direction === 'use' && current.remaining > 0) {
      next[key] = { used: current.used + 1, remaining: current.remaining - 1 }
    } else if (direction === 'restore' && current.used > 0) {
      next[key] = { used: current.used - 1, remaining: current.remaining + 1 }
    } else {
      return
    }
    return onPatch({ [field]: next })
  }

  return (
    <main className="character-page">
      <div className="ambient ambient-one" />
      <div className="ambient ambient-two" />

      <section className="sheet-shell" aria-label={t('sheet.aria', { name: sheet.name })}>
        <header className="character-hero">
          <div className="hero-copy">
            <p className="eyebrow">{t('sheet.eyebrow')}</p>
            <h1>{sheet.name}</h1>
            <p className="character-meta">
              <strong>{t('sheet.level', { level: sheet.total_level })}</strong>
              <span>{classSummary}</span>
              <span>PB {signed(sheet.proficiency_bonus)}</span>
              <span>{t('sheet.buildVersion', { version: sheet.version_no })}</span>
            </p>
            {headerActions ? (
              <div className="character-hero__actions">{headerActions}</div>
            ) : null}
          </div>

          <div className="hero-stats" aria-label={t('sheet.liveState')}>
            <div className="hero-stat hp-stat">
              <span>HP</span>
              <strong data-testid="header-hp">{sheet.current_hp}</strong>
              <small>/ {sheet.max_hp}</small>
            </div>
            <div className="hero-stat">
              <span>{t('sheet.temp')}</span>
              <strong data-testid="header-temp-hp">{sheet.temporary_hp}</strong>
            </div>
            <div className="hero-stat">
              <span>AC</span>
              <strong data-testid="header-ac">{sheet.armor_class}</strong>
            </div>
            <div className="hero-stat">
              <span>{t('sheet.init')}</span>
              <strong>{signed(sheet.initiative_modifier)}</strong>
            </div>
          </div>

          <div className="hero-live-row">
            <div className="hero-editors">
              <NumberSaveField
                label={t('sheet.currentHp')}
                value={sheet.current_hp}
                min={0}
                max={sheet.max_hp}
                busy={busy}
                testId="current-hp-input"
                onSave={(value) => onPatch({ current_hp: value })}
              />
              <NumberSaveField
                label={t('sheet.temporaryHp')}
                value={sheet.temporary_hp}
                min={0}
                busy={busy}
                testId="temporary-hp-input"
                onSave={(value) => onPatch({ temporary_hp: value })}
              />
            </div>
            <div className="condition-strip" aria-label={t('sheet.conditions')}>
              <span className="condition-label">{t('sheet.conditions')}</span>
              {sheet.conditions.length ? (
                sheet.conditions.map((condition) => (
                  <button
                    type="button"
                    className="condition-chip"
                    key={condition.condition_ref}
                    title={condition.note ? `${condition.note} · ${t('sheet.removeCondition')}` : t('sheet.removeCondition')}
                    disabled={busy}
                    onClick={() =>
                      onPatch({
                        conditions: sheet.conditions
                          .filter((entry) => entry.condition_ref !== condition.condition_ref)
                          .map((entry) => ({ condition_ref: entry.condition_ref, note: entry.note })),
                      })
                    }
                  >
                    {nameFor(condition.condition_ref, condition.name)} ×
                  </button>
                ))
              ) : (
                <span className="quiet-pill">{t('sheet.none')}</span>
              )}
            </div>
          </div>
        </header>

        {errorMessage ? <div className="error-banner" role="alert">{errorMessage}</div> : null}

        <nav className="sheet-tabs" role="tablist" aria-label={t('sheet.tabsAria')}>
          {([
            ['attributes', 'sheet.tab.attributes', '01'],
            ['spells', 'sheet.tab.spells', '02'],
            ['inventory', 'sheet.tab.inventory', '03'],
          ] as const).map(([value, labelKey, number]) => (
            <button
              key={value}
              role="tab"
              type="button"
              aria-selected={tab === value}
              className={tab === value ? 'sheet-tab is-active' : 'sheet-tab'}
              onClick={() => setTab(value)}
            >
              <span>{number}</span>
              {t(labelKey)}
            </button>
          ))}
        </nav>

        {tab === 'attributes' ? (
          <section className="sheet-content" role="tabpanel" aria-label={t('sheet.tab.attributes')}>
            <div className="section-heading">
              <div>
                <p className="eyebrow">{t('sheet.coreProfile')}</p>
                <h2>{t('sheet.tab.attributes')}</h2>
              </div>
              <div className="hero-editors">
                <div className="passive-card">
                  <span>{t('sheet.passivePerception')}</span>
                  <strong>{sheet.passive_perception}</strong>
                </div>
                <div className="passive-card">
                  <span>{passiveInvestigationLabel(locale)}</span>
                  <strong>{sheet.passive_investigation}</strong>
                </div>
              </div>
            </div>

            <div className="ability-grid">
              {Object.entries(sheet.abilities).map(([key, ability]) => (
                <article className="ability-card" key={key}>
                  <span>{abilityLabel(key, t)}</span>
                  <strong>{signed(ability.modifier)}</strong>
                  <small>{t('sheet.score', { score: ability.score })}</small>
                </article>
              ))}
            </div>

            <article className="panel" data-testid="movement-panel">
              <div className="panel-title"><h3>{t('sheet.movement')}</h3><span>{t('sheet.movementHint')}</span></div>
              <div className="stat-list">
                <div><span>{t('sheet.movement.walk')}</span><strong data-testid="movement-walk">{t('sheet.distanceFeet', { value: sheet.walking_speed })}</strong></div>
                {sheet.swim_speed != null ? <div><span>{t('sheet.movement.swim')}</span><strong data-testid="movement-swim">{t('sheet.distanceFeet', { value: sheet.swim_speed })}</strong></div> : null}
                {sheet.climb_speed != null ? <div><span>{t('sheet.movement.climb')}</span><strong data-testid="movement-climb">{t('sheet.distanceFeet', { value: sheet.climb_speed })}</strong></div> : null}
                {sheet.fly_speed != null ? <div><span>{t('sheet.movement.fly')}</span><strong data-testid="movement-fly">{t('sheet.distanceFeet', { value: sheet.fly_speed })}</strong></div> : null}
              </div>
            </article>

            <div className="two-column-grid">
              <article className="panel">
                <div className="panel-title"><h3>{t('sheet.savingThrows')}</h3><span>{t('sheet.saves')}</span></div>
                <div className="stat-list">
                  {Object.entries(sheet.saving_throws).map(([key, value]) => (
                    <div key={key}><span>{abilityLabel(key, t)}</span><strong>{signed(value)}</strong></div>
                  ))}
                </div>
              </article>
              <article className="panel">
                <div className="panel-title"><h3>{t('sheet.skills')}</h3><span>{t('sheet.skills')}</span></div>
                <div className="stat-list skill-list">
                  {Object.entries(sheet.skills).map(([key, value]) => (
                    <div key={key}>
                      <span>{nameFor(`srd5.1:skill:${key}`, titleCase(key))}</span>
                      <strong>{signed(value)}</strong>
                    </div>
                  ))}
                </div>
              </article>
            </div>

            <div className="two-column-grid">
              <article className="panel">
                <div className="panel-title"><h3>{t('sheet.hitDice')}</h3><span>{t('sheet.availableTotal')}</span></div>
                <div className="dice-grid">
                  {sheet.hit_dice.map((hitDie) => (
                    <div className="die-card" key={hitDie.die}>
                      <strong>{hitDie.die}</strong>
                      <span data-testid={`hit-die-${hitDie.die}`}>{hitDie.available}/{hitDie.total}</span>
                      <div className="stepper">
                        <button
                          type="button"
                          aria-label={t('sheet.useDie', { die: hitDie.die })}
                          disabled={busy || hitDie.available <= 0}
                          onClick={() => {
                            const next = Object.fromEntries(sheet.hit_dice.map((entry) => [entry.die, entry.available]))
                            next[hitDie.die] = hitDie.available - 1
                            void onPatch({ hit_dice_state: next })
                          }}
                        >−</button>
                        <button
                          type="button"
                          aria-label={t('sheet.restoreDie', { die: hitDie.die })}
                          disabled={busy || hitDie.available >= hitDie.total}
                          onClick={() => {
                            const next = Object.fromEntries(sheet.hit_dice.map((entry) => [entry.die, entry.available]))
                            next[hitDie.die] = hitDie.available + 1
                            void onPatch({ hit_dice_state: next })
                          }}
                        >+</button>
                      </div>
                    </div>
                  ))}
                </div>
              </article>

              <article className="panel">
                <div className="panel-title"><h3>{t('sheet.conditions')}</h3><span>{t('sheet.liveState')}</span></div>
                <SearchableSelect
                  label={t('sheet.addCondition')}
                  options={conditionOptions}
                  value={conditionRef}
                  onChange={setConditionRef}
                  disabled={busy}
                />
                <label className="text-field">
                  <span>{t('sheet.noteOptional')}</span>
                  <input
                    value={conditionNote}
                    placeholder={t('sheet.notePlaceholder')}
                    disabled={busy}
                    onChange={(event) => setConditionNote(event.target.value)}
                  />
                </label>
                <button
                  type="button"
                  className="button primary full"
                  disabled={busy || !conditionRef || sheet.conditions.some((entry) => entry.condition_ref === conditionRef)}
                  onClick={async () => {
                    await onPatch({
                      conditions: [
                        ...sheet.conditions.map((entry) => ({ condition_ref: entry.condition_ref, note: entry.note })),
                        { condition_ref: conditionRef, note: conditionNote.trim() || undefined },
                      ],
                    })
                    setConditionRef('')
                    setConditionNote('')
                  }}
                >
                  {t('sheet.addConditionButton')}
                </button>
              </article>
            </div>

            <article className="panel feature-panel">
              <div className="panel-title"><h3>{t('sheet.features')}</h3><span>{t('sheet.characterAbilities')}</span></div>
              <div className="feature-chips">
                {sheet.features.length
                  ? sheet.features.map((feature) => (
                      <span key={feature.key}>{nameFor(feature.key, feature.name)}</span>
                    ))
                  : <em>{t('sheet.noData')}</em>}
              </div>
            </article>

            <details className="roleplay-panel">
              <summary>
                <span><strong>{t('sheet.roleplay')}</strong><small>{t('sheet.roleplayHint')}</small></span>
                <span>{t('sheet.expand')}</span>
              </summary>
              <div className="roleplay-grid">
                {sheet.roleplay_profile.appearance ? <div><span>{t('sheet.appearance')}</span><p>{sheet.roleplay_profile.appearance}</p></div> : null}
                {sheet.roleplay_profile.biography ? <div><span>{t('sheet.biography')}</span><p>{sheet.roleplay_profile.biography}</p></div> : null}
                {sheet.roleplay_profile.personality_traits.length ? <div><span>{t('sheet.personality')}</span><p>{sheet.roleplay_profile.personality_traits.join(' · ')}</p></div> : null}
                {sheet.roleplay_profile.ideals.length ? <div><span>{t('sheet.ideals')}</span><p>{sheet.roleplay_profile.ideals.join(' · ')}</p></div> : null}
                {sheet.roleplay_profile.bonds.length ? <div><span>{t('sheet.bonds')}</span><p>{sheet.roleplay_profile.bonds.join(' · ')}</p></div> : null}
                {sheet.roleplay_profile.flaws.length ? <div><span>{t('sheet.flaws')}</span><p>{sheet.roleplay_profile.flaws.join(' · ')}</p></div> : null}
                {!sheet.roleplay_profile.appearance &&
                !sheet.roleplay_profile.biography &&
                !sheet.roleplay_profile.personality_traits.length &&
                !sheet.roleplay_profile.ideals.length &&
                !sheet.roleplay_profile.bonds.length &&
                !sheet.roleplay_profile.flaws.length ? (
                  <p className="empty-copy">{t('sheet.noRoleplay')}</p>
                ) : null}
              </div>
            </details>
          </section>
        ) : null}

        {tab === 'spells' ? (
          <section className="sheet-content" role="tabpanel" aria-label={t('sheet.tab.spells')}>
            <div className="section-heading">
              <div><p className="eyebrow">{t('sheet.spellbookResources')}</p><h2>{t('sheet.tab.spells')}</h2></div>
              <label className="inline-search"><span>{t('sheet.searchSpells')}</span><input value={spellFilter} placeholder={t('sheet.searchSpellsPlaceholder')} onChange={(event) => setSpellFilter(event.target.value)} /></label>
            </div>

            <div className="spellcasting-grid">
              {sheet.spellcasting.map((source) => (
                <article className="spellcasting-card" key={source.source_key}>
                  <span>{nameFor(source.source_key, source.source_name)}</span>
                  <strong>{abilityLabel(source.ability, t)}</strong>
                  <div><small>{t('sheet.saveDc')}</small><b>{source.save_dc}</b><small>{t('sheet.attack')}</small><b>{signed(source.attack_modifier)}</b></div>
                </article>
              ))}
            </div>

            <article className="panel">
              <div className="panel-title"><h3>{t('sheet.spellSlots')}</h3><span>{t('sheet.serverState')}</span></div>
              <div className="slot-grid">
                {Object.entries(sheet.spell_slots).sort(([a], [b]) => Number(a) - Number(b)).map(([level, counter]) => (
                  <div className="slot-card" key={level}>
                    <span>{t('sheet.levelLabel', { level })}</span>
                    <strong data-testid={`spell-slot-${level}-counter`}>{counter.remaining} / {counter.used + counter.remaining}</strong>
                    <small>{t('sheet.remainingTotal')}</small>
                    <div className="slot-actions">
                      <button type="button" data-testid={`spell-slot-${level}-use`} disabled={busy || counter.remaining <= 0} onClick={() => void updateCounter(level, sheet.spell_slots, 'use', 'spell_slots')}>{t('sheet.useOneSlot')}</button>
                      <button type="button" disabled={busy || counter.used <= 0} onClick={() => void updateCounter(level, sheet.spell_slots, 'restore', 'spell_slots')}>{t('sheet.restoreOneSlot')}</button>
                    </div>
                  </div>
                ))}
              </div>
            </article>

            {Object.keys(sheet.resources).length ? (
              <article className="panel">
                <div className="panel-title"><h3>{t('sheet.classResources')}</h3><span>{t('sheet.resources')}</span></div>
                <div className="resource-list">
                  {Object.entries(sheet.resources).map(([key, counter]) => (
                    <div key={key}>
                      <span>{resourceLabel(key, t)}</span>
                      <strong>{counter.remaining} / {counter.used + counter.remaining}</strong>
                      <div className="mini-actions">
                        <button type="button" disabled={busy || counter.remaining <= 0} onClick={() => void updateCounter(key, sheet.resources, 'use', 'resources')}>{t('sheet.use')}</button>
                        <button type="button" disabled={busy || counter.used <= 0} onClick={() => void updateCounter(key, sheet.resources, 'restore', 'resources')}>{t('sheet.restore')}</button>
                      </div>
                    </div>
                  ))}
                </div>
              </article>
            ) : null}

            <div className="spell-list">
              {filteredSpells.map((spell) => {
                const canonicalPrepare =
                  (spell.access_type === 'spellbook' || spell.access_type === 'prepared') &&
                  Boolean(spell.source_profile_id)
                const legacyPrepare = spell.access_type === 'spellbook' && !spell.source_profile_id
                const canPrepare = canonicalPrepare || legacyPrepare
                const localizedSpellName = nameFor(spell.spell_key, spell.name)
                const localizedSourceName =
                  classNameByRef.get(spell.source_key) ?? nameFor(spell.source_key, titleCase(spell.source_type))
                return (
                  <article className={spell.prepared ? 'spell-card is-prepared' : 'spell-card'} key={spell.entry_id}>
                    <div>
                      <span className="access-badge">{accessLabel(spell.access_type, t)}</span>
                      <h3>{localizedSpellName}</h3>
                      <p>{localizedSourceName}</p>
                    </div>
                    <div className="prepared-control">
                      <span className={spell.prepared ? 'prepared-badge on' : 'prepared-badge'}>{spell.prepared ? t('sheet.prepared') : t('sheet.unprepared')}</span>
                      {canPrepare ? (
                        <button
                          type="button"
                          className="button secondary compact"
                          disabled={busy}
                          onClick={() => {
                            if (canonicalPrepare && spell.source_profile_id) {
                              const next = spell.prepared
                                ? preparedSelections.filter(
                                    (selection) =>
                                      selection.source_profile_id !== spell.source_profile_id ||
                                      selection.spell_key !== spell.spell_key,
                                  )
                                : [
                                    ...preparedSelections,
                                    {
                                      spell_key: spell.spell_key,
                                      source_profile_id: spell.source_profile_id,
                                      source_access_entry_id: spell.source_access_entry_id ?? undefined,
                                    },
                                  ]
                              void onPatch({ prepared_spells: next })
                              return
                            }
                            const next = spell.prepared
                              ? preparedIds.filter((entryId) => entryId !== spell.entry_id)
                              : [...preparedIds, spell.entry_id]
                            void onPatch({ prepared_spell_entry_ids: next })
                          }}
                        >
                          {spell.prepared ? t('sheet.unprepare') : t('sheet.prepare')}
                        </button>
                      ) : null}
                    </div>
                  </article>
                )
              })}
              {!filteredSpells.length ? <p className="empty-copy">{t('sheet.noSpells')}</p> : null}
            </div>
          </section>
        ) : null}

        {tab === 'inventory' ? (
          <section className="sheet-content" role="tabpanel" aria-label={t('sheet.tab.inventory')}>
            <div className="section-heading">
              <div><p className="eyebrow">{t('sheet.liveInventory')}</p><h2>{t('sheet.tab.inventory')}</h2></div>
              <label className="inline-search"><span>{t('sheet.searchInventory')}</span><input value={inventoryFilter} placeholder={t('sheet.searchInventoryPlaceholder')} onChange={(event) => setInventoryFilter(event.target.value)} /></label>
            </div>

            <article className="panel add-inventory-panel">
              <div className="panel-title"><h3>{t('sheet.addItem')}</h3><span>{t('sheet.srdReference')}</span></div>
              <div className="add-inventory-row">
                <SearchableSelect label={t('sheet.itemName')} options={inventoryOptions} value={itemRef} onChange={setItemRef} disabled={busy} />
                <button
                  type="button"
                  className="button primary"
                  disabled={busy || !itemRef}
                  onClick={async () => {
                    const entryId = `inventory:ui:${typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : Date.now()}`
                    await patchInventory([
                      ...inventoryState(sheet.inventory),
                      { entry_id: entryId, item_ref: itemRef, quantity: 1, equipped: false, carried: true },
                    ])
                    setItemRef('')
                  }}
                >
                  {t('sheet.addInventory')}
                </button>
              </div>
            </article>

            <div className="inventory-list">
              {filteredInventory.map((item) => {
                const ruleDetails = describeRules(item.rules, t, nameFor)
                const localizedItemName = nameFor(item.item_ref, item.name)
                return (
                  <article className="inventory-card" key={item.entry_id} data-testid={`inventory-${item.entry_id}`}>
                    <div className="inventory-main">
                      <div className="item-monogram" aria-hidden="true">{localizedItemName.slice(0, 1)}</div>
                      <div>
                        <h3>{localizedItemName}</h3>
                        <p>{ruleDetails.length ? ruleDetails.join(' · ') : t('sheet.srdItem')}</p>
                        <div className="item-badges">
                          <span className={item.equipped ? 'item-badge active' : 'item-badge'}>{item.equipped ? t('sheet.equipped') : t('sheet.unequipped')}</span>
                          <span className={item.carried ? 'item-badge active' : 'item-badge'}>{item.carried ? t('sheet.carried') : t('sheet.stored')}</span>
                        </div>
                      </div>
                    </div>
                    <div className="inventory-actions">
                      <div className="quantity-stepper">
                        <span>{t('sheet.qty')}</span>
                        <button type="button" aria-label={t('sheet.decrementQty', { name: localizedItemName })} data-testid={`inventory-${item.entry_id}-decrement`} disabled={busy || item.quantity <= 1} onClick={() => void mutateInventoryItem(item.entry_id, { quantity: item.quantity - 1 })}>−</button>
                        <strong data-testid={`inventory-${item.entry_id}-quantity`}>{item.quantity}</strong>
                        <button type="button" aria-label={t('sheet.incrementQty', { name: localizedItemName })} disabled={busy} onClick={() => void mutateInventoryItem(item.entry_id, { quantity: item.quantity + 1 })}>＋</button>
                      </div>
                      <button type="button" className="button secondary compact" data-testid={`inventory-${item.entry_id}-equip`} disabled={busy} onClick={() => void mutateInventoryItem(item.entry_id, { equipped: !item.equipped })}>{item.equipped ? t('sheet.unequip') : t('sheet.equip')}</button>
                      <button type="button" className="button secondary compact" disabled={busy} onClick={() => void mutateInventoryItem(item.entry_id, { carried: !item.carried })}>{item.carried ? t('sheet.putDown') : t('sheet.carry')}</button>
                      <button type="button" className="icon-danger" aria-label={t('sheet.removeItem', { name: localizedItemName })} disabled={busy} onClick={() => void patchInventory(inventoryState(sheet.inventory).filter((entry) => entry.entry_id !== item.entry_id))}>×</button>
                    </div>
                  </article>
                )
              })}
              {!filteredInventory.length ? <p className="empty-copy">{t('sheet.noInventory')}</p> : null}
            </div>
          </section>
        ) : null}

        <footer className="sheet-footer">
          <span>{t('sheet.ruleset', { ruleset: sheet.ruleset })}</span>
          <span>{t('sheet.authoritative')}</span>
          {busy ? <strong>{t('shared.saving')}</strong> : <strong>{t('shared.synced')}</strong>}
        </footer>
      </section>
    </main>
  )
}

export function CharacterSheetPage({ characterId }: { characterId: string }) {
  const { t } = useUiCopy()
  const queryClient = useQueryClient()
  const sheetQuery = useQuery({
    queryKey: ['character-sheet', characterId],
    queryFn: () => getCharacterSheet(characterId),
  })
  const conditionQuery = useQuery({
    queryKey: ['rules-content', 'conditions'],
    queryFn: () => listContent('conditions'),
  })
  const equipmentQuery = useQuery({
    queryKey: ['rules-content', 'equipment'],
    queryFn: () => listContent('equipment'),
  })
  const itemQuery = useQuery({
    queryKey: ['rules-content', 'magic-items'],
    queryFn: () => listContent('magic-items'),
  })

  const mutation = useMutation({
    mutationFn: (patch: CharacterStatePatch) => patchCharacterState(characterId, patch),
    onSuccess: (authoritativeSheet) => {
      queryClient.setQueryData(['character-sheet', characterId], authoritativeSheet)
    },
  })

  if (sheetQuery.isPending) {
    return (
      <main className="character-page loading-page">
        <div className="loading-card"><span className="loading-mark">AT</span><h1>{t('sheet.loadingTitle')}</h1><p>{t('sheet.loadingHint')}</p></div>
      </main>
    )
  }

  if (sheetQuery.isError || !sheetQuery.data) {
    return (
      <main className="character-page loading-page">
        <div className="loading-card error-state"><span className="loading-mark">!</span><h1>{t('sheet.errorTitle')}</h1><p>{sheetQuery.error instanceof Error ? sheetQuery.error.message : t('sheet.unknownError')}</p></div>
      </main>
    )
  }

  const contentError = [conditionQuery.error, equipmentQuery.error, itemQuery.error].find(Boolean)
  const mutationError = mutation.error
  const errorMessage = mutationError instanceof Error
    ? mutationError.message
    : contentError instanceof Error
      ? t('sheet.contentError', { message: contentError.message })
      : null

  return (
    <CharacterSheetView
      sheet={sheetQuery.data}
      conditionContent={conditionQuery.data ?? []}
      inventoryContent={[...(equipmentQuery.data ?? []), ...(itemQuery.data ?? [])]}
      busy={mutation.isPending}
      errorMessage={errorMessage}
      headerActions={<ExportCharacterButton characterId={characterId} placement="sheet" />}
      onPatch={async (patch) => {
        await mutation.mutateAsync(patch)
      }}
    />
  )
}
