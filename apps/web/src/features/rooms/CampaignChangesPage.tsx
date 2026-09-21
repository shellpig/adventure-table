import React, { useEffect, useState } from 'react'

import type { AttachedAdventure } from '../../api/adventures'
import type { RoomCharacterSummary } from '../../api/campaigns'
import type {
  CampaignAdventureEntryOverlayView,
  CampaignAdventureOverride,
  CampaignRuntimeContext,
  RuntimeWorldEntryDmView,
} from '../../api/campaignRuntime'
import { useLocale } from '../../i18n/LocaleProvider'
import {
  campaignRuntimeCopy,
  campaignRuntimeErrorMessage,
  type CampaignRuntimeCopy,
} from './campaignRuntimeCopy'
import {
  EDITABLE_RUNTIME_ENTRY_KINDS,
  loadCampaignChanges,
} from './campaignRuntimeForm'
import {
  CampaignRuntimeContextView,
} from './CampaignRuntimeContext'
import {
  RuntimeEntryCardView,
  RuntimeEntryFormView,
} from './CampaignRuntimeEntries'
import {
  collectReviewQueueItems,
} from './campaignRuntimeOverrideForm'
import {
  CampaignAttachedAdventuresSection,
} from './CampaignRuntimeOverrides'
import {
  CampaignRuntimeReviewQueue,
} from './CampaignRuntimeReviewQueue'
import { recentRoomForId } from './roomStorage'
import {
  useCampaignChangesManagement,
  type CampaignChangesManagement,
} from './useCampaignChangesManagement'
import './rooms.css'

export type { CampaignChangesManagement }

const UUID_PATTERN = '[0-9a-fA-F-]{36}'

export type CampaignChangesRoute = {
  roomId: string
  campaignId: string
}

export function campaignChangesRouteFromPath(pathname: string): CampaignChangesRoute | null {
  const match = pathname.match(
    new RegExp(`^/rooms/(${UUID_PATTERN})/campaigns/(${UUID_PATTERN})/changes/?$`),
  )
  return match ? { roomId: match[1], campaignId: match[2] } : null
}

export function isCampaignChangesEmpty(
  entries: { length: number },
  overrides: { length: number },
  context: {
    current_adventure_scene_entry_id?: string | null
    current_runtime_scene_entry_id?: string | null
    current_situation?: string | null
  } | null,
  attachedAdventures: { length: number },
): boolean {
  if (entries.length > 0 || overrides.length > 0) return false
  if (attachedAdventures.length > 0) return false
  if (!context) return true
  return (
    !context.current_adventure_scene_entry_id &&
    !context.current_runtime_scene_entry_id &&
    !context.current_situation
  )
}

export type CampaignChangesViewProps = {
  roomId: string
  campaignId: string
  loading: boolean
  error: string | null
  entries: RuntimeWorldEntryDmView[]
  overrides: CampaignAdventureOverride[]
  context: CampaignRuntimeContext | null
  attachedAdventures: AttachedAdventure[]
  overlays: CampaignAdventureEntryOverlayView[]
  management: CampaignChangesManagement | null
  copy: CampaignRuntimeCopy
}

