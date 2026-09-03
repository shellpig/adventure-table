import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getCharacterSheet,
  listContent,
  patchCharacterState,
  type ActiveInfusionState,
  type ArtificerSummaryDTO,
  type CharacterSheetDTO,
  type ContentEntry,
} from '../../api/character'
import {
  getBuilderDraft,
  getBuilderReview,
  type BuilderReviewDTO,
} from '../../api/characterBuilder'
import type { StateReconciliationPreview } from '../../api/characterVersions'
import { SearchableSelect } from '../../components/SearchableSelect'
import { useContentPresentations } from '../../i18n/useContentPresentations'
import { CharacterBuilderPage } from '../character-builder/CharacterBuilderPage'
import { CharacterSheetPage } from '../character-sheet/CharacterSheetPage'
import './artificer.css'

const ARTIFICER_REF = 'tce:class:artificer'
const ARMOR_MODEL_FEATURE_REF = 'tce:feature:armor-model'

type ReviewState = StateReconciliationPreview['proposed_state'] & {
  active_infusions?: ActiveInfusionState[]
  feature_modes?: Record<string, string>
  spell_storing_item?: {
    inventory_entry_id: string
    spell_ref: string
    remaining_uses: number
  } | null
}

type ReviewWithArtificer = BuilderReviewDTO & {
  derived_stats?: (NonNullable<BuilderReviewDTO['derived_stats']> & {
    artificer?: ArtificerSummaryDTO | null
  }) | null
  reconciliation?: (Omit<StateReconciliationPreview, 'proposed_state'> & {
    proposed_state: ReviewState
  }) | null
}

const COPY = {
  en: {
    eyebrow: 'M01-H · Artificer Advanced State',
    title: 'Artificer Workbench',
    reviewTitle: 'Artificer Review',
    known: 'Known Infusions',
    active: 'Active Infusions',
    activeCapacity: 'Active capacity',
    attunement: 'Attunement capacity',
    resources: 'Tracked resources',
    armorModel: 'Armor Model',
    spellStoring: 'Spell-Storing Item',
    manual: 'Manual-resolution features',
    none: 'None',
    infusion: 'Infusion',
    targetItem: 'Target inventory item',
    armorPart: 'Arcane Armor part (only for Armor Modifications bonus slots)',
    activate: 'Activate',
    deactivate: 'Deactivate',
    use: 'Use',
    restore: 'Restore',
    saveMode: 'Switch model',
    storedSpell: 'Stored spell',
    store: 'Store spell',
    clear: 'Clear stored spell',
    requiresServer: 'Eligibility is server-authoritative; invalid combinations are rejected without changing state.',
    manualHint: 'The state/metadata is tracked here; combat, reaction, random-table, and other deferred effects are resolved manually.',
    attunementBypass: 'Magic Item Savant requirement bypasses',
    noBypass: 'No bypasses at this level',
    reviewHint: 'Review reflects the proposed immutable Build plus preserved Current State. Conflicts remain blocking and are never silently deleted.',
    charges: 'charges',
    remaining: 'remaining',
    level: 'Lv',
  },
  'zh-TW': {
    eyebrow: 'M01-H · 奇械師進階狀態',
    title: '奇械師工作台',
    reviewTitle: '奇械師檢視',
    known: '已知注法',
    active: '啟用中的注法',
    activeCapacity: '啟用注法容量',
    attunement: '調諧上限',
    resources: '追蹤中的資源',
    armorModel: '裝甲型號',
    spellStoring: '儲法物品',
    manual: '需手動判定的能力',
    none: '無',
    infusion: '注法',
    targetItem: '目標物品欄項目',
    armorPart: '奧能裝甲部位（僅裝甲改造的額外注法槽需要）',
    activate: '啟用',
    deactivate: '解除',
    use: '使用',
    restore: '恢復',
    saveMode: '切換型號',
    storedSpell: '儲存法術',
    store: '存入法術',
    clear: '清除儲存法術',
    requiresServer: '合法性由伺服器權威判定；不合法的組合會被拒絕且不改變狀態。',
    manualHint: '這裡追蹤狀態與規則資料；戰鬥、反應、隨機表與其他延後效果仍由玩家手動處理。',
    attunementBypass: '魔法物品專家的限制無視',
    noBypass: '目前等級沒有額外無視條件',
    reviewHint: '檢視內容同時反映預定的新角色配置與保留的即時狀態；衝突會阻擋確認，不會偷偷刪除狀態。',
    charges: '充能',
    remaining: '剩餘',
    level: '等級',
  },
} as const

