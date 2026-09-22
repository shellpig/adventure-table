import React from 'react'

import type { RoomCharacterSummary } from '../../api/campaigns'
import { useLocale } from '../../i18n/LocaleProvider'
import {
  adventureEntryKindLabel,
  campaignRuntimeCopy,
  entryKindLabel,
  type CampaignRuntimeCopy,
} from './campaignRuntimeCopy'
import { CampaignRuntimeContextView, type CampaignRuntimeContextActions } from './CampaignRuntimeContext'
import { RuntimeEntryFormView } from './CampaignRuntimeEntries'
import {
  SESSION_QUICK_ADD_KINDS,
  useSessionCampaignRuntime,
  type ActiveSessionRuntimeSnapshot,
  type SessionCampaignRuntimeActions,
  type StageCandidate,
} from './sessionCampaignRuntime'
import './rooms.css'
import './sessionTable.css'

const STAGE_CANDIDATE_GROUPS: Array<{
  group: StageCandidate['group']
  label: (copy: CampaignRuntimeCopy) => string
}> = [
  { group: 'adventure', label: (copy) => copy.stageImageGroupAdventure },
  { group: 'runtime', label: (copy) => copy.stageImageGroupRuntime },
  { group: 'room', label: (copy) => copy.stageImageGroupRoom },
]

