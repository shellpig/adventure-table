import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  cancelBuilderDraft,
  getAbilityGenerationRules,
  getBuilderDraft,
  patchBuilderDraft,
  type AbilityGenerationMethod,
  type BuilderAbilityScores,
  type BuilderChoice,
  type BuilderDraftPayload,
  type BuilderView,
} from '../../api/characterBuilder'
import { optionDisplay, SearchableSelect } from '../../components/SearchableSelect'
import {
  builderChoiceLabel,
  builderChoiceOptionLabel,
} from '../../i18n/builderChoicePresentation'
import type { Locale } from '../../i18n/locale'
import type { UiCopyKey } from '../../i18n/uiCopy'
import { type ContentNameResolver, useContentPresentations } from '../../i18n/useContentPresentations'
import { useUiCopy } from '../../i18n/useUiCopy'
import { assignStandardArrayScore } from './abilityAssignment'
import { formatSignedBonus } from './abilityPresentation'
import { choiceAnchorId, issueChoiceId } from './choiceAnchor'
import { ClassProgressionStep } from './ClassProgressionStep'
import { EquipmentReviewStep, EquipmentStep } from './EquipmentReviewStep'
import {
  grantDisplayName,
  grantPresentationFields,
  grantPresentationReferences,
  isVisibleGrant,
  sortGrantsByKind,
} from './grants'
import { SpellcastingStep } from './SpellcastingStep'
import './builder.css'

type BuilderStep = 'basic' | 'origin' | 'abilities' | 'class' | 'spells' | 'equipment' | 'review'

type ChoiceEditorProps = {
  choice: BuilderChoice
  view: BuilderView
  disabled: boolean
  onSave: (payload: BuilderDraftPayload) => void
  nameFor: ContentNameResolver
  locale: Locale
}

const DIRECT_OPTION_SOURCES = new Set([
  'content:race',
  'content:race-variant',
  'content:lineage',
  'content:background',
  'content:alignment',
  'content:subrace',
  'content:subclass',
  'builder:ability-generation',
  'content:class',
])

const VARIANT_BRANCH_OPTION_SOURCES = new Set([
  'content:race-variant-replacement',
  'content:race-variant-spell',
])

const ORIGIN_ABILITY_OPTION_SOURCES = new Set([
  'content:ability_bonus_options',
  'content:lineage-asi-pattern',
  'content:lineage-asi-ability',
  'content:lineage-size',
])

function stepForChoice(choice: BuilderChoice): BuilderStep {
  if (choice.choice_id.startsWith('level:')) return 'class'
  const source = choice.option_source ?? ''
  if (source === 'equipment') return 'equipment'
  if (
    DIRECT_OPTION_SOURCES.has(source) ||
    VARIANT_BRANCH_OPTION_SOURCES.has(source) ||
    ORIGIN_ABILITY_OPTION_SOURCES.has(source)
  ) {
    return 'origin'
  }
  return 'abilities'
}

const ABILITY_COPY_KEYS: Record<keyof BuilderAbilityScores, UiCopyKey> = {
  strength: 'builder.abilities.strength',
  dexterity: 'builder.abilities.dexterity',
  constitution: 'builder.abilities.constitution',
  intelligence: 'builder.abilities.intelligence',
  wisdom: 'builder.abilities.wisdom',
  charisma: 'builder.abilities.charisma',
}

const ABILITY_METHOD_KEYS: Record<AbilityGenerationMethod, UiCopyKey> = {
  standard_array: 'builder.abilities.standardArray',
  point_buy: 'builder.abilities.pointBuy',
  manual: 'builder.abilities.manual',
}

const GRANT_KIND_KEYS: Record<string, UiCopyKey> = {
  language: 'builder.grant.language',
  feature: 'builder.grant.feature',
  background_feature: 'builder.grant.background_feature',
  trait: 'builder.grant.trait',
  proficiency: 'builder.grant.proficiency',
}

const ABILITY_KEYS = Object.keys(ABILITY_COPY_KEYS) as (keyof BuilderAbilityScores)[]
const EMPTY_SCORES: BuilderAbilityScores = {
  strength: 0,
  dexterity: 0,
  constitution: 0,
  intelligence: 0,
  wisdom: 0,
  charisma: 0,
}

