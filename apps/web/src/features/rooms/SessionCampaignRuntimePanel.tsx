import React from 'react'

import type { RoomCharacterSummary } from '../../api/campaigns'
import { useLocale } from '../../i18n/LocaleProvider'
import {
  campaignRuntimeCopy,
  type CampaignRuntimeCopy,
} from './campaignRuntimeCopy'
import { CampaignRuntimeContextView, type CampaignRuntimeContextActions } from './CampaignRuntimeContext'
import { RuntimeEntryFormView } from './CampaignRuntimeEntries'
import {
  SESSION_QUICK_ADD_KINDS,
  useSessionCampaignRuntime,
  type ActiveSessionRuntimeSnapshot,
  type SessionCampaignRuntimeActions,
} from './sessionCampaignRuntime'
import './rooms.css'
import './sessionTable.css'

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