function StageImagePicker({
  actions,
  copy,
}: {
  actions: SessionCampaignRuntimeActions
  copy: CampaignRuntimeCopy
}) {
  const candidates = actions.stageCandidates
  return (
    <div className="session-world-stage">
      <h3>{copy.stageImageHeading}</h3>
      {actions.stageSuccess ? (
        <div className="notice-banner session-world-banner" role="status">
          {actions.stageSuccess}
        </div>
      ) : null}
      {actions.stagePickerError ? (
        <div className="error-banner session-world-banner" role="alert">
          {actions.stagePickerError}
        </div>
      ) : null}
      {!actions.stagePickerOpen ? (
        <button
          type="button"
          className="button secondary session-world-stage-btn"
          disabled={actions.pending}
          onClick={actions.onOpenStagePicker}
        >
          {copy.openStagePickerButton}
        </button>
      ) : (
        <div className="session-world-stage-picker">
          {actions.stagePickerLoading || candidates === null ? (
            <p className="session-stage-picker__loading">{copy.loading}</p>
          ) : candidates.length === 0 ? (
            <div className="session-stage-picker__empty-wrapper">
              <p className="session-stage-picker__empty">{copy.stageImageEmpty}</p>
              <button
                type="button"
                className="button secondary"
                disabled={actions.pending}
                onClick={actions.onCloseStagePicker}
              >
                {copy.closeStagePickerButton}
              </button>
            </div>
          ) : (
            <form
              className="room-form"
              onSubmit={(e) => {
                e.preventDefault()
                void actions.onSubmitStageImage()
              }}
            >
              <label className="room-field">
                <span>{copy.stageImageSelectLabel}</span>
                <select
                  aria-label={copy.stageImageAriaSelect}
                  value={actions.stageSelectedKey ?? ''}
                  disabled={actions.pending}
                  onChange={(e) => actions.onSelectStageCandidate(e.target.value)}
                >
                  {STAGE_CANDIDATE_GROUPS.map(({ group, label }) => {
                    const members = candidates.filter((c) => c.group === group)
                    if (members.length === 0) return null
                    return (
                      <optgroup key={group} label={label(copy)}>
                        {members.map((c) => (
                          <option key={c.key} value={c.key}>
                            {c.label}
                          </option>
                        ))}
                      </optgroup>
                    )
                  })}
                </select>
              </label>
              <div className="adventure-entry__actions">
                <button
                  type="submit"
                  className="button primary"
                  disabled={actions.pending}
                >
                  {copy.submitStageImageButton}
                </button>
                <button
                  type="button"
                  className="button secondary"
                  disabled={actions.pending}
                  onClick={actions.onCloseStagePicker}
                >
                  {copy.closeStagePickerButton}
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </div>
  )
}

function ReviewRow({
  kindLabel,
  title,
  needsReview,
  pending,
  copy,
  onToggle,
}: {
  kindLabel: string
  title: string
  needsReview: boolean
  pending: boolean
  copy: CampaignRuntimeCopy
  onToggle: () => void
}) {
  return (
    <li className="session-world-review__item">
      <div className="session-world-review__item-info">
        <span className="adventure-entry__kind">{kindLabel}</span>
        {needsReview ? (
          <span className="runtime-entry__badge">{copy.needsReviewBadge}</span>
        ) : null}
        <strong className="session-world-review__title">{title}</strong>
      </div>
      <button
        type="button"
        className="button secondary session-world-review__toggle-btn"
        disabled={pending}
        onClick={onToggle}
      >
        {needsReview ? copy.clearNeedsReviewButton : copy.markNeedsReviewButton}
      </button>
    </li>
  )
}

function SessionReviewList({
  snapshot,
  actions,
  copy,
}: {
  snapshot: ActiveSessionRuntimeSnapshot
  actions: SessionCampaignRuntimeActions
  copy: CampaignRuntimeCopy
}) {
  const entries = snapshot.entries.filter((entry) => !entry.archived_at)
  const overlays = snapshot.overlays.flatMap((overlay) =>
    overlay.override ? [{ overlay, override: overlay.override }] : [],
  )
  return (
    <div className="session-world-review">
      <h3>{copy.sessionReviewHeading}</h3>
      {entries.length === 0 && overlays.length === 0 ? (
        <p className="session-world-review__empty">{copy.sessionReviewEmpty}</p>
      ) : (
        <ul className="session-world-review__list">
          {entries.map((entry) => (
            <ReviewRow
              key={`entry-${entry.id}`}
              kindLabel={entryKindLabel(entry.kind, copy)}
              title={entry.title || copy.unnamedEntry}
              needsReview={entry.needs_review}
              pending={actions.pending}
              copy={copy}
              onToggle={() => void actions.onToggleEntryNeedsReview(entry)}
            />
          ))}
          {overlays.map(({ overlay, override }) => (
            <ReviewRow
              key={`overlay-${overlay.id}`}
              kindLabel={adventureEntryKindLabel(overlay.kind, copy)}
              title={overlay.title || copy.unnamedEntry}
              needsReview={override.needs_review}
              pending={actions.pending}
              copy={copy}
              onToggle={() => void actions.onToggleOverrideNeedsReview(overlay)}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

export type SessionCampaignRuntimePanelViewProps = {
  snapshot: ActiveSessionRuntimeSnapshot | null
  characters: RoomCharacterSummary[]
  loading: boolean
  error: string | null
  refreshStatus: string | null
  actions: SessionCampaignRuntimeActions | null
  copy: CampaignRuntimeCopy
  onRetry: () => void
}

export function SessionCampaignRuntimePanelView({
  snapshot,
  characters,
  loading,
  error,
  refreshStatus,
  actions,
  copy,
  onRetry,
}: SessionCampaignRuntimePanelViewProps) {
  const contextActions: CampaignRuntimeContextActions | null = actions
    ? {
        pending: actions.pending,
        formState: actions.contextForm,
        formError: actions.contextError,
        onOpenEdit: actions.onOpenContextEdit,
        onCancelEdit: actions.onCancelContextEdit,
        onChangeForm: actions.onChangeContextForm,
        onSubmitForm: actions.onSubmitContextForm,
        onClearContext: actions.onClearContext,
      }
    : null

  return (
    <section className="session-world-panel" aria-label={copy.sessionWorldHeading}>
      <div className="session-world-panel__header">
        <h2>{copy.sessionWorldHeading}</h2>
        <p>{copy.sessionWorldIntro}</p>
      </div>

      {refreshStatus ? (
        <div className="notice-banner session-world-banner" role="status">
          {refreshStatus}
        </div>
      ) : null}

      {error ? (
        <div className="error-banner session-world-banner" role="alert">
          <span>{error}</span>
          <button
            type="button"
            className="button secondary session-world-retry-btn"
            onClick={onRetry}
            disabled={actions?.pending ?? loading}
          >
            {copy.retryButton}
          </button>
        </div>
      ) : null}

      {loading && !snapshot ? (
        <p className="session-world-loading">{copy.loading}</p>
      ) : null}

      {snapshot ? (
        <>
          <CampaignRuntimeContextView
            context={snapshot.context}
            entries={snapshot.entries}
            overlays={snapshot.overlays}
            attachedAdventures={snapshot.attachedAdventures}
            actions={contextActions}
            copy={copy}
          />

          {actions ? (
            <>
              <div className="session-world-quick-add">
                <h3>{copy.quickAddHeading}</h3>
                {!actions.quickAddOpen ? (
                  <button
                    type="button"
                    className="button secondary session-world-quick-add-btn"
                    disabled={actions.pending}
                    onClick={actions.onOpenQuickAdd}
                  >
                    {copy.quickAddButton}
                  </button>
                ) : actions.quickAddForm ? (
                  <div className="session-world-quick-add-form-wrapper">
                    <RuntimeEntryFormView
                      characters={characters}
                      copy={copy}
                      entries={snapshot.entries}
                      form={actions.quickAddForm}
                      formError={actions.quickAddError}
                      kindOptions={SESSION_QUICK_ADD_KINDS}
                      onCancel={actions.onCloseQuickAdd}
                      onChange={actions.onChangeQuickAdd}
                      onSubmit={actions.onSubmitQuickAdd}
                      pending={actions.pending}
                    />
                  </div>
                ) : null}
              </div>

              <StageImagePicker actions={actions} copy={copy} />

              <SessionReviewList snapshot={snapshot} actions={actions} copy={copy} />
            </>
          ) : null}
        </>
      ) : null}
    </section>
  )
}

export type SessionCampaignRuntimePanelProps = {
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  characters: RoomCharacterSummary[]
  worldEventCursor: number
  onError: (message: string) => void
}

export function SessionCampaignRuntimePanel({
  roomId,
  campaignId,
  sessionId,
  token,
  characters,
  worldEventCursor,
  onError,
}: SessionCampaignRuntimePanelProps) {
  const { locale } = useLocale()
  const copy = campaignRuntimeCopy(locale)
  const { snapshot, loading, error, refreshStatus, actions, onRetry } = useSessionCampaignRuntime({
    roomId,
    campaignId,
    sessionId,
    token,
    worldEventCursor,
    copy,
    onError,
  })

  return (
    <SessionCampaignRuntimePanelView
      snapshot={snapshot}
      characters={characters}
      loading={loading}
      error={error}
      refreshStatus={refreshStatus}
      actions={actions}
      copy={copy}
      onRetry={onRetry}
    />
  )
}
