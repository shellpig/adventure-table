import { useMutation, useQuery } from '@tanstack/react-query'

import {
  confirmBuilderDraft,
  getBuilderReview,
  type BuilderChoice,
  type BuilderDraftPayload,
  type BuilderView,
} from '../../api/characterBuilder'
import { SearchableSelect } from '../../components/SearchableSelect'


type EquipmentReviewStepProps = {
  view: BuilderView
  disabled: boolean
  onSave: (payload: BuilderDraftPayload) => void
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

function optionsFor(choice: BuilderChoice) {
  return choice.options.map((option) => ({
    value: option.option_id,
    label: option.label,
    disabled: Boolean(option.disabled_reason),
    disabledReason: option.disabled_reason ?? undefined,
  }))
}

export function EquipmentReviewStep({
  view,
  disabled,
  onSave,
}: EquipmentReviewStepProps) {
  const equipmentChoices = view.choices.filter(
    (choice) => choice.option_source === 'equipment',
  )
  const equipmentSelections =
    view.draft.draft_payload.starting_equipment_choices ?? {}

  const reviewQuery = useQuery({
    queryKey: ['builder-review', view.draft.id, view.draft.revision],
    queryFn: () => getBuilderReview(view.draft.id),
  })
  const confirm = useMutation({
    mutationFn: () => confirmBuilderDraft(view.draft.id),
    onSuccess: (result) => window.location.assign(result.character_path),
  })

  const saveChoice = (choiceId: string, next: string[]) => {
    onSave({
      starting_equipment_choices: {
        ...equipmentSelections,
        [choiceId]: next,
      },
    })
  }

  const review = reviewQuery.data
  const busy = disabled || confirm.isPending
  const blockingCount =
    review?.issues.filter((issue) => issue.severity === 'blocking_error').length ??
    view.validation.issues.filter((issue) => issue.severity === 'blocking_error')
      .length

  return (
    <div className="builder-step">
      <div className="builder-step__heading">
        <p className="eyebrow">STEP 06 · P1-F</p>
        <h2>Equipment & final review</h2>
        <p>
          Starting equipment becomes immutable Build provenance. Confirm copies it
          into live inventory exactly once, then Current State evolves independently.
        </p>
      </div>

      <div className="builder-choice-list">
        <h3>Starting Equipment</h3>
        {equipmentChoices.length ? (
          equipmentChoices.map((choice) => {
            const selected = selectedIds(equipmentSelections[choice.choice_id])
            if (choice.choose_count === 1) {
              return (
                <div className="builder-choice" key={choice.choice_id}>
                  <SearchableSelect
                    label={choice.label}
                    value={selected[0] ?? ''}
                    disabled={busy}
                    options={optionsFor(choice)}
                    onChange={(value) =>
                      saveChoice(choice.choice_id, value ? [value] : [])
                    }
                  />
                </div>
              )
            }

            const selectedLabels = selected.map((id) => ({
              id,
              label:
                choice.options.find((option) => option.option_id === id)?.label ??
                id,
            }))
            return (
              <div className="builder-choice" key={choice.choice_id}>
                <div className="builder-choice__heading">
                  <strong>{choice.label}</strong>
                  <span>
                    {selected.length} / {choice.choose_count}
                  </span>
                </div>
                <div className="builder-choice__chips">
                  {selectedLabels.map((item) => (
                    <button
                      type="button"
                      key={item.id}
                      disabled={busy}
                      onClick={() =>
                        saveChoice(
                          choice.choice_id,
                          selected.filter((id) => id !== item.id),
                        )
                      }
                    >
                      {item.label} ×
                    </button>
                  ))}
                </div>
                <SearchableSelect
                  label="Add equipment"
                  value=""
                  disabled={busy || selected.length >= choice.choose_count}
                  options={optionsFor(choice).map((option) => ({
                    ...option,
                    disabled: option.disabled || selected.includes(option.value),
                    disabledReason: selected.includes(option.value)
                      ? 'Already selected'
                      : option.disabledReason,
                  }))}
                  onChange={(value) => {
                    if (value && !selected.includes(value)) {
                      saveChoice(choice.choice_id, [...selected, value])
                    }
                  }}
                />
              </div>
            )
          })
        ) : (
          <p className="builder-muted">
            Choose a starting class and background first to reveal equipment.
          </p>
        )}
      </div>

      {reviewQuery.isLoading ? (
        <div className="builder-rule-card">
          <span>Server Review</span>
          <strong>Resolving latest rules…</strong>
          <small>Build and initial Current State are generated on the server.</small>
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
              Build snapshot <span>Immutable Version 1</span>
            </h3>
            <div className="builder-rule-card">
              <span>Identity</span>
              <strong>
                {review.resolved_summary.name?.trim() || 'Unnamed'} · LV{' '}
                {review.resolved_summary.target_level ?? '—'}
              </strong>
              <small>
                {review.resolved_summary.race_name ?? '—'} ·{' '}
                {review.resolved_summary.background_name ?? '—'} ·{' '}
                {review.resolved_summary.class_summary ?? '—'}
              </small>
            </div>

            <div className="summary-abilities">
              {review.resolved_summary.ability_scores.map((score) => (
                <div key={score.ability}>
                  <span>{score.ability.slice(0, 3).toUpperCase()}</span>
                  <strong>{score.effective}</strong>
                  <small>
                    {score.resolved}
                    {score.overridden ? ' · override' : ''}
                  </small>
                </div>
              ))}
            </div>

            <div className="summary-grants">
              <h3>Resolved starting equipment</h3>
              {review.starting_equipment.map((entry) => (
                <div key={entry.entry_id}>
                  <span>× {entry.quantity}</span>
                  <strong>{entry.name}</strong>
                </div>
              ))}
              {!review.starting_equipment.length ? (
                <small>No resolved equipment yet.</small>
              ) : null}
            </div>
          </div>

          <div className="builder-optional">
            <h3>
              Initial Current State <span>Created once</span>
            </h3>
            {review.initial_state ? (
              <div className="builder-field-grid">
                <div className="builder-rule-card">
                  <span>Current HP</span>
                  <strong>{review.initial_state.current_hp}</strong>
                  <small>Temporary HP {review.initial_state.temporary_hp}</small>
                </div>
                <div className="builder-rule-card">
                  <span>Inventory</span>
                  <strong>{review.initial_state.inventory_state.length} entries</strong>
                  <small>Independent from Build after Confirm</small>
                </div>
                <div className="builder-rule-card">
                  <span>Hit Dice</span>
                  <strong>
                    {Object.entries(review.initial_state.hit_dice_state)
                      .map(([die, count]) => `${die} × ${count}`)
                      .join(' · ') || '—'}
                  </strong>
                  <small>Starts fully available</small>
                </div>
                <div className="builder-rule-card">
                  <span>Prepared Spells</span>
                  <strong>{review.initial_state.prepared_spells.length}</strong>
                  <small>Initial prepared state only</small>
                </div>
              </div>
            ) : (
              <p className="builder-muted">
                Initial state preview becomes available after all blocking choices
                are resolved.
              </p>
            )}
          </div>

          <div className="summary-validation">
            <div className="summary-validation__heading">
              <h3>Final server validation</h3>
              <span className={blockingCount ? 'has-errors' : 'is-clear'}>
                {blockingCount} blocking
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
                No blocking issues. Confirm will create Character, immutable Version
                1 and Current State in one transaction.
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
              ? 'Creating Character…'
              : 'Confirm & Create Character'}
          </button>
        </>
      ) : null}
    </div>
  )
}