export function CampaignChangesView({
  roomId,
  campaignId,
  loading,
  error,
  entries,
  overrides,
  context,
  attachedAdventures,
  overlays,
  management,
  copy,
}: CampaignChangesViewProps) {
  const isEmpty = isCampaignChangesEmpty(entries, overrides, context, attachedAdventures)
  const backHref = `/rooms/${roomId}/campaigns/${campaignId}`
  const reviewQueueItems = collectReviewQueueItems(entries, overlays, attachedAdventures)

  return (
    <main className="landing-page room-workspace-page">
      <section className="landing-card room-workspace-card">
        <h1>{copy.changesTitle}</h1>
        <p>{copy.changesIntro}</p>
        <div className="workshop-card__split-actions">
          <a className="button secondary" href={backHref}>
            {copy.backCampaign}
          </a>
        </div>
        {loading ? <p>{copy.loading}</p> : null}
        {error ? <div className="error-banner">{error}</div> : null}
        {management?.mutationError ? (
          <div className="error-banner">{management.mutationError}</div>
        ) : null}
        {management?.committedWarning ? (
          <div className="notice-banner" role="status">
            {management.committedWarning}
          </div>
        ) : null}

        {!loading && !error ? (
          <div>
            {isEmpty ? <p className="runtime-review-queue__empty">{copy.emptyState}</p> : null}

            <CampaignRuntimeReviewQueue
              actions={
                management
                  ? {
                      disabled: management.pending,
                      onOpenEditOverride: management.onOpenEditOverride,
                      onOpenEditRuntime: management.onOpenEdit,
                    }
                  : null
              }
              copy={copy}
              items={reviewQueueItems}
            />

            <hr />

            <CampaignRuntimeContextView
              actions={
                management
                  ? {
                      pending: management.pending,
                      formState: management.contextFormState,
                      formError: management.contextFormError,
                      onOpenEdit: management.onOpenEditContext,
                      onCancelEdit: management.onCancelEditContext,
                      onChangeForm: management.onChangeContextForm,
                      onSubmitForm: management.onSubmitContextForm,
                      onClearContext: management.onClearContext,
                    }
                  : null
              }
              attachedAdventures={attachedAdventures}
              context={context}
              copy={copy}
              entries={entries}
              overlays={overlays}
            />

            <hr />

            <section>
              <h2>{copy.entriesHeading}</h2>
              <p>
                {copy.entryCountLabel}: {entries.length}
              </p>
              {management && !management.formState ? (
                <div className="workshop-card__split-actions">
                  <button
                    className="button primary"
                    disabled={management.pending}
                    onClick={management.onOpenCreate}
                    type="button"
                  >
                    {copy.createEntryButton}
                  </button>
                </div>
              ) : null}
              {management?.formState?.mode === 'create' ? (
                <div className="runtime-entry-create-form-wrapper">
                  <RuntimeEntryFormView
                    characters={management.characters}
                    copy={copy}
                    entries={entries}
                    form={management.formState}
                    formError={management.formError}
                    kindOptions={EDITABLE_RUNTIME_ENTRY_KINDS}
                    onCancel={management.onCancelForm}
                    onChange={management.onChangeForm}
                    onSubmit={management.onSubmitForm}
                    pending={management.pending}
                  />
                </div>
              ) : null}
              {entries.length > 0 ? (
                <ul className="adventure-entry-list">
                  {entries.map((entry) => (
                    <li key={entry.id}>
                      {management?.formState?.mode === 'edit' &&
                      management.formState.entryId === entry.id ? (
                        <RuntimeEntryFormView
                          characters={management.characters}
                          copy={copy}
                          entries={entries}
                          form={management.formState}
                          formError={management.formError}
                          kindOptions={EDITABLE_RUNTIME_ENTRY_KINDS}
                          onCancel={management.onCancelForm}
                          onChange={management.onChangeForm}
                          onSubmit={management.onSubmitForm}
                          pending={management.pending}
                        />
                      ) : (
                        <RuntimeEntryCardView
                          actions={
                            management
                              ? {
                                  disabled: management.pending,
                                  onArchive: management.onArchiveEntry,
                                  onEdit: management.onOpenEdit,
                                }
                              : null
                          }
                          characters={management ? management.characters : []}
                          copy={copy}
                          entries={entries}
                          entry={entry}
                        />
                      )}
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>

            <hr />

            <CampaignAttachedAdventuresSection
              actions={
                management
                  ? {
                      pending: management.pending,
                      activeOverrideForm: management.overrideFormState,
                      overrideFormError: management.overrideFormError,
                      onCancelOverrideForm: management.onCancelOverrideForm,
                      onChangeOverrideForm: management.onChangeOverrideForm,
                      onClearOverride: management.onClearOverride,
                      onOpenCreateOverride: management.onOpenCreateOverride,
                      onOpenEditOverride: management.onOpenEditOverride,
                      onSubmitOverrideForm: management.onSubmitOverrideForm,
                    }
                  : null
              }
              attachedAdventures={attachedAdventures}
              context={context}
              copy={copy}
              overrideCount={overrides.length}
              overlays={overlays}
            />
          </div>
        ) : null}
      </section>
    </main>
  )
}

export function CampaignChangesPage({ roomId, campaignId }: CampaignChangesRoute) {
  const { locale } = useLocale()
  const copy = campaignRuntimeCopy(locale)
  const recent = recentRoomForId(roomId)
  const token = recent?.accessToken ?? ''
  const [entries, setEntries] = useState<RuntimeWorldEntryDmView[]>([])
  const [overrides, setOverrides] = useState<CampaignAdventureOverride[]>([])
  const [context, setContext] = useState<CampaignRuntimeContext | null>(null)
  const [characters, setCharacters] = useState<RoomCharacterSummary[]>([])
  const [attachedAdventures, setAttachedAdventures] = useState<AttachedAdventure[]>([])
  const [overlays, setOverlays] = useState<CampaignAdventureEntryOverlayView[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const handleReload = async () => {
    const snapshot = await loadCampaignChanges(roomId, campaignId, token)
    setEntries(snapshot.entries)
    setOverrides(snapshot.overrides)
    setContext(snapshot.context)
    setCharacters(snapshot.characters)
    setAttachedAdventures(snapshot.attachedAdventures)
    setOverlays(snapshot.overlays)
  }

  useEffect(() => {
    if (!recent) {
      setLoading(false)
      setError(copy.missingAccess)
      return
    }

    let active = true
    setLoading(true)
    setError(null)

    loadCampaignChanges(roomId, campaignId, token)
      .then((snapshot) => {
        if (!active) return
        setEntries(snapshot.entries)
        setOverrides(snapshot.overrides)
        setContext(snapshot.context)
        setCharacters(snapshot.characters)
        setAttachedAdventures(snapshot.attachedAdventures)
        setOverlays(snapshot.overlays)
      })
      .catch((cause: unknown) => {
        if (!active) return
        setError(campaignRuntimeErrorMessage(cause, copy))
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [campaignId, locale, roomId, token])

  const management = useCampaignChangesManagement({
    roomId,
    campaignId,
    token,
    copy,
    context,
    characters,
    onReload: handleReload,
  })

  return (
    <CampaignChangesView
      attachedAdventures={attachedAdventures}
      campaignId={campaignId}
      context={context}
      copy={copy}
      entries={entries}
      error={error}
      loading={loading}
      management={recent ? management : null}
      overrides={overrides}
      overlays={overlays}
      roomId={roomId}
    />
  )
}