type PanelLocale = keyof typeof COPY

const MODE_ZH: Record<string, string> = {
  guardian: '守護者',
  infiltrator: '滲透者',
}

const PART_ZH: Record<string, string> = {
  armor: '胸甲',
  boots: '靴子',
  helmet: '頭盔',
  special_weapon: '特殊武器',
}

const BYPASS_ZH: Record<string, string> = {
  class: '職業需求',
  race: '種族需求',
  spell: '施法需求',
  level: '等級需求',
}

function modeLabel(locale: PanelLocale, value: string): string {
  return locale === 'zh-TW' ? MODE_ZH[value] ?? value : value.replaceAll('-', ' ')
}

function armorPartLabel(locale: PanelLocale, value: string): string {
  return locale === 'zh-TW' ? PART_ZH[value] ?? value : value.replaceAll('_', ' ')
}

function bypassLabel(locale: PanelLocale, value: string): string {
  return locale === 'zh-TW' ? BYPASS_ZH[value] ?? value : value.replaceAll('_', ' ')
}

function toActiveState(summary: ArtificerSummaryDTO): ActiveInfusionState[] {
  return summary.active_infusions.map((active) => ({
    inventory_entry_id: active.inventory_entry_id,
    infusion_ref: active.infusion_ref,
    resource: active.resource ?? undefined,
    arcane_armor_part:
      active.arcane_armor_part === 'armor' ||
      active.arcane_armor_part === 'boots' ||
      active.arcane_armor_part === 'helmet' ||
      active.arcane_armor_part === 'special_weapon'
        ? active.arcane_armor_part
        : undefined,
  }))
}

function activeStateFromReview(review: ReviewWithArtificer): ActiveInfusionState[] {
  const proposed = review.reconciliation?.proposed_state.active_infusions
  if (Array.isArray(proposed)) return proposed
  return review.derived_stats?.artificer
    ? toActiveState(review.derived_stats.artificer)
    : []
}

function referenceName(entry: ContentEntry): string {
  return entry.name || entry.key
}

