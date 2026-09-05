import { useMutation, useQuery } from '@tanstack/react-query'

import {
  confirmBuilderDraft,
  getBuilderReview,
  type BuilderChoice,
  type BuilderDraftPayload,
  type BuilderEquipmentSummary,
  type BuilderReviewDTO,
  type BuilderView,
} from '../../api/characterBuilder'
import type { StateReconciliationPreview } from '../../api/characterVersions'
import { optionDisplay, SearchableSelect } from '../../components/SearchableSelect'
import {
  builderChoiceLabel,
  builderChoiceOptionLabel,
} from '../../i18n/builderChoicePresentation'
import type { Locale } from '../../i18n/locale'
import type { UiCopyKey } from '../../i18n/uiCopy'
import { type ContentNameResolver, useContentPresentations } from '../../i18n/useContentPresentations'
import { useUiCopy, type UiTranslator } from '../../i18n/useUiCopy'
import { choiceAnchorId } from './choiceAnchor'
import {
  grantDisplayName,
  grantPresentationFields,
  grantPresentationReferences,
  isVisibleGrant,
  pairGrantsByKind,
  sortGrantsByKind,
} from './grants'
import { RoleplayProfileEditor } from './RoleplayProfileEditor'

type EquipmentStepProps = {
  view: BuilderView
  disabled: boolean
  onSave: (payload: BuilderDraftPayload) => void
}

type EquipmentReviewStepProps = {
  view: BuilderView
  disabled: boolean
}

type P1GReview = BuilderReviewDTO & {
  reconciliation?: StateReconciliationPreview | null
}

const GRANT_KIND_KEYS: Record<string, UiCopyKey> = {
  language: 'builder.grant.language',
  feature: 'builder.grant.feature',
  background_feature: 'builder.grant.background_feature',
  trait: 'builder.grant.trait',
  proficiency: 'builder.grant.proficiency',
  skill: 'builder.grant.skill',
  spell: 'builder.grant.spell',
  infusion: 'builder.grant.infusion',
}

function selectedIds(raw: unknown): string[] {
  if (typeof raw === 'string') return raw ? [raw] : []
  if (Array.isArray(raw)) return raw.filter((value): value is string => typeof value === 'string')
  if (raw && typeof raw === 'object') {
    const nested = (raw as { selected_option_ids?: unknown }).selected_option_ids
    if (Array.isArray(nested)) {
      return nested.filter((value): value is string => typeof value === 'string')
    }
  }
  return []
}

export function mergeEquipmentByItem(
  entries: readonly BuilderEquipmentSummary[],
): { item_ref: string; name: string; quantity: number }[] {
  const merged = new Map<string, { item_ref: string; name: string; quantity: number }>()
  for (const entry of entries) {
    const existing = merged.get(entry.item_ref)
    if (existing) {
      existing.quantity += entry.quantity
      continue
    }
    merged.set(entry.item_ref, {
      item_ref: entry.item_ref,
      name: entry.name,
      quantity: entry.quantity,
    })
  }
  return [...merged.values()]
}

function EquipmentGrid({
  entries,
  nameFor,
}: {
  entries: readonly BuilderEquipmentSummary[]
  nameFor: ContentNameResolver
}) {
  if (!entries.length) return null
  return (
    <div className="equipment-grid">
      {mergeEquipmentByItem(entries).map((entry) => (
        <div key={entry.item_ref}>
          <strong>{nameFor(entry.item_ref, entry.name)}</strong>
          <span>× {entry.quantity}</span>
        </div>
      ))}
    </div>
  )
}

function optionsFor(
  choice: BuilderChoice,
  nameFor: ContentNameResolver,
  locale: Locale,
) {
  return choice.options.map((option) => ({
    value: option.option_id,
    label: builderChoiceOptionLabel(choice, option, locale, nameFor),
    disabled: Boolean(option.disabled_reason),
    disabledReason: option.disabled_reason ?? undefined,
  }))
}

function modeLabel(mode: BuilderView['draft']['mode'], t: UiTranslator) {
  return t(`review.mode.${mode}`)
}

function signed(value: number) {
  return value >= 0 ? `+${value}` : String(value)
}

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2)
}

