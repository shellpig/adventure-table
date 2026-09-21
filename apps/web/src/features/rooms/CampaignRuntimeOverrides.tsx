import React from 'react'

import type { AttachedAdventure } from '../../api/adventures'
import type {
  CampaignAdventureEntryOverlayView,
  CampaignRuntimeContext,
} from '../../api/campaignRuntime'
import {
  adventureEntryKindLabel,
  type CampaignRuntimeCopy,
} from './campaignRuntimeCopy'
import {
  computeDetachBlockers,
  type OverrideFormState,
} from './campaignRuntimeOverrideForm'
import './rooms.css'

export type CampaignAdventureOverrideFormViewProps = {
  form: OverrideFormState
  pending: boolean
  formError: string | null
  onChange: (updater: (prev: OverrideFormState) => OverrideFormState) => void
  onSubmit: (e: React.FormEvent) => void
  onCancel: () => void
  copy: CampaignRuntimeCopy
}

export function CampaignAdventureOverrideFormView({
  form,
  pending,
  formError,
  onChange,
  onSubmit,
  onCancel,
  copy,
}: CampaignAdventureOverrideFormViewProps) {
  const titleText =
    form.mode === 'create'
      ? copy.formTitleCreateOverride
      : copy.formTitleEditOverride
  const entryDisplay = form.entryTitle || form.adventureEntryId

  return (
    <form className="room-form landing-card room-workspace-card" onSubmit={onSubmit}>
      <h3>{titleText}</h3>
      <p className="runtime-entry__meta">
        <span className="adventure-entry__kind">
          {adventureEntryKindLabel(form.entryKind, copy)}
        </span>
        <strong>{entryDisplay}</strong>
      </p>
      {formError ? <p className="form-error">{formError}</p> : null}

      <label className="room-field">
        <span>{copy.overrideStateLabel}</span>
        <textarea
          value={form.stateJson}
          disabled={pending}
          rows={5}
          placeholder="{}"
          onChange={(e) => {
            const val = e.target.value
            onChange((prev) => ({ ...prev, stateJson: val }))
          }}
        />
      </label>

      <label className="room-field">
        <span>{copy.overrideNoteLabel}</span>
        <input
          type="text"
          value={form.note}
          disabled={pending}
          onChange={(e) => {
            const val = e.target.value
            onChange((prev) => ({ ...prev, note: val }))
          }}
        />
      </label>

      <label className="room-field room-field--inline">
        <input
          type="checkbox"
          checked={form.needsReview}
          disabled={pending}
          onChange={(e) => {
            const checked = e.target.checked
            onChange((prev) => ({ ...prev, needsReview: checked }))
          }}
        />
        <span>{copy.needsReviewLabel}</span>
      </label>

      <div className="adventure-entry__actions">
        <button className="button primary" type="submit" disabled={pending}>
          {copy.saveButton}
        </button>
        <button
          className="button secondary"
          type="button"
          disabled={pending}
          onClick={onCancel}
        >
          {copy.cancelButton}
        </button>
      </div>
    </form>
  )
}

export type CampaignAdventureEntryOverlayCardActions = {
  pending: boolean
  onOpenCreate: (overlay: CampaignAdventureEntryOverlayView) => void
  onOpenEdit: (overlay: CampaignAdventureEntryOverlayView) => void
  onClear: (overlay: CampaignAdventureEntryOverlayView) => void
}

export type CampaignAdventureEntryOverlayCardProps = {
  overlay: CampaignAdventureEntryOverlayView
  actions: CampaignAdventureEntryOverlayCardActions | null
  copy: CampaignRuntimeCopy
}

export function CampaignAdventureEntryOverlayCard({
  overlay,
  actions,
  copy,
}: CampaignAdventureEntryOverlayCardProps) {
  const displayTitle = overlay.title || overlay.id
  const hasOverride = overlay.override !== null

  return (
    <article className="adventure-entry runtime-entry-card" key={overlay.id}>
      <div className="adventure-entry__content">
        <div className="adventure-entry__meta">
          <span className="adventure-entry__kind">
            {adventureEntryKindLabel(overlay.kind, copy)}
          </span>
          {hasOverride && overlay.override?.needs_review ? (
            <span className="runtime-entry__badge">{copy.needsReviewBadge}</span>
          ) : null}
          {hasOverride ? (
            <span className="runtime-entry__revision">
              {copy.overrideRevisionLabel} {overlay.override?.revision}
            </span>
          ) : null}
        </div>

        <h3 className="adventure-entry__title">{displayTitle}</h3>
        {overlay.body ? <p className="adventure-entry__body">{overlay.body}</p> : null}

        {overlay.data && Object.keys(overlay.data).length > 0 ? (
          <div className="runtime-entry__typed-field">
            <strong>{copy.effectiveDataLabel}: </strong>
            <pre className="runtime-entry__json">
              <code>{JSON.stringify(overlay.data, null, 2)}</code>
            </pre>
          </div>
        ) : null}

        {hasOverride && overlay.override ? (
          <div className="runtime-override-box">
            <h4>{copy.activeOverrideNotice}</h4>
            {overlay.override.note ? (
              <p className="runtime-entry__dm-notes">
                <strong>{copy.overrideNoteLabel}: </strong>
                <span>{overlay.override.note}</span>
              </p>
            ) : null}
            <div className="runtime-entry__typed-field">
              <strong>{copy.overridePatchLabel}: </strong>
              <pre className="runtime-entry__json">
                <code>{JSON.stringify(overlay.override.state_json, null, 2)}</code>
              </pre>
            </div>
          </div>
        ) : (
          <p className="runtime-override-none">{copy.noActiveOverride}</p>
        )}
      </div>

      {actions ? (
        <div className="adventure-entry__actions">
          {hasOverride && overlay.override ? (
            <>
              <button
                className="button secondary"
                type="button"
                disabled={actions.pending}
                onClick={() => actions.onOpenEdit(overlay)}
              >
                {copy.editOverrideButton}
              </button>
              <button
                className="button danger"
                type="button"
                disabled={actions.pending}
                onClick={() => actions.onClear(overlay)}
              >
                {copy.clearOverrideButton}
              </button>
            </>
          ) : (
            <button
              className="button primary"
              type="button"
              disabled={actions.pending}
              onClick={() => actions.onOpenCreate(overlay)}
            >
              {copy.createOverrideButton}
            </button>
          )}
        </div>
      ) : null}
    </article>
  )
}