function ArtificerSummaryCards({
  summary,
  activeCount,
  armorModel,
}: {
  summary: ArtificerSummaryDTO
  activeCount: number
  armorModel?: string | null
}) {
  const references = [
    ...summary.known_infusions.map((entry) => entry.infusion_ref),
    ...summary.tracked_resources.map((entry) => entry.feature_ref),
    ...summary.manual_features.map((entry) => entry.feature_ref),
  ]
  const { nameFor, locale } = useContentPresentations(references)
  const copy = COPY[locale]
  const effectiveArmorModel = armorModel || summary.armor_model

  return (
    <>
      <div className="artificer-card-grid">
        <article className="artificer-card">
          <span>{copy.known}</span>
          <strong>{summary.known_infusions.length} / {summary.known_infusion_limit}</strong>
          <p>{summary.known_infusions.map((entry) => nameFor(entry.infusion_ref, entry.name)).join(' · ') || copy.none}</p>
        </article>
        <article className="artificer-card">
          <span>{copy.activeCapacity}</span>
          <strong>{activeCount} / {summary.active_infusion_capacity}</strong>
          <p>{summary.active_infusion_base_capacity} + {summary.active_infusion_capacity_bonus}</p>
        </article>
        <article className="artificer-card">
          <span>{copy.attunement}</span>
          <strong>{summary.attunement_capacity}</strong>
          <p>
            {summary.attunement_requirement_bypasses.length
              ? `${copy.attunementBypass}: ${summary.attunement_requirement_bypasses.map((value) => bypassLabel(locale, value)).join('、')}`
              : copy.noBypass}
          </p>
        </article>
        {summary.armor_model_options.length ? (
          <article className="artificer-card">
            <span>{copy.armorModel}</span>
            <strong>{effectiveArmorModel ? modeLabel(locale, effectiveArmorModel) : copy.none}</strong>
            <p>{summary.armor_model_options.map((value) => modeLabel(locale, value)).join(' / ')}</p>
          </article>
        ) : null}
      </div>

      {summary.tracked_resources.length ? (
        <section className="artificer-subsection">
          <h3>{copy.resources}</h3>
          <div className="artificer-resource-list">
            {summary.tracked_resources.map((resource) => (
              <div key={resource.resource_id}>
                <span>{nameFor(resource.feature_ref, resource.feature_name)}</span>
                <strong>{resource.remaining} / {resource.capacity}</strong>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {summary.manual_features.length ? (
        <section className="artificer-subsection">
          <h3>{copy.manual}</h3>
          <div className="artificer-chip-list">
            {summary.manual_features.map((feature) => (
              <span key={feature.feature_ref}>{nameFor(feature.feature_ref, feature.feature_name)}</span>
            ))}
          </div>
          <p className="artificer-note">{copy.manualHint}</p>
        </section>
      ) : null}
    </>
  )
}

function ArtificerSheetPanel({
  sheet,
  busy,
  errorMessage,
  onPatch,
}: {
  sheet: CharacterSheetDTO
  busy: boolean
  errorMessage?: string | null
  onPatch: (patch: Parameters<typeof patchCharacterState>[1]) => Promise<void>
}) {
  const summary = sheet.artificer
  const [infusionRef, setInfusionRef] = useState('')
  const [inventoryEntryId, setInventoryEntryId] = useState('')
  const [armorPart, setArmorPart] = useState('')
  const [storedItemId, setStoredItemId] = useState('')
  const [storedSpellRef, setStoredSpellRef] = useState('')
  const [armorModel, setArmorModel] = useState(summary?.armor_model ?? '')

  const spellContentQuery = useQuery({
    queryKey: ['rules-content', 'spells', 'm01-h-artificer'],
    queryFn: () => listContent('spells'),
    enabled: Boolean(summary?.spell_storing_item_capacity),
  })

  const references = summary
    ? [
        ARTIFICER_REF,
        ...summary.known_infusions.map((entry) => entry.infusion_ref),
        ...summary.active_infusions.flatMap((entry) => [entry.infusion_ref, entry.inventory_item_ref]),
        ...sheet.inventory.map((entry) => entry.item_ref),
        ...(spellContentQuery.data ?? []).map((entry) => entry.key),
      ]
    : [ARTIFICER_REF]
  const { nameFor, locale } = useContentPresentations(references)
  const copy = COPY[locale]

  const artificerSpellKeys = useMemo(
    () => new Set(sheet.spells.filter((spell) => spell.source_key === ARTIFICER_REF).map((spell) => spell.spell_key)),
    [sheet.spells],
  )
  const spellOptions = useMemo(
    () =>
      (spellContentQuery.data ?? [])
        .filter((entry) => {
          const level = entry.data.level
          const castingTime = entry.data.casting_time
          return artificerSpellKeys.has(entry.key) &&
            (level === 1 || level === 2) &&
            typeof castingTime === 'string' &&
            ['1 action', 'action'].includes(castingTime.trim().toLowerCase())
        })
        .map((entry) => ({ value: entry.key, label: nameFor(entry.key, referenceName(entry)) })),
    [artificerSpellKeys, nameFor, spellContentQuery.data],
  )

  if (!summary) return null

  const activeState = toActiveState(summary)
  const activeTargets = new Set(summary.active_infusions.map((entry) => entry.inventory_entry_id))
  const activeInfusionRefs = new Set(summary.active_infusions.map((entry) => entry.infusion_ref))
  const infusionOptions = summary.known_infusions.map((entry) => ({
    value: entry.infusion_ref,
    label: nameFor(entry.infusion_ref, entry.name),
    disabled: activeInfusionRefs.has(entry.infusion_ref),
    disabledReason: activeInfusionRefs.has(entry.infusion_ref) ? copy.active : undefined,
  }))
  const inventoryOptions = sheet.inventory.map((entry) => ({
    value: entry.entry_id,
    label: nameFor(entry.item_ref, entry.name),
    disabled: activeTargets.has(entry.entry_id),
    disabledReason: activeTargets.has(entry.entry_id) ? copy.active : undefined,
  }))
  const chosenInfusion = summary.known_infusions.find((entry) => entry.infusion_ref === infusionRef)

  const patchActive = async (next: ActiveInfusionState[]) => {
    await onPatch({ active_infusions: next })
  }

  const updateActiveResource = async (
    inventoryId: string,
    direction: 'use' | 'restore',
  ) => {
    const next = activeState.map((entry) => {
      if (entry.inventory_entry_id !== inventoryId || !entry.resource) return entry
      if (direction === 'use' && entry.resource.remaining > 0) {
        return {
          ...entry,
          resource: {
            used: entry.resource.used + 1,
            remaining: entry.resource.remaining - 1,
          },
        }
      }
      if (direction === 'restore' && entry.resource.used > 0) {
        return {
          ...entry,
          resource: {
            used: entry.resource.used - 1,
            remaining: entry.resource.remaining + 1,
          },
        }
      }
      return entry
    })
    await patchActive(next)
  }

  return (
    <section className="artificer-route-panel" aria-label={copy.title}>
      <div className="artificer-panel-heading">
        <div>
          <p className="eyebrow">{copy.eyebrow}</p>
          <h2>{nameFor(ARTIFICER_REF, copy.title)}</h2>
        </div>
        <strong>{copy.level} {summary.artificer_level}</strong>
      </div>

      {errorMessage ? <div className="error-banner">{errorMessage}</div> : null}
      <ArtificerSummaryCards summary={summary} activeCount={summary.active_infusion_count} armorModel={summary.armor_model} />

      <section className="artificer-subsection">
        <h3>{copy.active}</h3>
        <div className="artificer-active-list">
          {summary.active_infusions.map((active) => (
            <article key={active.inventory_entry_id} className="artificer-active-row">
              <div>
                <strong>{nameFor(active.infusion_ref, active.infusion_name)}</strong>
                <span>{nameFor(active.inventory_item_ref, active.inventory_item_name)}</span>
                {active.arcane_armor_part ? <small>{armorPartLabel(locale, active.arcane_armor_part)}</small> : null}
              </div>
              {active.resource ? (
                <div className="artificer-inline-actions">
                  <span>{active.resource.remaining} / {active.resource.used + active.resource.remaining} {copy.charges}</span>
                  <button type="button" disabled={busy || active.resource.remaining <= 0} onClick={() => void updateActiveResource(active.inventory_entry_id, 'use')}>{copy.use}</button>
                  <button type="button" disabled={busy || active.resource.used <= 0} onClick={() => void updateActiveResource(active.inventory_entry_id, 'restore')}>{copy.restore}</button>
                </div>
              ) : null}
              <button type="button" className="button secondary compact" disabled={busy} onClick={() => void patchActive(activeState.filter((entry) => entry.inventory_entry_id !== active.inventory_entry_id))}>{copy.deactivate}</button>
            </article>
          ))}
          {!summary.active_infusions.length ? <p className="artificer-note">{copy.none}</p> : null}
        </div>

        <div className="artificer-form-grid">
          <SearchableSelect label={copy.infusion} value={infusionRef} options={infusionOptions} onChange={setInfusionRef} disabled={busy} />
          <SearchableSelect label={copy.targetItem} value={inventoryEntryId} options={inventoryOptions} onChange={setInventoryEntryId} disabled={busy} />
          {summary.armor_modification_parts.length ? (
            <label className="artificer-field">
              <span>{copy.armorPart}</span>
              <select value={armorPart} disabled={busy} onChange={(event) => setArmorPart(event.target.value)}>
                <option value="">—</option>
                {summary.armor_modification_parts.map((part) => <option key={part} value={part}>{armorPartLabel(locale, part)}</option>)}
              </select>
            </label>
          ) : null}
          <button
            type="button"
            className="button primary"
            disabled={busy || !infusionRef || !inventoryEntryId || summary.active_infusion_count >= summary.active_infusion_capacity}
            onClick={async () => {
              const next: ActiveInfusionState = {
                inventory_entry_id: inventoryEntryId,
                infusion_ref: infusionRef,
                resource: chosenInfusion?.charge_capacity != null
                  ? { used: 0, remaining: chosenInfusion.charge_capacity }
                  : undefined,
                arcane_armor_part:
                  armorPart === 'armor' || armorPart === 'boots' || armorPart === 'helmet' || armorPart === 'special_weapon'
                    ? armorPart
                    : undefined,
              }
              await patchActive([...activeState, next])
              setInfusionRef('')
              setInventoryEntryId('')
              setArmorPart('')
            }}
          >
            {copy.activate}
          </button>
        </div>
        <p className="artificer-note">{copy.requiresServer}</p>
      </section>

      {summary.armor_model_options.length ? (
        <section className="artificer-subsection">
          <h3>{copy.armorModel}</h3>
          <div className="artificer-inline-form">
            <select value={armorModel} disabled={busy} onChange={(event) => setArmorModel(event.target.value)}>
              {summary.armor_model_options.map((mode) => <option key={mode} value={mode}>{modeLabel(locale, mode)}</option>)}
            </select>
            <button type="button" className="button secondary compact" disabled={busy || !armorModel || armorModel === summary.armor_model} onClick={() => void onPatch({ feature_modes: { [ARMOR_MODEL_FEATURE_REF]: armorModel } })}>{copy.saveMode}</button>
          </div>
        </section>
      ) : null}

      {summary.spell_storing_item_capacity > 0 ? (
        <section className="artificer-subsection">
          <h3>{copy.spellStoring}</h3>
          {summary.spell_storing_item ? (
            <article className="artificer-active-row">
              <div>
                <strong>{nameFor(summary.spell_storing_item.spell_ref, summary.spell_storing_item.spell_name)}</strong>
                <span>{nameFor(summary.spell_storing_item.inventory_item_ref, summary.spell_storing_item.inventory_item_name)}</span>
              </div>
              <div className="artificer-inline-actions">
                <span>{summary.spell_storing_item.remaining_uses} / {summary.spell_storing_item.capacity} {copy.remaining}</span>
                <button type="button" disabled={busy || summary.spell_storing_item.remaining_uses <= 0} onClick={() => void onPatch({ spell_storing_item: { inventory_entry_id: summary.spell_storing_item!.inventory_entry_id, spell_ref: summary.spell_storing_item!.spell_ref, remaining_uses: summary.spell_storing_item!.remaining_uses - 1 } })}>{copy.use}</button>
                <button type="button" disabled={busy || summary.spell_storing_item.remaining_uses >= summary.spell_storing_item.capacity} onClick={() => void onPatch({ spell_storing_item: { inventory_entry_id: summary.spell_storing_item!.inventory_entry_id, spell_ref: summary.spell_storing_item!.spell_ref, remaining_uses: summary.spell_storing_item!.remaining_uses + 1 } })}>{copy.restore}</button>
                <button type="button" className="button secondary compact" disabled={busy} onClick={() => void onPatch({ spell_storing_item: null })}>{copy.clear}</button>
              </div>
            </article>
          ) : (
            <div className="artificer-form-grid">
              <SearchableSelect label={copy.targetItem} value={storedItemId} options={sheet.inventory.map((entry) => ({ value: entry.entry_id, label: nameFor(entry.item_ref, entry.name) }))} onChange={setStoredItemId} disabled={busy} />
              <SearchableSelect label={copy.storedSpell} value={storedSpellRef} options={spellOptions} onChange={setStoredSpellRef} disabled={busy || spellContentQuery.isPending} />
              <button
                type="button"
                className="button primary"
                disabled={busy || !storedItemId || !storedSpellRef}
                onClick={async () => {
                  await onPatch({ spell_storing_item: { inventory_entry_id: storedItemId, spell_ref: storedSpellRef, remaining_uses: summary.spell_storing_item_capacity } })
                  setStoredItemId('')
                  setStoredSpellRef('')
                }}
              >
                {copy.store}
              </button>
            </div>
          )}
          <p className="artificer-note">{copy.requiresServer}</p>
        </section>
      ) : null}
    </section>
  )
}

function ArtificerReviewPanel({
  review,
  summary,
}: {
  review: ReviewWithArtificer
  summary: ArtificerSummaryDTO
}) {
  const proposed = review.reconciliation?.proposed_state
  const active = activeStateFromReview(review)
  const armorModel = proposed?.feature_modes?.[ARMOR_MODEL_FEATURE_REF] ?? summary.armor_model
  const references = [
    ARTIFICER_REF,
    ...summary.known_infusions.map((entry) => entry.infusion_ref),
    ...active.map((entry) => entry.infusion_ref),
  ]
  const { nameFor, locale } = useContentPresentations(references)
  const copy = COPY[locale]

  return (
    <section className="artificer-route-panel artificer-review-panel" aria-label={copy.reviewTitle}>
      <div className="artificer-panel-heading">
        <div>
          <p className="eyebrow">{copy.eyebrow}</p>
          <h2>{copy.reviewTitle} · {nameFor(ARTIFICER_REF, 'Artificer')}</h2>
        </div>
        <strong>{copy.level} {summary.artificer_level}</strong>
      </div>
      <ArtificerSummaryCards summary={summary} activeCount={active.length} armorModel={armorModel} />
      <section className="artificer-subsection">
        <h3>{copy.active}</h3>
        <div className="artificer-chip-list">
          {active.map((entry) => (
            <span key={`${entry.inventory_entry_id}:${entry.infusion_ref}`}>{nameFor(entry.infusion_ref, entry.infusion_ref.split(':').at(-1) ?? entry.infusion_ref)}</span>
          ))}
          {!active.length ? <span>{copy.none}</span> : null}
        </div>
      </section>
      <p className="artificer-note">{copy.reviewHint}</p>
    </section>
  )
}

export function CharacterSheetRoutePage({ characterId }: { characterId: string }) {
  const queryClient = useQueryClient()
  const sheetQuery = useQuery({
    queryKey: ['character-sheet', characterId],
    queryFn: () => getCharacterSheet(characterId),
  })
  const mutation = useMutation({
    mutationFn: (patch: Parameters<typeof patchCharacterState>[1]) => patchCharacterState(characterId, patch),
    onSuccess: (next) => queryClient.setQueryData(['character-sheet', characterId], next),
  })

  return (
    <>
      <CharacterSheetPage characterId={characterId} />
      {sheetQuery.data?.artificer ? (
        <ArtificerSheetPanel
          sheet={sheetQuery.data}
          busy={mutation.isPending}
          errorMessage={mutation.error instanceof Error ? mutation.error.message : null}
          onPatch={async (patch) => {
            await mutation.mutateAsync(patch)
          }}
        />
      ) : null}
    </>
  )
}

export function CharacterBuilderRoutePage({ draftId }: { draftId: string }) {
  const draftQuery = useQuery({
    queryKey: ['builder-draft', draftId],
    queryFn: () => getBuilderDraft(draftId),
  })
  const revision = draftQuery.data?.draft.revision
  const reviewQuery = useQuery({
    queryKey: ['builder-review', draftId, revision, 'm01-h-artificer'],
    queryFn: () => getBuilderReview(draftId),
    enabled: revision != null,
  })
  const review = reviewQuery.data as ReviewWithArtificer | undefined
  const summary = review?.derived_stats?.artificer

  return (
    <>
      <CharacterBuilderPage draftId={draftId} />
      {review && summary ? <ArtificerReviewPanel review={review} summary={summary} /> : null}
    </>
  )
}
