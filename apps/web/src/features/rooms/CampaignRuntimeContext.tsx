import React from 'react'

import type { AttachedAdventure } from '../../api/adventures'
import type {
  CampaignAdventureEntryOverlayView,
  CampaignRuntimeContext,
  RuntimeWorldEntryDmView,
} from '../../api/campaignRuntime'
import type { CampaignRuntimeCopy } from './campaignRuntimeCopy'
import {
  encodeSceneSelection,
  parseSceneSelection,
  type ContextFormState,
} from './campaignRuntimeOverrideForm'
import './rooms.css'

export type CampaignRuntimeContextActions = {
  pending: boolean
  formState: ContextFormState | null
  formError: string | null
  onOpenEdit: () => void
  onCancelEdit: () => void
  onChangeForm: (updater: (prev: ContextFormState) => ContextFormState) => void
  onSubmitForm: (e: React.FormEvent) => void
  onClearContext: () => void
}

export type CampaignRuntimeContextViewProps = {
  context: CampaignRuntimeContext | null
  entries: RuntimeWorldEntryDmView[]
  overlays: CampaignAdventureEntryOverlayView[]
  attachedAdventures: AttachedAdventure[]
  actions: CampaignRuntimeContextActions | null
  copy: CampaignRuntimeCopy
}

export function CampaignRuntimeContextView({
  context,
  entries,
  overlays,
  attachedAdventures,
  actions,
  copy,
}: CampaignRuntimeContextViewProps) {
  let currentSceneDisplay: string = copy.noCurrentScene
  if (context?.current_adventure_scene_entry_id) {
    const advEntry = overlays.find((o) => o.id === context.current_adventure_scene_entry_id)
    if (advEntry) {
      const adv = attachedAdventures.find((a) => a.adventure_id === advEntry.adventure_id)
      const advName = adv?.name || advEntry.adventure_id
      currentSceneDisplay = `${advEntry.title || advEntry.id} (${advName})`
    } else {
      currentSceneDisplay = context.current_adventure_scene_entry_id
    }
  } else if (context?.current_runtime_scene_entry_id) {
    const rtEntry = entries.find((e) => e.id === context.current_runtime_scene_entry_id)
    if (rtEntry) {
      currentSceneDisplay = `${rtEntry.title || rtEntry.id} (${copy.kindScene})`
    } else {
      currentSceneDisplay = context.current_runtime_scene_entry_id
    }
  }

  const hasContentToClear = Boolean(
    context?.current_adventure_scene_entry_id ||
      context?.current_runtime_scene_entry_id ||
      context?.current_situation,
  )

  const adventureScenes = overlays.filter((o) => o.kind === 'scene')
  const runtimeScenes = entries.filter((e) => e.kind === 'scene' && !e.archived_at)

  const formState = actions?.formState ?? null
  const isEditing = formState !== null

  return (
    <section className="runtime-context-card">
      <div className="runtime-context-card__header">
        <h2>{copy.contextHeading}</h2>
        {context !== null ? (
          <span className="runtime-entry__revision">
            {copy.revisionLabel} {context.revision}
          </span>
        ) : null}
      </div>

      {!isEditing ? (
        <div className="runtime-context-card__details">
          <p>
            <strong>{copy.currentSceneLabel}:</strong> <span>{currentSceneDisplay}</span>
          </p>
          {context?.current_situation ? (
            <p>
              <strong>{copy.currentSituationLabel}:</strong>{' '}
              <span>{context.current_situation}</span>
            </p>
          ) : null}

          {actions ? (
            <div className="adventure-entry__actions">
              <button
                className="button primary"
                type="button"
                disabled={actions.pending}
                onClick={actions.onOpenEdit}
              >
                {copy.editContextButton}
              </button>
              {hasContentToClear ? (
                <button
                  className="button danger"
                  type="button"
                  disabled={actions.pending}
                  onClick={actions.onClearContext}
                >
                  {copy.clearContextButton}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : actions ? (
        <form className="room-form landing-card room-workspace-card" onSubmit={actions.onSubmitForm}>
          <h3>{copy.formTitleEditContext}</h3>
          {actions.formError ? <p className="form-error">{actions.formError}</p> : null}

          <label className="room-field">
            <span>{copy.sceneSelectorLabel}</span>
            <select
              value={encodeSceneSelection(formState.sceneSelection)}
              disabled={actions.pending}
              onChange={(e) => {
                const parsed = parseSceneSelection(e.target.value)
                actions.onChangeForm((prev) => ({ ...prev, sceneSelection: parsed }))
              }}
            >
              <option value="">{copy.sceneOptionNone}</option>
              {adventureScenes.length > 0 ? (
                <optgroup label={copy.sceneGroupAdventure}>
                  {adventureScenes.map((scene) => {
                    const adv = attachedAdventures.find((a) => a.adventure_id === scene.adventure_id)
                    const advName = adv?.name || scene.adventure_id
                    const displayTitle = scene.title || scene.id
                    return (
                      <option key={`adv-${scene.id}`} value={`adventure:${scene.id}`}>
                        {displayTitle} ({advName})
                      </option>
                    )
                  })}
                </optgroup>
              ) : null}
              {runtimeScenes.length > 0 ? (
                <optgroup label={copy.sceneGroupRuntime}>
                  {runtimeScenes.map((scene) => {
                    const displayTitle = scene.title || scene.id
                    return (
                      <option key={`rt-${scene.id}`} value={`runtime:${scene.id}`}>
                        {displayTitle} ({copy.kindScene})
                      </option>
                    )
                  })}
                </optgroup>
              ) : null}
            </select>
          </label>

          <label className="room-field">
            <span>{copy.currentSituationLabel}</span>
            <textarea
              value={formState.situation}
              disabled={actions.pending}
              placeholder={copy.contextSituationPlaceholder}
              onChange={(e) => {
                const val = e.target.value
                actions.onChangeForm((prev) => ({ ...prev, situation: val }))
              }}
            />
          </label>

          <div className="adventure-entry__actions">
            <button className="button primary" type="submit" disabled={actions.pending}>
              {copy.contextSaveButton}
            </button>
            <button
              className="button secondary"
              type="button"
              disabled={actions.pending}
              onClick={actions.onCancelEdit}
            >
              {copy.cancelButton}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  )
}
