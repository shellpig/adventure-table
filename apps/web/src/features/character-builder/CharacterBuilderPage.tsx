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
import { SearchableSelect } from '../../components/SearchableSelect'
import { ClassProgressionStep } from './ClassProgressionStep'
import './builder.css'

type BuilderStep = 'basic' | 'origin' | 'abilities' | 'class'

type ChoiceEditorProps = {
  choice: BuilderChoice
  view: BuilderView
  disabled: boolean
  onSave: (payload: BuilderDraftPayload) => void
}

const DIRECT_OPTION_SOURCES = new Set([
  'content:race',
  'content:background',
  'content:alignment',
  'content:subrace',
  'content:subclass',
  'builder:ability-generation',
  'content:class',
])

const ABILITY_LABELS: Record<keyof BuilderAbilityScores, string> = {
  strength: 'STR · Strength',
  dexterity: 'DEX · Dexterity',
  constitution: 'CON · Constitution',
  intelligence: 'INT · Intelligence',
  wisdom: 'WIS · Wisdom',
  charisma: 'CHA · Charisma',
}

const ABILITY_KEYS = Object.keys(ABILITY_LABELS) as (keyof BuilderAbilityScores)[]
const EMPTY_SCORES: BuilderAbilityScores = {
  strength: 0,
  dexterity: 0,
  constitution: 0,
  intelligence: 0,
  wisdom: 0,
  charisma: 0,
}

function selectionOptions(choice: BuilderChoice) {
  return choice.options.map((option) => ({
    value: option.option_id,
    label: option.label,
    disabled: Boolean(option.disabled_reason),
    disabledReason: option.disabled_reason ?? undefined,
  }))
}

function ChoiceEditor({ choice, view, disabled, onSave }: ChoiceEditorProps) {
  if (choice.disabled_reason) {
    return (
      <div className="builder-choice is-disabled">
        <div>
          <strong>{choice.label}</strong>
          <small>{choice.disabled_reason}</small>
        </div>
        <span className="builder-lock">LOCKED</span>
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
      <div className="builder-choice">
        <SearchableSelect
          label={choice.label}
          value={selected[0] ?? ''}
          disabled={disabled}
          options={selectionOptions(choice)}
          onChange={(value) => saveSelected(value ? [value] : [])}
        />
      </div>
    )
  }

  const selectedLabels = selected.map((id) => ({
    id,
    label: choice.options.find((option) => option.option_id === id)?.label ?? id,
  }))
  const canAdd = selected.length < choice.choose_count
  return (
    <div className="builder-choice">
      <div className="builder-choice__heading">
        <strong>{choice.label}</strong>
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
        label="Add selection"
        value=""
        disabled={disabled || !canAdd}
        options={selectionOptions(choice).map((option) => ({
          ...option,
          disabled: option.disabled || selected.includes(option.value),
          disabledReason: selected.includes(option.value) ? 'Already selected' : option.disabledReason,
        }))}
        onChange={(value) => {
          if (value && !selected.includes(value)) saveSelected([...selected, value])
        }}
      />
    </div>
  )
}

