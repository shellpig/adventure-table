import React, { useEffect, useState } from 'react'

import type { RoomCharacterSummary } from '../../api/campaigns'
import {
  createRuntimeEntry,
  updateRuntimeEntry,
  type CampaignAdventureOverride,
  type CampaignRuntimeContext,
  type RuntimeWorldEntryDmView,
} from '../../api/campaignRuntime'
import { useLocale } from '../../i18n/LocaleProvider'
import {
  campaignRuntimeCopy,
  campaignRuntimeErrorMessage,
  type CampaignRuntimeCopy,
} from './campaignRuntimeCopy'
import {
  buildCreateEntryRequest,
  buildUpdateEntryRequest,
  createInitialEntryFormState,
  entryToFormState,
  executeRuntimeMutation,
  generateRuntimeIdempotencyKey,
  handleArchiveRuntimeEntry,
  loadCampaignChanges,
  type RuntimeEntryFormState,
} from './campaignRuntimeForm'
import {
  RuntimeEntryCardView,
  RuntimeEntryFormView,
} from './CampaignRuntimeEntries'
import { recentRoomForId } from './roomStorage'
import './rooms.css'

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
): boolean {
  if (entries.length > 0 || overrides.length > 0) return false
  if (!context) return true
  return (
    !context.current_adventure_scene_entry_id &&
    !context.current_runtime_scene_entry_id &&
    !context.current_situation
  )
}

export type CampaignChangesManagement = {
  characters: RoomCharacterSummary[]
  formState: RuntimeEntryFormState | null
  pending: boolean
  formError: string | null
  mutationError: string | null
  committedWarning: string | null
  onOpenCreate: () => void
  onOpenEdit: (entry: RuntimeWorldEntryDmView) => void
  onCancelForm: () => void
  onChangeForm: (updater: (prev: RuntimeEntryFormState) => RuntimeEntryFormState) => void
  onSubmitForm: (e: React.FormEvent) => void
  onArchiveEntry: (entry: RuntimeWorldEntryDmView) => void
}