export type CampaignAttachedAdventuresActions = {
  pending: boolean
  activeOverrideForm: OverrideFormState | null
  overrideFormError: string | null
  onOpenCreateOverride: (overlay: CampaignAdventureEntryOverlayView) => void
  onOpenEditOverride: (overlay: CampaignAdventureEntryOverlayView) => void
  onCancelOverrideForm: () => void
  onChangeOverrideForm: (updater: (prev: OverrideFormState) => OverrideFormState) => void
  onSubmitOverrideForm: (e: React.FormEvent) => void
  onClearOverride: (overlay: CampaignAdventureEntryOverlayView) => void
}

export type CampaignAttachedAdventuresSectionProps = {
  attachedAdventures: AttachedAdventure[]
  overlays: CampaignAdventureEntryOverlayView[]
  overrideCount: number
  context: CampaignRuntimeContext | null
  actions: CampaignAttachedAdventuresActions | null
  copy: CampaignRuntimeCopy
}

export function CampaignAttachedAdventuresSection({
  attachedAdventures,
  overlays,
  overrideCount,
  context,
  actions,
  copy,
}: CampaignAttachedAdventuresSectionProps) {
  return (
    <section>
      <h2>{copy.overridesHeading}</h2>
      <p>
        {copy.overrideCountLabel}: {overrideCount}
      </p>
      {attachedAdventures.length === 0 ? (
        <p>{copy.noAttachedAdventures}</p>
      ) : (
        attachedAdventures.map((adv) => {
          const advOverlays = overlays.filter((o) => o.adventure_id === adv.adventure_id)
          const blockerStatus = computeDetachBlockers(adv.adventure_id, overlays, context)

          return (
            <div key={adv.adventure_id} className="attached-adventure-block">
              <div className="attached-adventure-block__header">
                <h3>{adv.name}</h3>
                {adv.summary ? <p>{adv.summary}</p> : null}
                <p className="attached-adventure-block__meta">
                  <span>
                    {copy.adventureEntriesCountLabel}: {advOverlays.length}
                  </span>
                  <span>
                    {copy.overrideCountLabel}: {blockerStatus.overrideCount}
                  </span>
                </p>
              </div>

              {blockerStatus.hasActiveOverrides ? (
                <div className="detach-blocker-warning" role="alert">
                  <strong>{copy.detachBlockerNoticeHeading}: </strong>
                  <span>{copy.detachBlockerOverrides}</span>
                </div>
              ) : null}

              {blockerStatus.hasActiveContextScene ? (
                <div className="detach-blocker-warning" role="alert">
                  <strong>{copy.detachBlockerNoticeHeading}: </strong>
                  <span>{copy.detachBlockerContextScene}</span>
                </div>
              ) : null}

              <ul className="adventure-entry-list">
                {advOverlays.map((overlay) => (
                  <li key={overlay.id}>
                    {actions?.activeOverrideForm &&
                    actions.activeOverrideForm.adventureEntryId === overlay.id ? (
                      <CampaignAdventureOverrideFormView
                        copy={copy}
                        form={actions.activeOverrideForm}
                        formError={actions.overrideFormError}
                        onCancel={actions.onCancelOverrideForm}
                        onChange={actions.onChangeOverrideForm}
                        onSubmit={actions.onSubmitOverrideForm}
                        pending={actions.pending}
                      />
                    ) : (
                      <CampaignAdventureEntryOverlayCard
                        actions={
                          actions
                            ? {
                                pending: actions.pending,
                                onClear: actions.onClearOverride,
                                onOpenCreate: actions.onOpenCreateOverride,
                                onOpenEdit: actions.onOpenEditOverride,
                              }
                            : null
                        }
                        copy={copy}
                        overlay={overlay}
                      />
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )
        })
      )}
    </section>
  )
}