function titleCase(value: string) {
  return value
    .replaceAll('-', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function localizedClassSummary(
  review: P1GReview,
  nameFor: ContentNameResolver,
): string {
  return Array.from(
    review.resolved_summary.progression.reduce(
      (classes, node) =>
        classes.set(node.class_ref, {
          name: nameFor(node.class_ref, node.class_name),
          level: node.class_level,
        }),
      new Map<string, { name: string; level: number }>(),
    ).values(),
  )
    .map((entry) => `${entry.name} ${entry.level}`)
    .join(' / ')
}

export function EquipmentStep({
  view,
  disabled,
  onSave,
}: EquipmentStepProps) {
  const { t } = useUiCopy()
  const versioned = view.draft.mode !== 'create'
  const equipmentChoices = view.choices.filter(
    (choice) => choice.option_source === 'equipment',
  )
  const equipmentSelections =
    view.draft.draft_payload.starting_equipment_choices ?? {}
  const resolvedQuery = useQuery({
    queryKey: ['builder-review', view.draft.id, view.draft.revision],
    queryFn: () => getBuilderReview(view.draft.id),
    enabled: !versioned,
  })
  const resolvedEquipment = resolvedQuery.data?.starting_equipment ?? []
  const equipmentReferences = [
    ...equipmentChoices.flatMap((choice) =>
      choice.options.flatMap((option) => [
        ...(option.reference_id ? [option.reference_id] : []),
        ...(option.presentation_items ?? []).map((item) => item.reference_id),
      ]),
    ),
    ...resolvedEquipment.map((entry) => entry.item_ref),
  ]
  const { nameFor, locale } = useContentPresentations(equipmentReferences)

  const saveChoice = (choiceId: string, next: string[]) => {
    onSave({
      starting_equipment_choices: {
        ...equipmentSelections,
        [choiceId]: next,
      },
    })
  }

  return (
    <div className="builder-step">
      <div className="builder-step__heading">
        <p className="eyebrow">{t('equipment.step')}</p>
        <h2>{t('equipment.title')}</h2>
        <p>{t('equipment.description')}</p>
      </div>

      {!versioned ? (
        <div className="builder-choice-list">
          <h3>{t('equipment.starting')}</h3>
          {equipmentChoices.length ? (
            equipmentChoices.map((choice) => {
              const selected = selectedIds(equipmentSelections[choice.choice_id])
              const choiceLabel = builderChoiceLabel(choice, locale, nameFor)
              if (choice.choose_count === 1) {
                return (
                  <div className="builder-choice" key={choice.choice_id} id={choiceAnchorId(choice.choice_id)}>
                    <SearchableSelect
                      label={choiceLabel}
                      value={selected[0] ?? ''}
                      disabled={disabled}
                      options={optionsFor(choice, nameFor, locale)}
                      secondaryMode="duplicates"
                      onChange={(value) =>
                        saveChoice(choice.choice_id, value ? [value] : [])
                      }
                    />
                  </div>
                )
              }

              const selectedLabels = selected.map((id) => {
                const option = choice.options.find((candidate) => candidate.option_id === id)
                return {
                  id,
                  label: option
                    ? optionDisplay(builderChoiceOptionLabel(choice, option, locale, nameFor)).primary
                    : nameFor(id, id),
                }
              })
              return (
                <div className="builder-choice" key={choice.choice_id} id={choiceAnchorId(choice.choice_id)}>
                  <div className="builder-choice__heading">
                    <strong>{choiceLabel}</strong>
                    <span>
                      {selected.length} / {choice.choose_count}
                    </span>
                  </div>
                  <div className="builder-choice__chips">
                    {selectedLabels.map((item, selectedIndex) => (
                      <button
                        type="button"
                        key={`${item.id}:${selectedIndex}`}
                        disabled={disabled}
                        onClick={() =>
                          saveChoice(
                            choice.choice_id,
                            selected.filter((_, index) => index !== selectedIndex),
                          )
                        }
                      >
                        {item.label} ×
                      </button>
                    ))}
                  </div>
                  <SearchableSelect
                    label={t('equipment.add')}
                    value=""
                    disabled={disabled || selected.length >= choice.choose_count}
                    options={optionsFor(choice, nameFor, locale).map((option) => {
                      const alreadySelected =
                        !choice.allow_duplicates && selected.includes(option.value)
                      return {
                        ...option,
                        disabled: option.disabled || alreadySelected,
                        disabledReason: alreadySelected
                          ? t('shared.alreadySelected')
                          : option.disabledReason,
                      }
                    })}
                    secondaryMode="duplicates"
                    onChange={(value) => {
                      if (value && (choice.allow_duplicates || !selected.includes(value))) {
                        saveChoice(choice.choice_id, [...selected, value])
                      }
                    }}
                  />
                </div>
              )
            })
          ) : (
            <p className="builder-muted">{t('equipment.chooseFirst')}</p>
          )}
          <div className="summary-grants">
            <h3>{t('review.resolvedStarting')}</h3>
            <EquipmentGrid entries={resolvedEquipment} nameFor={nameFor} />
            {!resolvedEquipment.length ? (
              <small>{t('review.noStarting')}</small>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="builder-rule-card">
          <span>{t('equipment.starting')}</span>
          <strong>{t('equipment.preserved')}</strong>
          <small>{t('equipment.preservedHint')}</small>
        </div>
      )}

      {!versioned ? (
        <RoleplayProfileEditor
          view={view}
          disabled={disabled}
          onSave={onSave}
        />
      ) : null}
    </div>
  )
}

export function EquipmentReviewStep({
  view,
  disabled,
}: EquipmentReviewStepProps) {
  const { t } = useUiCopy()
  const versioned = view.draft.mode !== 'create'
  const reviewQuery = useQuery({
    queryKey: ['builder-review', view.draft.id, view.draft.revision],
    queryFn: () => getBuilderReview(view.draft.id),
  })
  const confirm = useMutation({
    mutationFn: () => confirmBuilderDraft(view.draft.id),
    onSuccess: (result) => window.location.assign(result.character_path),
  })

  const review = reviewQuery.data as P1GReview | undefined
  const reviewReferences = review
    ? [
        ...(view.draft.draft_payload.race_selection?.reference_id
          ? [view.draft.draft_payload.race_selection.reference_id]
          : []),
        ...(view.draft.draft_payload.subrace_selection?.reference_id
          ? [view.draft.draft_payload.subrace_selection.reference_id]
          : []),
        ...(view.draft.draft_payload.background_selection?.reference_id
          ? [view.draft.draft_payload.background_selection.reference_id]
          : []),
        ...(view.draft.draft_payload.alignment_selection?.reference_id
          ? [view.draft.draft_payload.alignment_selection.reference_id]
          : []),
        ...review.resolved_summary.progression.flatMap((node) => [
          node.class_ref,
          ...(node.subclass_ref ? [node.subclass_ref] : []),
          ...node.automatic_feature_refs,
        ]),
        ...grantPresentationReferences(review.resolved_summary.grants),
        ...review.starting_equipment.map((entry) => entry.item_ref),
        ...Object.keys(review.derived_stats?.skill_modifiers ?? {}).map(
          (skill) => `srd5.1:skill:${skill}`,
        ),
      ]
    : []
  const { nameFor, fieldFor, locale } = useContentPresentations(
    reviewReferences,
    review ? grantPresentationFields(review.resolved_summary.grants) : {},
  )
  const busy = disabled || confirm.isPending
  const blockingCount =
    review?.issues.filter((issue) => issue.severity === 'blocking_error').length ??
    view.validation.issues.filter((issue) => issue.severity === 'blocking_error')
      .length
  const localizedMode = modeLabel(view.draft.mode, t)

  return (
    <div className="builder-step">
      <div className="builder-step__heading">
        <p className="eyebrow">{t('review.step')}</p>
        <h2>
          {versioned
            ? t('review.versionedTitle', { mode: localizedMode })
            : t('review.createTitle')}
        </h2>
        <p>{versioned ? t('review.versionedDescription') : t('review.createDescription')}</p>
      </div>

      {reviewQuery.isLoading ? (
        <div className="builder-rule-card">
          <span>{t('review.serverReview')}</span>
          <strong>{t('review.resolving')}</strong>
          <small>{versioned ? t('review.serverVersionedHint') : t('review.serverCreateHint')}</small>
        </div>
      ) : null}
      {reviewQuery.error ? (
        <div className="error-banner">{reviewQuery.error.message}</div>
      ) : null}
      {confirm.error ? (
        <div className="error-banner">{confirm.error.message}</div>
      ) : null}

      {review ? (
        <>
          <div className="builder-optional">
            <h3>
              {t('review.buildSnapshot')}{' '}
              <span>
                {versioned
                  ? t('review.newVersion', { mode: localizedMode })
                  : t('review.immutableV1')}
              </span>
            </h3>
            <div className="review-identity-grid">
              <div className="builder-rule-card">
                <span>{t('review.identity')}</span>
                <strong>
                  {review.resolved_summary.name?.trim() || t('review.unnamed')} ·{' '}
                  {t('builder.summary.level', {
                    level: review.resolved_summary.target_level ?? '—',
                  })}
                </strong>
                <small>
                  {nameFor(
                    view.draft.draft_payload.race_selection?.reference_id,
                    review.resolved_summary.race_name ?? '—',
                  )} ·{' '}
                  {nameFor(
                    view.draft.draft_payload.background_selection?.reference_id,
                    review.resolved_summary.background_name ?? '—',
                  )} ·{' '}
                  {localizedClassSummary(review, nameFor) || review.resolved_summary.class_summary || '—'}
                </small>
              </div>
              <div className="builder-rule-card proficiency-card">
                <span>{t('review.proficiencyBonus')}</span>
                <strong>
                  {review.derived_stats
                    ? signed(review.derived_stats.proficiency_bonus)
                    : '—'}
                </strong>
                <small>{t('review.currentCharacterLevel')}</small>
              </div>
            </div>

            <div className="summary-abilities">
              {review.resolved_summary.ability_scores.map((score) => {
                const modifier =
                  review.derived_stats?.ability_modifiers[score.ability] ??
                  abilityModifier(score.effective)
                return (
                  <div key={score.ability}>
                    <span>{score.ability.slice(0, 3).toUpperCase()}</span>
                    <strong>
                      {score.effective}({signed(modifier)})
                    </strong>
                    <small>
                      {t('review.base', { value: score.base })}
                      {score.permanent_bonus ? ` + ${score.permanent_bonus}` : ''}
                      {score.overridden ? ` · ${t('review.override')}` : ''}
                    </small>
                  </div>
                )
              })}
            </div>

            <div className="summary-grants summary-grants--paired">
              <h3>{t('review.resolvedGrants')}</h3>
              {pairGrantsByKind(sortGrantsByKind(review.resolved_summary.grants)).map(
                (row, rowIndex) => (
                  <div className="grant-row" key={`${row[0].kind}:${rowIndex}`}>
                    {row.map((grant, index) => (
                      <div key={`${grant.source_ref}:${grant.reference_id ?? grant.label}:${index}`}>
                        <span>
                          {grant.kind === 'feat'
                            ? locale === 'zh-TW' ? '專長' : 'feat'
                            : GRANT_KIND_KEYS[grant.kind]
                              ? t(GRANT_KIND_KEYS[grant.kind])
                              : grant.kind}
                        </span>
                        <strong>
                          {grantDisplayName(
                            grant,
                            optionDisplay(grant.label).primary,
                            nameFor,
                            fieldFor,
                          )}
                        </strong>
                      </div>
                    ))}
                  </div>
                ),
              )}
              {!review.resolved_summary.grants.filter(isVisibleGrant).length ? (
                <small>{t('review.noOriginGrants')}</small>
              ) : null}
            </div>

            <div className="summary-grants">
              <h3>{versioned ? t('review.startingBaseline') : t('review.resolvedStarting')}</h3>
              <EquipmentGrid entries={review.starting_equipment} nameFor={nameFor} />
              {!review.starting_equipment.length ? (
                <small>{t('review.noStarting')}</small>
              ) : null}
            </div>
          </div>

          {versioned ? (
            <div className="builder-optional">
              <h3>
                {t('review.reconciliation')} <span>{t('review.atomicConfirm')}</span>
              </h3>
              {review.reconciliation ? (
                <>
                  <div className="builder-field-grid">
                    <div className="builder-rule-card">
                      <span>{t('review.resultingHp')}</span>
                      <strong>{review.reconciliation.proposed_state.current_hp}</strong>
                      <small>{t('review.damagePreserved')}</small>
                    </div>
                    <div className="builder-rule-card">
                      <span>{t('review.liveInventory')}</span>
                      <strong>{t('review.entries', { count: review.reconciliation.proposed_state.inventory_state.length })}</strong>
                      <small>{t('review.independentBuild')}</small>
                    </div>
                    <div className="builder-rule-card">
                      <span>{t('review.temporaryHp')}</span>
                      <strong>{review.reconciliation.proposed_state.temporary_hp}</strong>
                      <small>{t('review.preserved')}</small>
                    </div>
                    <div className="builder-rule-card">
                      <span>{t('review.conditions')}</span>
                      <strong>{review.reconciliation.proposed_state.conditions.length}</strong>
                      <small>{t('review.preserved')}</small>
                    </div>
                  </div>
                  <div className="reconciliation-list">
                    {review.reconciliation.changes.map((change) => (
                      <div className="builder-rule-card" key={`${change.path}:${change.kind}`}>
                        <span>{change.path}</span>
                        <strong>{change.before} → {change.after}</strong>
                        <small>{change.message}</small>
                      </div>
                    ))}
                    {!review.reconciliation.changes.length ? (
                      <p className="builder-muted">{t('review.noCapacityChanges')}</p>
                    ) : null}
                  </div>
                </>
              ) : (
                <p className="builder-muted">{t('review.reconciliationUnavailable')}</p>
              )}
            </div>
          ) : (
            <div className="builder-optional">
              <h3>
                {t('review.initialState')} <span>{t('review.createdOnce')}</span>
              </h3>
              {review.initial_state ? (
                <div className="builder-field-grid">
                  <div className="builder-rule-card">
                    <span>{t('review.currentHp')}</span>
                    <strong>{review.initial_state.current_hp}</strong>
                    <small>{t('review.tempHpValue', { value: review.initial_state.temporary_hp })}</small>
                  </div>
                  <div className="builder-rule-card">
                    <span>{t('review.inventory')}</span>
                    <strong>{t('review.entries', { count: review.initial_state.inventory_state.length })}</strong>
                    <small>{t('review.independentAfterConfirm')}</small>
                  </div>
                  <div className="builder-rule-card">
                    <span>{t('review.hitDice')}</span>
                    <strong>
                      {Object.entries(review.initial_state.hit_dice_state)
                        .map(([die, count]) => `${die} × ${count}`)
                        .join(' · ') || '—'}
                    </strong>
                    <small>{t('review.startsAvailable')}</small>
                  </div>
                  <div className="builder-rule-card">
                    <span>{t('review.preparedSpells')}</span>
                    <strong>{review.initial_state.prepared_spells.length}</strong>
                    <small>{t('review.initialPreparedOnly')}</small>
                  </div>
                </div>
              ) : (
                <p className="builder-muted">{t('review.initialUnavailable')}</p>
              )}
            </div>
          )}

          {review.derived_stats ? (
            <div className="builder-optional review-skills">
              <h3>
                {t('review.skillChecks')} <span>{t('review.currentBuild')}</span>
              </h3>
              <div className="skill-modifier-grid">
                {Object.entries(review.derived_stats.skill_modifiers).map(
                  ([skill, modifier]) => (
                    <div key={skill}>
                      <span>{nameFor(`srd5.1:skill:${skill}`, titleCase(skill))}</span>
                      <strong>{signed(modifier)}</strong>
                    </div>
                  ),
                )}
              </div>
            </div>
          ) : null}

          <div className="summary-validation">
            <div className="summary-validation__heading">
              <h3>{t('review.finalValidation')}</h3>
              <span className={blockingCount ? 'has-errors' : 'is-clear'}>
                {t('review.blocking', { count: blockingCount })}
              </span>
            </div>
            <ul>
              {review.issues.map((issue, index) => (
                <li
                  className={`issue-${issue.severity}`}
                  key={`${issue.code}:${issue.path}:${index}`}
                >
                  <strong>{issue.code.replaceAll('_', ' ')}</strong>
                  <span>{issue.message}</span>
                </li>
              ))}
            </ul>
            {!review.issues.length ? (
              <p className="builder-hint">
                {versioned ? t('review.clearVersioned') : t('review.clearCreate')}
              </p>
            ) : null}
          </div>

          <button
            type="button"
            className="button primary full"
            disabled={busy || !review.can_confirm}
            onClick={() => confirm.mutate()}
          >
            {confirm.isPending
              ? versioned ? t('review.creatingVersion') : t('review.creatingCharacter')
              : versioned ? t('review.confirmMode', { mode: localizedMode }) : t('review.confirmCreate')}
          </button>
        </>
      ) : null}
    </div>
  )
}
