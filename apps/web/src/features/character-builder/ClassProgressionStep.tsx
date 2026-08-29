import {
  type BuilderChoice,
  type BuilderDraftPayload,
  type BuilderHPMethod,
  type BuilderLevelChoice,
  type BuilderView,
} from '../../api/characterBuilder'
import { SearchableSelect } from '../../components/SearchableSelect'


type Props = {
  view: BuilderView
  disabled: boolean
  onSave: (payload: BuilderDraftPayload) => void
}

function optionsFor(choice: BuilderChoice) {
  return choice.options.map((option) => ({
    value: option.option_id,
    label: option.label,
    disabled: Boolean(option.disabled_reason),
    disabledReason: option.disabled_reason ?? undefined,
  }))
}

function LevelChoiceEditor({
  choice,
  view,
  disabled,
  onSave,
}: {
  choice: BuilderChoice
  view: BuilderView
  disabled: boolean
  onSave: (payload: BuilderDraftPayload) => void
}) {
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

  if (choice.choose_count === 1) {
    return (
      <SearchableSelect
        label={choice.label}
        value={selected[0] ?? ''}
        disabled={disabled}
        options={optionsFor(choice)}
        onChange={(value) => saveSelected(value ? [value] : [])}
      />
    )
  }

  const canAdd = selected.length < choice.choose_count
  return (
    <div className="builder-choice progression-choice">
      <div className="builder-choice__heading">
        <strong>{choice.label}</strong>
        <span>{selected.length} / {choice.choose_count}</span>
      </div>
      <div className="builder-choice__chips">
        {selected.map((id) => (
          <button
            type="button"
            key={id}
            disabled={disabled}
            onClick={() => saveSelected(selected.filter((item) => item !== id))}
          >
            {choice.options.find((option) => option.option_id === id)?.label ?? id} ×
          </button>
        ))}
      </div>
      <SearchableSelect
        label="Add selection"
        value=""
        disabled={disabled || !canAdd}
        options={optionsFor(choice).map((option) => ({
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

export function ClassProgressionStep({ view, disabled, onSave }: Props) {
  const targetLevel = view.draft.draft_payload.target_level ?? 0
  const savedLevels = view.draft.draft_payload.level_choices ?? []
  const choicesById = new Map(view.choices.map((choice) => [choice.choice_id, choice]))
  const nodesByLevel = new Map(
    view.resolved_summary.progression.map((node) => [node.character_level, node]),
  )

  const saveLevel = (level: number, next: BuilderLevelChoice) => {
    const levels = [...savedLevels]
    levels[level - 1] = next
    onSave({ level_choices: levels })
  }

  const selectClass = (level: number, classRef: string) => {
    const classChoice = choicesById.get(`level:${level}:class-selection`)
    const option = classChoice?.options.find((candidate) => candidate.option_id === classRef)
    if (!option || option.disabled_reason || !option.hit_die_size || !option.fixed_hp_gain) return
    const current = savedLevels[level - 1]
    const sameClass = current?.class_ref === classRef
    saveLevel(level, {
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
    })
  }

  const setHPMethod = (level: number, method: BuilderHPMethod) => {
    const current = savedLevels[level - 1]
    const node = nodesByLevel.get(level)
    if (!current || !node || level === 1) return
    saveLevel(level, {
      ...current,
      hp_method: method,
      hp_base_gain: method === 'fixed_average' ? node.fixed_hp_gain : Math.min(current.hp_base_gain, node.hit_die_size),
    })
  }

  if (!targetLevel) {
    return <p className="builder-muted">Set a target level first.</p>
  }

  return (
    <div className="builder-step class-progression-step">
      <div className="builder-step__heading">
        <p className="eyebrow">STEP 04</p>
        <h2>Build the level rail</h2>
        <p>
          Every row is one real Character Level. Class level, multiclass prerequisites, subclass timing,
          grants and HP are recalculated by the server from this exact order.
        </p>
      </div>

      <div className="progression-overview">
        <div><span>Starting class</span><strong>{view.resolved_summary.starting_class_name ?? 'Choose Lv1'}</strong></div>
        <div><span>Progression</span><strong>{view.resolved_summary.class_summary ?? 'Not started'}</strong></div>
        <div><span>Filled</span><strong>{savedLevels.length} / {targetLevel}</strong></div>
      </div>

      <div className="level-rail" aria-label="Class progression level rail">
        {Array.from({ length: targetLevel }, (_, index) => {
          const level = index + 1
          const current = savedLevels[index]
          const node = nodesByLevel.get(level)
          const classChoice = choicesById.get(`level:${level}:class-selection`)
          const subclassChoice = choicesById.get(`level:${level}:subclass-selection`)
          const levelSpecificChoices = view.choices.filter(
            (choice) =>
              choice.choice_id.startsWith(`level:${level}:`) &&
              choice.option_source === 'content:class-proficiency',
          )
          const canEdit = level === 1 || savedLevels.length >= level - 1

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
                    label={`Level ${level} class`}
                    value={current?.class_ref ?? ''}
                    disabled={disabled || !canEdit}
                    options={optionsFor(classChoice)}
                    onChange={(value) => value && selectClass(level, value)}
                  />
                ) : null}

                {!canEdit ? (
                  <p className="builder-muted">Complete the previous level first.</p>
                ) : null}

                {node && current ? (
                  <div className="level-node__details">
                    <div className="level-node__meta">
                      <span>{node.class_name} {node.class_level}</span>
                      <span>d{node.hit_die_size}</span>
                      {node.starting_class ? <em>Starting class</em> : null}
                      {node.multiclass_entry ? <em>Multiclass entry</em> : null}
                    </div>

                    {level === 1 ? (
                      <div className="hp-row">
                        <div><span>HP method</span><strong>First-level maximum</strong></div>
                        <div><span>Base gain</span><strong>{current.hp_base_gain}</strong></div>
                      </div>
                    ) : (
                      <div className="hp-editor">
                        <label className="builder-field">
                          <span>HP method</span>
                          <select
                            value={current.hp_method}
                            disabled={disabled}
                            onChange={(event) => setHPMethod(level, event.target.value as BuilderHPMethod)}
                          >
                            <option value="fixed_average">Fixed average ({node.fixed_hp_gain})</option>
                            <option value="manual_rolled">Manual rolled</option>
                          </select>
                        </label>
                        <label className="builder-field">
                          <span>Base HP gain</span>
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
                        label={`${node.class_name} subclass · required at class level ${node.class_level}`}
                        value={current.subclass_ref ?? ''}
                        disabled={disabled}
                        options={optionsFor(subclassChoice)}
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
                      />
                    ))}

                    {node.automatic_feature_refs.length ? (
                      <details className="feature-preview">
                        <summary>{node.automatic_feature_refs.length} automatic feature(s)</summary>
                        <ul>
                          {node.automatic_feature_refs.map((feature) => (
                            <li key={feature}>{feature.replace('srd5.1:feature:', '').replaceAll('-', ' ')}</li>
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
