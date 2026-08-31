import {
  type BuilderChoice,
  type BuilderDraftPayload,
  type BuilderHPMethod,
  type BuilderLevelChoice,
  type BuilderView,
} from '../../api/characterBuilder'
import { optionDisplay, SearchableSelect } from '../../components/SearchableSelect'
import {
  builderChoiceLabel,
  builderChoiceOptionLabel,
} from '../../i18n/builderChoicePresentation'
import type { Locale } from '../../i18n/locale'
import { type ContentNameResolver, useContentPresentations } from '../../i18n/useContentPresentations'
import { useUiCopy } from '../../i18n/useUiCopy'
import './progression.css'

type Props = {
  view: BuilderView
  disabled: boolean
  onSave: (payload: BuilderDraftPayload) => void
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

function LevelChoiceEditor({
  choice,
  view,
  disabled,
  onSave,
  nameFor,
  locale,
}: {
  choice: BuilderChoice
  view: BuilderView
  disabled: boolean
  onSave: (payload: BuilderDraftPayload) => void
  nameFor: ContentNameResolver
  locale: Locale
}) {
  const { t } = useUiCopy()
  const label = builderChoiceLabel(choice, locale, nameFor)
  const selected = view.draft.draft_payload.choice_selections?.[choice.choice_id]?.selected_option_ids ?? []
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

  if (choice.disabled_reason) {
    return (
      <div className="builder-choice progression-choice is-disabled">
        <div>
          <strong>{label}</strong>
          <small>{choice.disabled_reason}</small>
        </div>
      </div>
    )
  }

  if (choice.choose_count === 1) {
    return (
      <SearchableSelect
        label={label}
        value={selected[0] ?? ''}
        disabled={disabled}
        options={optionsFor(choice, nameFor, locale)}
        secondaryMode="duplicates"
        onChange={(value) => saveSelected(value ? [value] : [])}
      />
    )
  }

  const canAdd = selected.length < choice.choose_count
  return (
    <div className="builder-choice progression-choice">
      <div className="builder-choice__heading">
        <strong>{label}</strong>
        <span>{selected.length} / {choice.choose_count}</span>
      </div>
      <div className="builder-choice__chips">
        {selected.map((id, selectedIndex) => (
          <button
            type="button"
            key={`${id}:${selectedIndex}`}
            disabled={disabled}
            onClick={() =>
              saveSelected(selected.filter((_, index) => index !== selectedIndex))
            }
          >
            {(() => {
              const option = choice.options.find((item) => item.option_id === id)
              return option
                ? optionDisplay(builderChoiceOptionLabel(choice, option, locale, nameFor)).primary
                : nameFor(id, id)
            })()} ×
          </button>
        ))}
      </div>
      <SearchableSelect
        label={t('shared.addSelection')}
        value=""
        disabled={disabled || !canAdd}
        secondaryMode="duplicates"
        options={optionsFor(choice, nameFor, locale).map((option) => {
          const alreadySelected = selected.includes(option.value)
          return {
            ...option,
            disabled: option.disabled || (!choice.allow_duplicates && alreadySelected),
            disabledReason:
              !choice.allow_duplicates && alreadySelected
                ? t('shared.alreadySelected')
                : option.disabledReason,
          }
        })}
        onChange={(value) => {
          if (value && (choice.allow_duplicates || !selected.includes(value))) {
            saveSelected([...selected, value])
          }
        }}
      />
    </div>
  )
}

export function ClassProgressionStep({ view, disabled, onSave }: Props) {
  const { t } = useUiCopy()
  const targetLevel = view.draft.draft_payload.target_level ?? 0
  const savedLevels = view.draft.draft_payload.level_choices ?? []
  const choicesById = new Map(view.choices.map((choice) => [choice.choice_id, choice]))
  const nodesByLevel = new Map(
    view.resolved_summary.progression.map((node) => [node.character_level, node]),
  )
  const contentReferences = [
    ...view.choices.flatMap((choice) =>
      choice.options.flatMap((option) => (option.reference_id ? [option.reference_id] : [])),
    ),
    ...view.resolved_summary.progression.flatMap((node) => [
      node.class_ref,
      ...(node.subclass_ref ? [node.subclass_ref] : []),
      ...node.automatic_feature_refs,
    ]),
  ]
  const { nameFor, locale } = useContentPresentations(contentReferences)
  const localizedProgression = Array.from(
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
  const startingNode = view.resolved_summary.progression.find((node) => node.starting_class)
  const localizedStartingClass = startingNode
    ? nameFor(startingNode.class_ref, startingNode.class_name)
    : view.resolved_summary.starting_class_name ?? t('class.chooseLv1')

  const saveLevel = (
    level: number,
    next: BuilderLevelChoice,
    options: { resetSpellChoices?: boolean } = {},
  ) => {
    const levels = [...savedLevels]
    levels[level - 1] = next
    const payload: BuilderDraftPayload = { level_choices: levels }
    if (options.resetSpellChoices) payload.spell_choices = {}
    onSave(payload)
  }

  const selectClass = (level: number, classRef: string) => {
    const classChoice = choicesById.get(`level:${level}:class-selection`)
    const option = classChoice?.options.find((candidate) => candidate.option_id === classRef)
    if (!option || option.disabled_reason || !option.hit_die_size || !option.fixed_hp_gain) return
    const current = savedLevels[level - 1]
    const sameClass = current?.class_ref === classRef
    saveLevel(
      level,
      {
        character_level: level,
        class_ref: classRef,
        hp_method:
          level === 1
            ? 'first_level'
            : sameClass
              ? current.hp_method
              : 'fixed_average',
        hp_base_gain:
          level === 1
            ? option.hit_die_size
            : sameClass
              ? current.hp_base_gain
              : option.fixed_hp_gain,
        subclass_ref: sameClass ? current.subclass_ref : null,
      },
      { resetSpellChoices: !sameClass },
    )
  }

  const setHPMethod = (level: number, method: BuilderHPMethod) => {
    const current = savedLevels[level - 1]
    const node = nodesByLevel.get(level)
    if (!current || !node || level === 1) return
    saveLevel(level, {
      ...current,
      hp_method: method,
      hp_base_gain:
        method === 'fixed_average'
          ? node.fixed_hp_gain
          : Math.min(current.hp_base_gain, node.hit_die_size),
    })
  }

  if (!targetLevel) {
    return <p className="builder-muted">{t('class.targetFirst')}</p>
  }

  return (
    <div className="builder-step class-progression-step">
      <div className="builder-step__heading">
        <p className="eyebrow">{t('class.step')}</p>
        <h2>{t('class.title')}</h2>
        <p>{t('class.description')}</p>
      </div>

      <div className="progression-overview">
        <div><span>{t('class.startingClass')}</span><strong>{localizedStartingClass}</strong></div>
        <div><span>{t('class.progression')}</span><strong>{localizedProgression || t('class.notStarted')}</strong></div>
        <div><span>{t('class.filled')}</span><strong>{savedLevels.length} / {targetLevel}</strong></div>
      </div>

      <div className="level-rail" aria-label={t('class.railAria')}>
        {Array.from({ length: targetLevel }, (_, index) => {
          const level = index + 1
          const current = savedLevels[index]
          const node = nodesByLevel.get(level)
          const classChoice = choicesById.get(`level:${level}:class-selection`)
          const subclassChoice = choicesById.get(`level:${level}:subclass-selection`)
          const levelSpecificChoices = view.choices.filter((choice) => {
            if (!choice.choice_id.startsWith(`level:${level}:`)) return false
            const source = choice.option_source ?? ''
            return (
              source === 'content:class-proficiency' ||
              source === 'content:asi-feat' ||
              source === 'content:asi-ability' ||
              source.startsWith('content:feature:')
            )
          })
          const canEdit = level === 1 || savedLevels.length >= level - 1
          const localizedClassName = node ? nameFor(node.class_ref, node.class_name) : ''

          return (
            <section
              className={`level-node ${current ? 'is-filled' : ''} ${node?.multiclass_entry ? 'is-multiclass' : ''}`}
              key={level}
              data-testid={`level-node-${level}`}
            >
              <div className="level-node__index">
                <span>LV</span>
                <strong>{level}</strong>
              </div>
              <div className="level-node__body">
                {classChoice ? (
                  <SearchableSelect
                    label={t('class.levelClass', { level })}
                    value={current?.class_ref ?? ''}
                    disabled={disabled || !canEdit}
                    options={optionsFor(classChoice, nameFor, locale)}
                    secondaryMode="duplicates"
                    onChange={(value) => value && selectClass(level, value)}
                  />
                ) : null}

                {!canEdit ? (
                  <p className="builder-muted">{t('class.previousFirst')}</p>
                ) : null}

                {node && current ? (
                  <div className="level-node__details">
                    <div className="level-node__meta">
                      <span>{localizedClassName} {node.class_level}</span>
                      <span>d{node.hit_die_size}</span>
                      {node.starting_class ? <em>{t('class.startingClassBadge')}</em> : null}
                      {node.multiclass_entry ? <em>{t('class.multiclassBadge')}</em> : null}
                    </div>

                    {level === 1 ? (
                      <div className="hp-row">
                        <div><span>{t('class.hpMethod')}</span><strong>{t('class.firstLevelMax')}</strong></div>
                        <div><span>{t('class.baseGain')}</span><strong>{current.hp_base_gain}</strong></div>
                      </div>
                    ) : (
                      <div className="hp-editor">
                        <label className="builder-field">
                          <span>{t('class.hpMethod')}</span>
                          <select
                            value={current.hp_method}
                            disabled={disabled}
                            onChange={(event) => setHPMethod(level, event.target.value as BuilderHPMethod)}
                          >
                            <option value="fixed_average">{t('class.fixedAverage', { value: node.fixed_hp_gain })}</option>
                            <option value="manual_rolled">{t('class.manualRolled')}</option>
                          </select>
                        </label>
                        <label className="builder-field">
                          <span>{t('class.baseHpGain')}</span>
                          <input
                            type="number"
                            min={1}
                            max={node.hit_die_size}
                            disabled={disabled || current.hp_method !== 'manual_rolled'}
                            value={current.hp_base_gain}
                            onChange={(event) =>
                              saveLevel(level, {
                                ...current,
                                hp_base_gain: Number(event.target.value),
                              })
                            }
                          />
                        </label>
                      </div>
                    )}

                    {subclassChoice ? (
                      <SearchableSelect
                        label={t('class.subclass', { className: localizedClassName, level: node.class_level })}
                        value={current.subclass_ref ?? ''}
                        disabled={disabled}
                        options={optionsFor(subclassChoice, nameFor, locale)}
                        secondaryMode="duplicates"
                        onChange={(value) => saveLevel(level, { ...current, subclass_ref: value || null })}
                      />
                    ) : null}

                    {levelSpecificChoices.map((choice) => (
                      <LevelChoiceEditor
                        key={choice.choice_id}
                        choice={choice}
                        view={view}
                        disabled={disabled}
                        onSave={onSave}
                        nameFor={nameFor}
                        locale={locale}
                      />
                    ))}

                    {node.automatic_feature_refs.length ? (
                      <details className="feature-preview">
                        <summary>{t('class.automaticFeatures', { count: node.automatic_feature_refs.length })}</summary>
                        <ul>
                          {node.automatic_feature_refs.map((feature) => (
                            <li key={feature}>
                              {nameFor(
                                feature,
                                feature.split(':').at(-1)?.replaceAll('-', ' ') ?? t('shared.unknownFeature'),
                              )}
                            </li>
                          ))}
                        </ul>
                      </details>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </section>
          )
        })}
      </div>
    </div>
  )
}