function selectionOptions(
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

function localizedClassSummary(view: BuilderView, nameFor: ContentNameResolver): string {
  return Array.from(
    view.resolved_summary.progression.reduce(
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

function ChoiceEditor({ choice, view, disabled, onSave, nameFor, locale }: ChoiceEditorProps) {
  const { t } = useUiCopy()
  const label = builderChoiceLabel(choice, locale, nameFor)

  if (choice.disabled_reason) {
    return (
      <div className="builder-choice is-disabled" id={choiceAnchorId(choice.choice_id)}>
        <div>
          <strong>{label}</strong>
          <small>{choice.disabled_reason}</small>
        </div>
        <span className="builder-lock">{t('shared.locked')}</span>
      </div>
    )
  }

  const selected =
    view.draft.draft_payload.choice_selections?.[choice.choice_id]?.selected_option_ids ?? []
  const saveSelected = (next: string[]) => {
    onSave({
      choice_selections: {
        ...(view.draft.draft_payload.choice_selections ?? {}),
        [choice.choice_id]: {
          choice_id: choice.choice_id,
          source_ref: choice.source_ref,
          selected_option_ids: next,
        },
      },
    })
  }

  if (choice.choose_count === 1) {
    return (
      <div className="builder-choice" id={choiceAnchorId(choice.choice_id)}>
        <SearchableSelect
          label={label}
          value={selected[0] ?? ''}
          disabled={disabled}
          options={selectionOptions(choice, nameFor, locale)}
          secondaryMode="duplicates"
          onChange={(value) => saveSelected(value ? [value] : [])}
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
  const canAdd = selected.length < choice.choose_count
  return (
    <div className="builder-choice" id={choiceAnchorId(choice.choice_id)}>
      <div className="builder-choice__heading">
        <strong>{label}</strong>
        <span>{selected.length} / {choice.choose_count}</span>
      </div>
      <div className="builder-choice__chips">
        {selectedLabels.map((item) => (
          <button
            type="button"
            key={item.id}
            disabled={disabled}
            onClick={() => saveSelected(selected.filter((id) => id !== item.id))}
          >
            {item.label} ×
          </button>
        ))}
      </div>
      <SearchableSelect
        label={t('shared.addSelection')}
        value=""
        disabled={disabled || !canAdd}
        options={selectionOptions(choice, nameFor, locale).map((option) => ({
          ...option,
          disabled: option.disabled || selected.includes(option.value),
          disabledReason: selected.includes(option.value) ? t('shared.alreadySelected') : option.disabledReason,
        }))}
        secondaryMode="duplicates"
        onChange={(value) => {
          if (value && !selected.includes(value)) saveSelected([...selected, value])
        }}
      />
    </div>
  )
}

export function CharacterBuilderPage({ draftId }: { draftId: string }) {
  const { t } = useUiCopy()
  const queryClient = useQueryClient()
  const [step, setStep] = useState<BuilderStep>('basic')
  const [pendingChoiceId, setPendingChoiceId] = useState<string | null>(null)
  const draftQuery = useQuery({
    queryKey: ['builder-draft', draftId],
    queryFn: () => getBuilderDraft(draftId),
  })
  const rulesQuery = useQuery({
    queryKey: ['builder-rules', 'ability-generation'],
    queryFn: getAbilityGenerationRules,
  })
  const view = draftQuery.data
  const contentReferences = useMemo(
    () => [
      ...(view?.choices.flatMap((choice) => [
        ...(choice.source_ref ? [choice.source_ref] : []),
        ...choice.options.flatMap((option) => [
          ...(option.reference_id ? [option.reference_id] : []),
          ...(option.presentation_items ?? []).map((item) => item.reference_id),
        ]),
      ]) ?? []),
      ...(view?.resolved_summary.progression.flatMap((node) => [
        node.class_ref,
        ...(node.subclass_ref ? [node.subclass_ref] : []),
        ...node.automatic_feature_refs,
      ]) ?? []),
      ...grantPresentationReferences(view?.resolved_summary.grants ?? []),
      ...(view?.draft.draft_payload.race_selection?.reference_id
        ? [view.draft.draft_payload.race_selection.reference_id]
        : []),
      ...(view?.draft.draft_payload.race_variant_selection?.reference_id
        ? [view.draft.draft_payload.race_variant_selection.reference_id]
        : []),
      ...(view?.draft.draft_payload.subrace_selection?.reference_id
        ? [view.draft.draft_payload.subrace_selection.reference_id]
        : []),
      ...(view?.draft.draft_payload.lineage_selection?.reference_id
        ? [view.draft.draft_payload.lineage_selection.reference_id]
        : []),
      ...(view?.draft.draft_payload.background_selection?.reference_id
        ? [view.draft.draft_payload.background_selection.reference_id]
        : []),
      ...(view?.draft.draft_payload.alignment_selection?.reference_id
        ? [view.draft.draft_payload.alignment_selection.reference_id]
        : []),
    ],
    [view],
  )
  const { nameFor, fieldFor, locale } = useContentPresentations(
    contentReferences,
    grantPresentationFields(view?.resolved_summary.grants ?? []),
  )

  const save = useMutation({
    mutationFn: (payload: BuilderDraftPayload) => {
      if (!view) throw new Error(t('builder.notFound'))
      return patchBuilderDraft(draftId, view.draft.revision, payload)
    },
    onSuccess: (next) => {
      queryClient.setQueryData(['builder-draft', draftId], next)
      queryClient.invalidateQueries({ queryKey: ['builder-drafts', 'create'] })
    },
  })
  const cancel = useMutation({
    mutationFn: () => cancelBuilderDraft(draftId),
    onSuccess: () => window.location.assign('/characters'),
  })

  const [name, setName] = useState('')
  const [targetLevel, setTargetLevel] = useState(1)
  const [appearance, setAppearance] = useState('')
  const [biography, setBiography] = useState('')
  const [abilityMethod, setAbilityMethod] = useState<AbilityGenerationMethod>('standard_array')
  const [abilityScores, setAbilityScores] = useState<BuilderAbilityScores>(EMPTY_SCORES)

  useEffect(() => {
    if (!view) return
    setName(view.draft.draft_payload.basic?.name ?? '')
    setTargetLevel(view.draft.draft_payload.target_level ?? 1)
    setAppearance(String(view.draft.draft_payload.roleplay_profile?.appearance ?? ''))
    setBiography(String(view.draft.draft_payload.roleplay_profile?.biography ?? ''))
    const generation = view.draft.draft_payload.ability_generation
    if (generation) {
      setAbilityMethod(generation.method)
      setAbilityScores(generation.scores)
    }
  }, [view])

  useEffect(() => {
    if (view?.draft.draft_payload.ability_generation || !rulesQuery.data) return
    const values = rulesQuery.data.standard_array
    if (values.length !== ABILITY_KEYS.length) return
    setAbilityScores(
      ABILITY_KEYS.reduce(
        (result, ability, index) => ({ ...result, [ability]: values[index] }),
        EMPTY_SCORES,
      ),
    )
  }, [rulesQuery.data, view])

  const choicesBySource = useMemo(
    () => new Map(view?.choices.map((choice) => [choice.option_source, choice]) ?? []),
    [view],
  )
  const choicesById = useMemo(
    () => new Map(view?.choices.map((choice) => [choice.choice_id, choice]) ?? []),
    [view],
  )

  useEffect(() => {
    if (!pendingChoiceId) return
    setPendingChoiceId(null)
    const anchor = document.getElementById(choiceAnchorId(pendingChoiceId))
    if (!anchor) return
    anchor.scrollIntoView({ block: 'center' })
    anchor
      .querySelector<HTMLElement>('input:not([disabled]), select:not([disabled]), button:not([disabled])')
      ?.focus({ preventScroll: true })
  }, [pendingChoiceId, step])
  const variantBranchChoices = useMemo(
    () =>
      view?.choices.filter((choice) =>
        VARIANT_BRANCH_OPTION_SOURCES.has(choice.option_source ?? ''),
      ) ?? [],
    [view],
  )
  const originAbilityChoices = useMemo(
    () =>
      view?.choices.filter((choice) =>
        ORIGIN_ABILITY_OPTION_SOURCES.has(choice.option_source ?? ''),
      ) ?? [],
    [view],
  )
  const startingChoices = useMemo(
    () =>
      view?.choices.filter(
        (choice) =>
          !DIRECT_OPTION_SOURCES.has(choice.option_source ?? '') &&
          !VARIANT_BRANCH_OPTION_SOURCES.has(choice.option_source ?? '') &&
          !ORIGIN_ABILITY_OPTION_SOURCES.has(choice.option_source ?? '') &&
          choice.option_source !== 'equipment' &&
          !choice.choice_id.startsWith('level:'),
      ) ?? [],
    [view],
  )

  if (draftQuery.isLoading) {
    return <main className="builder-loading">{t('builder.loading')}</main>
  }
  if (draftQuery.error || !view) {
    return (
      <main className="builder-loading">
        <div className="error-banner">{draftQuery.error?.message ?? t('builder.notFound')}</div>
        <a className="button secondary" href="/characters">{t('builder.backWorkshop')}</a>
      </main>
    )
  }

  const saving = save.isPending || cancel.isPending
  const raceChoice = choicesBySource.get('content:race')
  const raceVariantChoice = choicesBySource.get('content:race-variant')
  const lineageChoice = choicesBySource.get('content:lineage')
  const subraceChoice = choicesBySource.get('content:subrace')
  const backgroundChoice = choicesBySource.get('content:background')
  const alignmentChoice = choicesBySource.get('content:alignment')
  const currentRace = view.draft.draft_payload.race_selection?.reference_id ?? ''
  const currentRaceVariant = view.draft.draft_payload.race_variant_selection?.reference_id ?? ''
  const currentLineage =
    view.draft.draft_payload.lineage_selection?.reference_id ??
    lineageChoice?.selected_option_ids[0] ??
    ''
  const currentSubrace = view.draft.draft_payload.subrace_selection?.reference_id ?? ''
  const currentBackground = view.draft.draft_payload.background_selection?.reference_id ?? ''
  const currentAlignment = view.draft.draft_payload.alignment_selection?.reference_id ?? ''

  const patchReference = (
    field:
      | 'race_selection'
      | 'race_variant_selection'
      | 'subrace_selection'
      | 'lineage_selection'
      | 'background_selection'
      | 'alignment_selection',
    value: string,
    resetChoices = false,
  ) => {
    const payload: BuilderDraftPayload = { [field]: value ? { reference_id: value } : null }
    if (field === 'race_selection') {
      payload.race_variant_selection = null
      payload.subrace_selection = null
    }
    if (field === 'lineage_selection' && lineageChoice) {
      payload.choice_selections = {
        ...(view.draft.draft_payload.choice_selections ?? {}),
        [lineageChoice.choice_id]: {
          choice_id: lineageChoice.choice_id,
          source_ref: lineageChoice.source_ref,
          selected_option_ids: value ? [value] : [],
        },
      }
    }
    if (resetChoices) {
      payload.choice_selections = {}
      payload.starting_equipment_choices = {}
    }
    save.mutate(payload)
  }

  const issueCount = view.validation.issues.filter((issue) => issue.severity === 'blocking_error').length
  const abilityRules = rulesQuery.data
  const standardValues = abilityRules?.standard_array ?? []
  const pointBuySpent = abilityRules
    ? ABILITY_KEYS.reduce((total, ability) => {
        const cost = abilityRules.point_buy_costs[String(abilityScores[ability])]
        return cost === undefined ? Number.NaN : total + cost
      }, 0)
    : Number.NaN
  const abilityInputValid = abilityRules
    ? ABILITY_KEYS.every(
        (ability) =>
          Number.isInteger(abilityScores[ability]) &&
          abilityScores[ability] >= abilityRules.hard_min &&
          abilityScores[ability] <= abilityRules.hard_max,
      )
    : false

  const saveBasicDetails = () => {
    const previousTarget = view.draft.draft_payload.target_level ?? 1
    const payload: BuilderDraftPayload = {
      basic: { name, ruleset: 'dnd5e-2014' },
      target_level: targetLevel,
      level_choices: (view.draft.draft_payload.level_choices ?? []).slice(0, targetLevel),
      roleplay_profile: { appearance, biography },
    }
    if (previousTarget !== targetLevel) {
      payload.spell_choices = {}
      payload.starting_equipment_choices = {}
    }
    save.mutate(payload)
  }

  return (
    <main className="builder-page">
      <div className="builder-shell">
        <header className="builder-topbar">
          <div className="builder-topbar__main">
            <a href="/characters" className="builder-back">{t('builder.backWorkshopArrow')}</a>
            <span className="builder-topbar__divider" aria-hidden="true" />
            <h1 className="builder-topbar__title">{view.resolved_summary.name?.trim() || t('builder.unnamedCharacter')}</h1>
            <span className="builder-topbar__badge">{t('builder.eyebrow')}</span>
          </div>
          <div className="builder-save-state">
            <span>{t('builder.draftRevision', { revision: view.draft.revision })}</span>
            <strong>{saving ? t('shared.saving') : t('builder.saved')}</strong>
          </div>
        </header>

        {save.error ? <div className="error-banner">{save.error.message}</div> : null}

        <div className="builder-layout">
          <aside className="builder-rail" aria-label={t('builder.stepsAria')}>
            <button className={step === 'basic' ? 'is-active' : ''} onClick={() => setStep('basic')}>
              <span>01</span><div><strong>{t('builder.step.basic')}</strong><small>{t('builder.step.basicHint')}</small></div>
            </button>
            <button className={step === 'origin' ? 'is-active' : ''} onClick={() => setStep('origin')}>
              <span>02</span><div><strong>{t('builder.step.origin')}</strong><small>{t('builder.step.originHint')}</small></div>
            </button>
            <button className={step === 'abilities' ? 'is-active' : ''} onClick={() => setStep('abilities')}>
              <span>03</span><div><strong>{t('builder.step.abilities')}</strong><small>{t('builder.step.abilitiesHint')}</small></div>
            </button>
            <button className={step === 'class' ? 'is-active' : ''} onClick={() => setStep('class')}>
              <span>04</span><div><strong>{t('builder.step.class')}</strong><small>{t('builder.step.classHint')}</small></div>
            </button>
            <button className={step === 'spells' ? 'is-active' : ''} onClick={() => setStep('spells')}>
              <span>05</span><div><strong>{t('builder.step.spells')}</strong><small>{t('builder.step.spellsHint')}</small></div>
            </button>
            <button className={step === 'equipment' ? 'is-active' : ''} onClick={() => setStep('equipment')}>
              <span>06</span><div><strong>{t('builder.step.equipment')}</strong><small>{t('builder.step.equipmentHint')}</small></div>
            </button>
            <button className={step === 'review' ? 'is-active' : ''} onClick={() => setStep('review')}>
              <span>07</span><div><strong>{t('builder.step.review')}</strong><small>{t('builder.step.reviewHint')}</small></div>
            </button>
          </aside>

          <section className="builder-form">
            {step === 'basic' ? (
              <div className="builder-step">
                <div className="builder-step__heading">
                  <p className="eyebrow">{t('builder.basic.step')}</p>
                  <h2>{t('builder.basic.title')}</h2>
                  <p>{t('builder.basic.description')}</p>
                </div>
                <div className="builder-field-grid">
                  <label className="builder-field">
                    <span>{t('builder.basic.name')}</span>
                    <input value={name} onChange={(event) => setName(event.target.value)} maxLength={200} />
                  </label>
                  <label className="builder-field">
                    <span>{t('builder.basic.targetLevel')}</span>
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={targetLevel}
                      onChange={(event) => setTargetLevel(Number(event.target.value))}
                    />
                  </label>
                </div>
                <div className="builder-rule-card">
                  <span>{t('builder.basic.ruleset')}</span><strong>D&amp;D 5e · 2014</strong><small>{t('builder.basic.builtIn')}</small>
                </div>
                <div className="builder-optional">
                  <h3>{t('builder.basic.roleplayNotes')} <span>{t('shared.optional')}</span></h3>
                  <label className="builder-field"><span>{t('builder.basic.appearance')}</span><textarea value={appearance} onChange={(event) => setAppearance(event.target.value)} /></label>
                  <label className="builder-field"><span>{t('builder.basic.biography')}</span><textarea value={biography} onChange={(event) => setBiography(event.target.value)} /></label>
                </div>
                <button
                  type="button"
                  className="button primary"
                  disabled={saving || targetLevel < 1 || targetLevel > 20}
                  onClick={saveBasicDetails}
                >
                  {t('builder.basic.save')}
                </button>
              </div>
            ) : null}

            {step === 'origin' ? (
              <div className="builder-step">
                <div className="builder-step__heading">
                  <p className="eyebrow">{t('builder.origin.step')}</p>
                  <h2>{t('builder.origin.title')}</h2>
                  <p>{t('builder.origin.description')}</p>
                </div>
                {raceChoice ? (
                  <SearchableSelect label={t('builder.origin.race')} value={currentRace} disabled={saving} options={selectionOptions(raceChoice, nameFor, locale)} secondaryMode="duplicates" onChange={(value) => patchReference('race_selection', value, true)} />
                ) : null}
                {lineageChoice ? (
                  <SearchableSelect
                    label={builderChoiceLabel(lineageChoice, locale, nameFor)}
                    value={currentLineage}
                    disabled={saving}
                    options={selectionOptions(lineageChoice, nameFor, locale)}
                    secondaryMode="duplicates"
                    onChange={(value) => patchReference('lineage_selection', value)}
                  />
                ) : null}
                {raceVariantChoice ? (
                  <SearchableSelect
                    label={builderChoiceLabel(raceVariantChoice, locale, nameFor)}
                    value={currentRaceVariant}
                    disabled={saving}
                    options={selectionOptions(raceVariantChoice, nameFor, locale)}
                    secondaryMode="duplicates"
                    onChange={(value) => patchReference('race_variant_selection', value)}
                  />
                ) : null}
                {variantBranchChoices.length ? (
                  <div className="builder-choice-list">
                    {variantBranchChoices.map((choice) => (
                      <ChoiceEditor
                        key={choice.choice_id}
                        choice={choice}
                        view={view}
                        disabled={saving}
                        onSave={(payload) => save.mutate(payload)}
                        nameFor={nameFor}
                        locale={locale}
                      />
                    ))}
                  </div>
                ) : null}
                {subraceChoice ? (
                  <SearchableSelect label={t('builder.origin.subrace')} value={currentSubrace} disabled={saving} options={selectionOptions(subraceChoice, nameFor, locale)} secondaryMode="duplicates" onChange={(value) => patchReference('subrace_selection', value, true)} />
                ) : null}
                {originAbilityChoices.length ? (
                  <div className="builder-choice-list">
                    {originAbilityChoices.map((choice) => (
                      <ChoiceEditor
                        key={choice.choice_id}
                        choice={choice}
                        view={view}
                        disabled={saving}
                        onSave={(payload) => save.mutate(payload)}
                        nameFor={nameFor}
                        locale={locale}
                      />
                    ))}
                  </div>
                ) : null}
                {backgroundChoice ? (
                  <SearchableSelect label={t('builder.origin.background')} value={currentBackground} disabled={saving} options={selectionOptions(backgroundChoice, nameFor, locale)} secondaryMode="duplicates" onChange={(value) => patchReference('background_selection', value, true)} />
                ) : null}
                {alignmentChoice ? (
                  <SearchableSelect label={t('builder.origin.alignment')} value={currentAlignment} disabled={saving} options={selectionOptions(alignmentChoice, nameFor, locale)} secondaryMode="duplicates" onChange={(value) => patchReference('alignment_selection', value)} />
                ) : null}
                <div className="builder-grant-preview">
                  <span>{t('builder.origin.resolvedGrants')}</span><strong>{view.resolved_summary.grants.filter(isVisibleGrant).length}</strong><small>{t('builder.origin.grantsHint')}</small>
                </div>
              </div>
            ) : null}

            {step === 'abilities' ? (
              <div className="builder-step">
                <div className="builder-step__heading">
                  <p className="eyebrow">{t('builder.abilities.step')}</p>
                  <h2>{t('builder.abilities.title')}</h2>
                  <p>{t('builder.abilities.description')}</p>
                </div>
                <div className="ability-methods" role="tablist" aria-label={t('builder.abilities.methodAria')}>
                  {(['standard_array', 'point_buy', 'manual'] as AbilityGenerationMethod[]).map((method) => (
                    <button
                      type="button"
                      role="tab"
                      aria-selected={abilityMethod === method}
                      className={abilityMethod === method ? 'is-active' : ''}
                      key={method}
                      onClick={() => {
                        setAbilityMethod(method)
                        if (method === 'standard_array' && standardValues.length === ABILITY_KEYS.length) {
                          setAbilityScores(
                            ABILITY_KEYS.reduce(
                              (result, ability, index) => ({ ...result, [ability]: standardValues[index] }),
                              EMPTY_SCORES,
                            ),
                          )
                        }
                      }}
                    >
                      {t(ABILITY_METHOD_KEYS[method])}
                    </button>
                  ))}
                </div>
                {rulesQuery.error ? <div className="error-banner">{rulesQuery.error.message}</div> : null}
                <div className="builder-abilities">
                  {ABILITY_KEYS.map((ability) => {
                    return abilityMethod === 'standard_array' ? (
                      <SearchableSelect
                        key={ability}
                        label={t(ABILITY_COPY_KEYS[ability])}
                        value={abilityScores[ability] ? String(abilityScores[ability]) : ''}
                        disabled={saving || !abilityRules}
                        options={standardValues.map((score) => ({
                          value: String(score),
                          label: String(score),
                        }))}
                        onChange={(value) =>
                          setAbilityScores((current) => assignStandardArrayScore(current, ability, Number(value)))
                        }
                      />
                    ) : (
                      <label className="builder-field ability-input" key={ability}>
                        <span>{t(ABILITY_COPY_KEYS[ability])}</span>
                        <input
                          type="number"
                          min={abilityRules?.hard_min}
                          max={abilityRules?.hard_max}
                          value={abilityScores[ability] || ''}
                          onChange={(event) =>
                            setAbilityScores((current) => ({ ...current, [ability]: Number(event.target.value) }))
                          }
                        />
                      </label>
                    )
                  })}
                </div>
                <p className="builder-hint">
                  {abilityMethod === 'point_buy' && abilityRules
                    ? Number.isNaN(pointBuySpent)
                      ? t('builder.abilities.pointBuyInvalid', { budget: abilityRules.point_buy_budget })
                      : t('builder.abilities.pointBuyUsed', { spent: pointBuySpent, budget: abilityRules.point_buy_budget })
                    : abilityMethod === 'manual' && abilityRules
                      ? t('builder.abilities.manualHint', { min: abilityRules.manual_standard_min, max: abilityRules.manual_standard_max })
                      : t('builder.abilities.standardHint')}
                </p>
                <button
                  type="button"
                  className="button primary"
                  disabled={saving || !abilityInputValid}
                  onClick={() =>
                    save.mutate({
                      ability_generation: {
                        method: abilityMethod,
                        scores: abilityScores,
                        provenance: abilityMethod === 'manual' ? 'manual_input' : 'builder_ui',
                      },
                    })
                  }
                >
                  {t('builder.abilities.save')}
                </button>

                <div className="builder-choice-list builder-choice-list--columns">
                  <h3>{t('builder.abilities.startingChoices')}</h3>
                  {startingChoices.length ? (
                    startingChoices.map((choice) => (
                      <ChoiceEditor
                        key={choice.choice_id}
                        choice={choice}
                        view={view}
                        disabled={saving}
                        onSave={(payload) => save.mutate(payload)}
                        nameFor={nameFor}
                        locale={locale}
                      />
                    ))
                  ) : (
                    <p className="builder-muted">{t('builder.abilities.chooseOriginFirst')}</p>
                  )}
                </div>
              </div>
            ) : null}

            {step === 'class' ? (
              <ClassProgressionStep
                view={view}
                disabled={saving}
                onSave={(payload) => save.mutate(payload)}
              />
            ) : null}

            {step === 'spells' ? (
              <SpellcastingStep
                view={view}
                disabled={saving}
                onSave={(payload) => save.mutate(payload)}
              />
            ) : null}

            {step === 'equipment' ? (
              <EquipmentStep
                view={view}
                disabled={saving}
                onSave={(payload) => save.mutate(payload)}
              />
            ) : null}

            {step === 'review' ? (
              <EquipmentReviewStep
                view={view}
                disabled={saving}
              />
            ) : null}
          </section>

          <aside className="builder-summary">
            <div className="builder-summary__top">
              <div><span>{t('builder.summary.label')}</span><h2>{view.resolved_summary.name?.trim() || t('review.unnamed')}</h2></div>
              <strong>{t('builder.summary.level', { level: view.resolved_summary.target_level ?? '—' })}</strong>
            </div>
            <dl className="builder-summary__facts">
              {currentLineage && lineageChoice ? (
                <div>
                  <dt>{builderChoiceLabel(lineageChoice, locale, nameFor)}</dt>
                  <dd>{nameFor(currentLineage, view.resolved_summary.lineage_name ?? currentLineage)}</dd>
                </div>
              ) : (
                <div>
                  <dt>{t('builder.summary.race')}</dt>
                  <dd>
                    {nameFor(currentRace, view.resolved_summary.race_name ?? '—')}
                    {currentRaceVariant
                      ? ` · ${nameFor(currentRaceVariant, view.resolved_summary.race_variant_name ?? currentRaceVariant)}`
                      : ''}
                    {currentSubrace
                      ? ` · ${nameFor(currentSubrace, view.resolved_summary.subrace_name ?? currentSubrace)}`
                      : ''}
                  </dd>
                </div>
              )}
              <div>
                <dt>{t('builder.summary.background')}</dt>
                <dd>{nameFor(currentBackground, view.resolved_summary.background_name ?? '—')}</dd>
              </div>
              <div>
                <dt>{t('builder.summary.class')}</dt>
                <dd>{localizedClassSummary(view, nameFor) || view.resolved_summary.class_summary || '—'}</dd>
              </div>
              <div>
                <dt>{t('builder.summary.alignment')}</dt>
                <dd>{nameFor(currentAlignment, view.resolved_summary.alignment_name ?? t('builder.summary.optional'))}</dd>
              </div>
            </dl>

            {view.resolved_summary.ability_scores.length ? (
              <div className="summary-abilities">
                {view.resolved_summary.ability_scores.map((score) => (
                  <div key={score.ability}>
                    <span>{score.ability.slice(0, 3).toUpperCase()}</span>
                    <strong>{score.effective}</strong>
                    <small>{score.base} {formatSignedBonus(score.permanent_bonus)}{score.overridden ? ` · ${t('builder.summary.override')}` : ''}</small>
                  </div>
                ))}
              </div>
            ) : null}

            <div className="summary-grants">
              <h3>{t('builder.summary.resolvedGrants')}</h3>
              {sortGrantsByKind(view.resolved_summary.grants).map((grant, index) => {
                const kindKey = GRANT_KIND_KEYS[grant.kind]
                return (
                  <div key={`${grant.source_ref}:${grant.reference_id ?? grant.label}:${index}`}>
                    <span>{kindKey ? t(kindKey) : grant.kind.replaceAll('_', ' ')}</span>
                    <strong>
                      {grantDisplayName(
                        grant,
                        optionDisplay(grant.label).primary,
                        nameFor,
                        fieldFor,
                      )}
                    </strong>
                  </div>
                )
              })}
            </div>

            <div className="summary-validation">
              <div className="summary-validation__heading">
                <h3>{t('builder.summary.validation')}</h3>
                <span className={issueCount ? 'has-errors' : 'is-clear'}>{t('builder.summary.blocking', { count: issueCount })}</span>
              </div>
              <ul>
                {view.validation.issues.map((issue, index) => {
                  const targetChoiceId = issueChoiceId(issue.path)
                  const target = targetChoiceId ? choicesById.get(targetChoiceId) : undefined
                  const body = (
                    <><strong>{issue.code.replaceAll('_', ' ')}</strong><span>{issue.message}</span></>
                  )
                  return (
                    <li className={`issue-${issue.severity}`} key={`${issue.code}:${issue.path}:${index}`}>
                      {target ? (
                        <button
                          type="button"
                          className="summary-validation__jump"
                          title={t('builder.summary.jumpToChoice')}
                          onClick={() => {
                            setStep(stepForChoice(target))
                            setPendingChoiceId(target.choice_id)
                          }}
                        >
                          {body}
                        </button>
                      ) : body}
                    </li>
                  )
                })}
              </ul>
              <p className="builder-hint">{t('builder.summary.reviewHint')}</p>
            </div>

            <button
              type="button"
              className="button secondary full"
              disabled={saving}
              onClick={() => {
                if (window.confirm(t('builder.cancel.confirm'))) cancel.mutate()
              }}
            >
              {t('builder.cancel.button')}
            </button>
          </aside>
        </div>
      </div>
    </main>
  )
}