export function CharacterBuilderPage({ draftId }: { draftId: string }) {
  const queryClient = useQueryClient()
  const [step, setStep] = useState<BuilderStep>('basic')
  const draftQuery = useQuery({
    queryKey: ['builder-draft', draftId],
    queryFn: () => getBuilderDraft(draftId),
  })
  const rulesQuery = useQuery({
    queryKey: ['builder-rules', 'ability-generation'],
    queryFn: getAbilityGenerationRules,
  })
  const view = draftQuery.data

  const save = useMutation({
    mutationFn: (payload: BuilderDraftPayload) => {
      if (!view) throw new Error('Draft is not loaded yet')
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
  const startingChoices = useMemo(
    () =>
      view?.choices.filter(
        (choice) =>
          !DIRECT_OPTION_SOURCES.has(choice.option_source ?? '') &&
          !choice.choice_id.startsWith('level:'),
      ) ?? [],
    [view],
  )

  if (draftQuery.isLoading) {
    return <main className="builder-loading">Loading Character Builder…</main>
  }
  if (draftQuery.error || !view) {
    return (
      <main className="builder-loading">
        <div className="error-banner">{draftQuery.error?.message ?? 'Builder draft not found.'}</div>
        <a className="button secondary" href="/characters">Back to Workshop</a>
      </main>
    )
  }

  const saving = save.isPending || cancel.isPending
  const raceChoice = choicesBySource.get('content:race')
  const subraceChoice = choicesBySource.get('content:subrace')
  const backgroundChoice = choicesBySource.get('content:background')
  const alignmentChoice = choicesBySource.get('content:alignment')
  const currentRace = view.draft.draft_payload.race_selection?.reference_id ?? ''
  const currentSubrace = view.draft.draft_payload.subrace_selection?.reference_id ?? ''
  const currentBackground = view.draft.draft_payload.background_selection?.reference_id ?? ''
  const currentAlignment = view.draft.draft_payload.alignment_selection?.reference_id ?? ''

  const patchReference = (
    field: 'race_selection' | 'subrace_selection' | 'background_selection' | 'alignment_selection',
    value: string,
    resetChoices = false,
  ) => {
    const payload: BuilderDraftPayload = { [field]: value ? { reference_id: value } : null }
    if (field === 'race_selection') payload.subrace_selection = null
    if (resetChoices) payload.choice_selections = {}
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

  return (
    <main className="builder-page">
      <div className="builder-shell">
        <header className="builder-topbar">
          <div>
            <a href="/characters" className="builder-back">← Character Workshop</a>
            <p className="eyebrow">P1-C · Create Character</p>
            <h1>{view.resolved_summary.name?.trim() || 'Unnamed character'}</h1>
          </div>
          <div className="builder-save-state">
            <span>Draft revision {view.draft.revision}</span>
            <strong>{saving ? 'Saving…' : 'Saved on server'}</strong>
          </div>
        </header>

        {save.error ? <div className="error-banner">{save.error.message}</div> : null}

        <div className="builder-layout">
          <aside className="builder-rail" aria-label="Character creation steps">
            <button className={step === 'basic' ? 'is-active' : ''} onClick={() => setStep('basic')}>
              <span>01</span><div><strong>Basic</strong><small>Name & target</small></div>
            </button>
            <button className={step === 'origin' ? 'is-active' : ''} onClick={() => setStep('origin')}>
              <span>02</span><div><strong>Origin</strong><small>Race & background</small></div>
            </button>
            <button className={step === 'abilities' ? 'is-active' : ''} onClick={() => setStep('abilities')}>
              <span>03</span><div><strong>Abilities</strong><small>Scores & starting choices</small></div>
            </button>
            <button className={step === 'class' ? 'is-active' : ''} onClick={() => setStep('class')}>
              <span>04</span><div><strong>Class</strong><small>Level-by-level rail</small></div>
            </button>
            <button disabled><span>05</span><div><strong>Review</strong><small>P1-F</small></div></button>
          </aside>

          <section className="builder-form">
            {step === 'basic' ? (
              <div className="builder-step">
                <div className="builder-step__heading">
                  <p className="eyebrow">STEP 01</p>
                  <h2>Start with the character</h2>
                  <p>Name and target level define the draft. Ruleset is fixed to D&amp;D 5e 2014.</p>
                </div>
                <div className="builder-field-grid">
                  <label className="builder-field">
                    <span>Character name</span>
                    <input value={name} onChange={(event) => setName(event.target.value)} maxLength={200} />
                  </label>
                  <label className="builder-field">
                    <span>Target character level</span>
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
                  <span>Ruleset</span><strong>D&amp;D 5e · 2014</strong><small>Built-in content: SRD 5.1</small>
                </div>
                <div className="builder-optional">
                  <h3>Roleplay notes <span>Optional</span></h3>
                  <label className="builder-field"><span>Appearance</span><textarea value={appearance} onChange={(event) => setAppearance(event.target.value)} /></label>
                  <label className="builder-field"><span>Biography</span><textarea value={biography} onChange={(event) => setBiography(event.target.value)} /></label>
                </div>
                <button
                  type="button"
                  className="button primary"
                  disabled={saving || targetLevel < 1 || targetLevel > 20}
                  onClick={() =>
                    save.mutate({
                      basic: { name, ruleset: 'dnd5e-2014' },
                      target_level: targetLevel,
                      level_choices: (view.draft.draft_payload.level_choices ?? []).slice(0, targetLevel),
                      roleplay_profile: { appearance, biography },
                    })
                  }
                >
                  Save Basic Details
                </button>
              </div>
            ) : null}

            {step === 'origin' ? (
              <div className="builder-step">
                <div className="builder-step__heading">
                  <p className="eyebrow">STEP 02</p>
                  <h2>Choose an origin</h2>
                  <p>Selectors come from server-generated eligible content. Subrace is preserved as its own choice.</p>
                </div>
                {raceChoice ? (
                  <SearchableSelect label="Race" value={currentRace} disabled={saving} options={selectionOptions(raceChoice)} onChange={(value) => patchReference('race_selection', value, true)} />
                ) : null}
                {subraceChoice ? (
                  <SearchableSelect label="Subrace" value={currentSubrace} disabled={saving} options={selectionOptions(subraceChoice)} onChange={(value) => patchReference('subrace_selection', value, true)} />
                ) : null}
                {backgroundChoice ? (
                  <SearchableSelect label="Background" value={currentBackground} disabled={saving} options={selectionOptions(backgroundChoice)} onChange={(value) => patchReference('background_selection', value, true)} />
                ) : null}
                {alignmentChoice ? (
                  <SearchableSelect label="Alignment · optional" value={currentAlignment} disabled={saving} options={selectionOptions(alignmentChoice)} onChange={(value) => patchReference('alignment_selection', value)} />
                ) : null}
                <div className="builder-grant-preview">
                  <span>Resolved grants</span><strong>{view.resolved_summary.grants.length}</strong><small>Traits, languages and proficiencies are resolved by the server.</small>
                </div>
              </div>
            ) : null}

            {step === 'abilities' ? (
              <div className="builder-step">
                <div className="builder-step__heading">
                  <p className="eyebrow">STEP 03</p>
                  <h2>Abilities & starting choices</h2>
                  <p>Base generation stays separate from racial grants and Numeric Overrides.</p>
                </div>
                <div className="ability-methods" role="tablist" aria-label="Ability generation method">
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
                      {method === 'standard_array' ? 'Standard Array' : method === 'point_buy' ? 'Point Buy' : 'Manual Input'}
                    </button>
                  ))}
                </div>
                {rulesQuery.error ? <div className="error-banner">{rulesQuery.error.message}</div> : null}
                <div className="builder-abilities">
                  {ABILITY_KEYS.map((ability) => {
                    const usedElsewhere = new Set(
                      Object.entries(abilityScores)
                        .filter(([key]) => key !== ability)
                        .map(([, score]) => score),
                    )
                    return abilityMethod === 'standard_array' ? (
                      <SearchableSelect
                        key={ability}
                        label={ABILITY_LABELS[ability]}
                        value={abilityScores[ability] ? String(abilityScores[ability]) : ''}
                        disabled={saving || !abilityRules}
                        options={standardValues.map((score) => ({
                          value: String(score),
                          label: String(score),
                          disabled: usedElsewhere.has(score),
                          disabledReason: usedElsewhere.has(score) ? 'Already assigned' : undefined,
                        }))}
                        onChange={(value) => setAbilityScores((current) => ({ ...current, [ability]: Number(value) }))}
                      />
                    ) : (
                      <label className="builder-field ability-input" key={ability}>
                        <span>{ABILITY_LABELS[ability]}</span>
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
                      ? `Point Buy · legal scores only · budget ${abilityRules.point_buy_budget}`
                      : `Point Buy · ${pointBuySpent} / ${abilityRules.point_buy_budget} points used`
                    : abilityMethod === 'manual' && abilityRules
                      ? `Manual values outside ${abilityRules.manual_standard_min}–${abilityRules.manual_standard_max} are preserved and marked Non-standard.`
                      : 'Each Standard Array value must be assigned exactly once.'}
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
                  Save Ability Scores
                </button>

                <div className="builder-choice-list">
                  <h3>Starting choices</h3>
                  {startingChoices.length ? (
                    startingChoices.map((choice) => (
                      <ChoiceEditor key={choice.choice_id} choice={choice} view={view} disabled={saving} onSave={(payload) => save.mutate(payload)} />
                    ))
                  ) : (
                    <p className="builder-muted">Choose Race / Background first to reveal starting choices.</p>
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
          </section>

          <aside className="builder-summary">
            <div className="builder-summary__top">
              <div><span>LIVE SUMMARY</span><h2>{view.resolved_summary.name?.trim() || 'Unnamed'}</h2></div>
              <strong>LV {view.resolved_summary.target_level ?? '—'}</strong>
            </div>
            <dl className="builder-summary__facts">
              <div><dt>Race</dt><dd>{view.resolved_summary.race_name ?? '—'}{view.resolved_summary.subrace_name ? ` · ${view.resolved_summary.subrace_name}` : ''}</dd></div>
              <div><dt>Background</dt><dd>{view.resolved_summary.background_name ?? '—'}</dd></div>
              <div><dt>Class</dt><dd>{view.resolved_summary.class_summary ?? '—'}</dd></div>
              <div><dt>Alignment</dt><dd>{view.resolved_summary.alignment_name ?? 'Optional'}</dd></div>
            </dl>

            {view.resolved_summary.ability_scores.length ? (
              <div className="summary-abilities">
                {view.resolved_summary.ability_scores.map((score) => (
                  <div key={score.ability}>
                    <span>{score.ability.slice(0, 3).toUpperCase()}</span>
                    <strong>{score.effective}</strong>
                    <small>{score.base} {score.permanent_bonus ? `+ ${score.permanent_bonus}` : ''}{score.overridden ? ' · override' : ''}</small>
                  </div>
                ))}
              </div>
            ) : null}

            <div className="summary-grants">
              <h3>Resolved grants</h3>
              {view.resolved_summary.grants.slice(0, 12).map((grant, index) => (
                <div key={`${grant.source_ref}:${grant.reference_id ?? grant.label}:${index}`}>
                  <span>{grant.kind}</span><strong>{grant.label}</strong>
                </div>
              ))}
              {view.resolved_summary.grants.length > 12 ? <small>+ {view.resolved_summary.grants.length - 12} more</small> : null}
            </div>

            <div className="summary-validation">
              <div className="summary-validation__heading">
                <h3>Validation</h3>
                <span className={issueCount ? 'has-errors' : 'is-clear'}>{issueCount} blocking</span>
              </div>
              <ul>
                {view.validation.issues.map((issue, index) => (
                  <li className={`issue-${issue.severity}`} key={`${issue.code}:${issue.path}:${index}`}>
                    <strong>{issue.code.replaceAll('_', ' ')}</strong><span>{issue.message}</span>
                  </li>
                ))}
              </ul>
              <p className="builder-hint">P1-C validates the full class rail. Confirm remains locked until P1-D through P1-F complete the remaining Build choices.</p>
            </div>

            <button
              type="button"
              className="button secondary full"
              disabled={saving}
              onClick={() => {
                if (window.confirm('Cancel this unfinished draft?')) cancel.mutate()
              }}
            >
              Cancel Draft
            </button>
          </aside>
        </div>
      </div>
    </main>
  )
}