export type CampaignChangesViewProps = {
  roomId: string
  campaignId: string
  loading: boolean
  error: string | null
  entries: RuntimeWorldEntryDmView[]
  overrides: CampaignAdventureOverride[]
  context: CampaignRuntimeContext | null
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
  management,
  copy,
}: CampaignChangesViewProps) {
  const isEmpty = isCampaignChangesEmpty(entries, overrides, context)
  const backHref = `/rooms/${roomId}/campaigns/${campaignId}`
  const currentScene =
    context?.current_runtime_scene_entry_id ??
    context?.current_adventure_scene_entry_id ??
    null

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
        {management?.committedWarning ? (
          <div className="notice-banner" role="status">
            {management.committedWarning}
          </div>
        ) : null}
        {!loading && !error && isEmpty ? (
          <div>
            <p>{copy.emptyState}</p>
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
                  onCancel={management.onCancelForm}
                  onChange={management.onChangeForm}
                  onSubmit={management.onSubmitForm}
                  pending={management.pending}
                />
              </div>
            ) : null}
          </div>
        ) : null}
        {!loading && !error && !isEmpty ? (
          <div>
            <hr />
            <section>
              <h2>{copy.contextHeading}</h2>
              <p>
                <strong>{copy.currentSceneLabel}:</strong> {currentScene ?? copy.noCurrentScene}
              </p>
              {context?.current_situation ? (
                <p>
                  <strong>{copy.currentSituationLabel}:</strong> {context.current_situation}
                </p>
              ) : null}
            </section>
            <hr />
            <section>
              <h2>{copy.entriesHeading}</h2>
              <p>
                {copy.entryCountLabel}: {entries.length}
              </p>
              {management?.mutationError ? (
                <div className="error-banner">{management.mutationError}</div>
              ) : null}
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
                    onCancel={management.onCancelForm}
                    onChange={management.onChangeForm}
                    onSubmit={management.onSubmitForm}
                    pending={management.pending}
                  />
                </div>
              ) : null}
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
            </section>
            <hr />
            <section>
              <h2>{copy.overridesHeading}</h2>
              <p>
                {copy.overrideCountLabel}: {overrides.length}
              </p>
            </section>
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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [formState, setFormState] = useState<RuntimeEntryFormState | null>(null)
  const [pending, setPending] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [mutationError, setMutationError] = useState<string | null>(null)
  const [committedWarning, setCommittedWarning] = useState<string | null>(null)

  const handleReload = async () => {
    const snapshot = await loadCampaignChanges(roomId, campaignId, token)
    setEntries(snapshot.entries)
    setOverrides(snapshot.overrides)
    setContext(snapshot.context)
    setCharacters(snapshot.characters)
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

  const handleOpenCreate = () => {
    setFormState(createInitialEntryFormState('scene'))
    setFormError(null)
    setMutationError(null)
    setCommittedWarning(null)
  }

  const handleOpenEdit = (entry: RuntimeWorldEntryDmView) => {
    const nextState = entryToFormState(entry)
    if (!nextState) return
    setFormState(nextState)
    setFormError(null)
    setMutationError(null)
    setCommittedWarning(null)
  }

  const handleCancelForm = () => {
    setFormState(null)
    setFormError(null)
  }

  const handleChangeForm = (
    updater: (prev: RuntimeEntryFormState) => RuntimeEntryFormState,
  ) => {
    setFormState((prev) => (prev ? updater(prev) : prev))
  }

  const handleSubmitForm = (e: React.FormEvent) => {
    e.preventDefault()
    if (!formState) return

    if (formState.mode === 'create') {
      const idempotencyKey = generateRuntimeIdempotencyKey('runtime-entry-create')
      const built = buildCreateEntryRequest(formState, idempotencyKey)
      if (!built.ok) {
        setFormError(copy[built.errorKey])
        return
      }
      setPending(true)
      setFormError(null)
      setMutationError(null)
      setCommittedWarning(null)
      void executeRuntimeMutation({
        action: () => createRuntimeEntry(roomId, campaignId, token, built.value),
        onReload: handleReload,
        onSuccess: () => {
          setFormState(null)
          setPending(false)
        },
        onError: (err) => {
          setFormError(err)
          setPending(false)
        },
        onCommittedReloadError: () => {
          setFormState(null)
          setPending(false)
          setFormError(null)
          setMutationError(null)
          setCommittedWarning(copy.committedReloadWarning)
        },
        copy,
      })
    } else {
      const idempotencyKey = generateRuntimeIdempotencyKey('runtime-entry-update')
      const built = buildUpdateEntryRequest(formState, idempotencyKey)
      if (!built.ok) {
        setFormError(copy[built.errorKey])
        return
      }
      setPending(true)
      setFormError(null)
      setMutationError(null)
      setCommittedWarning(null)
      void executeRuntimeMutation({
        action: () =>
          updateRuntimeEntry(roomId, campaignId, formState.entryId, token, built.value),
        onReload: handleReload,
        onSuccess: () => {
          setFormState(null)
          setPending(false)
        },
        onError: (err) => {
          setFormError(err)
          setPending(false)
        },
        onCommittedReloadError: () => {
          setFormState(null)
          setPending(false)
          setFormError(null)
          setMutationError(null)
          setCommittedWarning(copy.committedReloadWarning)
        },
        copy,
      })
    }
  }

  const handleArchive = (entry: RuntimeWorldEntryDmView) => {
    const idempotencyKey = generateRuntimeIdempotencyKey('runtime-entry-archive')
    void handleArchiveRuntimeEntry({
      roomId,
      campaignId,
      entryId: entry.id,
      revision: entry.revision,
      token,
      idempotencyKey,
      onStart: () => {
        setPending(true)
        setMutationError(null)
        setCommittedWarning(null)
      },
      onCancel: () => {
        setPending(false)
      },
      onReload: handleReload,
      onSuccess: () => {
        setPending(false)
      },
      onError: (err) => {
        setMutationError(err)
        setPending(false)
      },
      onCommittedReloadError: () => {
        setPending(false)
        setMutationError(null)
        setCommittedWarning(copy.committedReloadWarning)
      },
      copy,
    })
  }

  const management: CampaignChangesManagement = {
    characters,
    formState,
    pending,
    formError,
    mutationError,
    committedWarning,
    onOpenCreate: handleOpenCreate,
    onOpenEdit: handleOpenEdit,
    onCancelForm: handleCancelForm,
    onChangeForm: handleChangeForm,
    onSubmitForm: handleSubmitForm,
    onArchiveEntry: handleArchive,
  }

  return (
    <CampaignChangesView
      campaignId={campaignId}
      context={context}
      copy={copy}
      entries={entries}
      error={error}
      loading={loading}
      management={management}
      overrides={overrides}
      roomId={roomId}
    />
  )
}
