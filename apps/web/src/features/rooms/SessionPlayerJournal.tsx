import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { RoomCharacterSummary } from '../../api/campaigns'
import {
  listActiveRuntimeEntries,
  CampaignRuntimeApiError,
  type RuntimeEntryKind,
  type RuntimeWorldEntryPlayerView,
} from '../../api/campaignRuntime'
import type { SessionSnapshot } from '../../api/sessions'
import { useLocale } from '../../i18n/LocaleProvider'
import {
  anyEntryKindLabel,
  campaignRuntimeCopy,
  type CampaignRuntimeCopy,
} from './campaignRuntimeCopy'
import { LoadCoordinator } from './sessionCampaignRuntime'
import './rooms.css'
import './sessionTable.css'

export type PlayerJournalIdentity = {
  callerAccessSessionId: string
  controlledSeatIds: string[]
  activeCharacterIds: string[]
  projectionKey: string
}

export type DerivePlayerJournalIdentityInput = {
  status: SessionSnapshot['status']
  isCurrentDm: boolean
  callerAccessSessionId: string | null
  tableSnapshot: SessionSnapshot
}

export function derivePlayerJournalIdentity(
  input: DerivePlayerJournalIdentityInput,
): PlayerJournalIdentity | null {
  if (input.status !== 'active') return null
  if (input.isCurrentDm) return null
  if (!input.callerAccessSessionId) return null

  const controlledParticipants = input.tableSnapshot.participants.filter(
    (participant) =>
      participant.role === 'player' &&
      participant.controller_access_session_id_at_join === input.callerAccessSessionId,
  )

  if (controlledParticipants.length === 0) return null

  const controlledSeatIds = Array.from(
    new Set(controlledParticipants.map((participant) => participant.seat_id)),
  ).sort()

  const activeCharacterIds = Array.from(
    new Set(
      controlledParticipants
        .map((participant) => participant.active_character_id)
        .filter((id): id is string => typeof id === 'string' && id.length > 0),
    ),
  ).sort()

  const projectionKey = `${input.callerAccessSessionId}:${controlledSeatIds.join(',')}:${activeCharacterIds.join(',')}`

  return {
    callerAccessSessionId: input.callerAccessSessionId,
    controlledSeatIds,
    activeCharacterIds,
    projectionKey,
  }
}

export const ALLOWED_PLAYER_ENTRY_KEYS: ReadonlySet<string> = new Set([
  'id',
  'campaign_id',
  'kind',
  'title',
  'body',
  'state',
  'visibility',
  'revision',
  'created_at',
  'updated_at',
])

export const VALID_RUNTIME_ENTRY_KINDS: ReadonlySet<string> = new Set<RuntimeEntryKind>([
  'scene',
  'npc',
  'item',
  'quest',
  'fact',
  'secret',
  'hazard',
  'other',
])

export const FORBIDDEN_DM_FIELDS = [
  'dm_notes',
  'character_recipient_ids',
  'needs_review',
  'source_adventure_entry_id',
  'provenance_json',
  'created_by_actor_kind',
  'created_by_actor_id',
  'archived_at',
] as const

export class UnexpectedDmProjectionError extends Error {
  constructor(message = 'Received unexpected DM projection or DM-only fields for player journal') {
    super(message)
    this.name = 'UnexpectedDmProjectionError'
  }
}

export function isSafeRuntimeWorldEntryPlayerView(
  entry: unknown,
): entry is RuntimeWorldEntryPlayerView {
  if (typeof entry !== 'object' || entry === null || Array.isArray(entry)) {
    return false
  }

  // Exact key check: object must have exactly the 10 allowed Player keys.
  // Any extra key of any name (even if value undefined) or missing key is rejected.
  const ownKeys = Reflect.ownKeys(entry)
  if (ownKeys.length !== ALLOWED_PLAYER_ENTRY_KEYS.size) {
    return false
  }
  for (const k of ownKeys) {
    if (typeof k !== 'string' || !ALLOWED_PLAYER_ENTRY_KEYS.has(k)) {
      return false
    }
  }

  // Cast-free property verification using property-in-object narrowing
  if (!('id' in entry) || typeof entry.id !== 'string' || entry.id === '') {
    return false
  }
  if (
    !('campaign_id' in entry) ||
    typeof entry.campaign_id !== 'string' ||
    entry.campaign_id === ''
  ) {
    return false
  }
  if (
    !('kind' in entry) ||
    typeof entry.kind !== 'string' ||
    !VALID_RUNTIME_ENTRY_KINDS.has(entry.kind)
  ) {
    return false
  }
  if (!('title' in entry) || (entry.title !== null && typeof entry.title !== 'string')) {
    return false
  }
  if (!('body' in entry) || (entry.body !== null && typeof entry.body !== 'string')) {
    return false
  }
  if (
    !('visibility' in entry) ||
    (entry.visibility !== 'public' && entry.visibility !== 'character')
  ) {
    return false
  }
  if (
    !('revision' in entry) ||
    typeof entry.revision !== 'number' ||
    !Number.isInteger(entry.revision) ||
    entry.revision < 1
  ) {
    return false
  }
  if (
    !('created_at' in entry) ||
    typeof entry.created_at !== 'string' ||
    entry.created_at === ''
  ) {
    return false
  }
  if (
    !('updated_at' in entry) ||
    typeof entry.updated_at !== 'string' ||
    entry.updated_at === ''
  ) {
    return false
  }

  // state must be a non-array object with state.kind === entry.kind
  if (
    !('state' in entry) ||
    typeof entry.state !== 'object' ||
    entry.state === null ||
    Array.isArray(entry.state)
  ) {
    return false
  }
  if (!('kind' in entry.state) || entry.state.kind !== entry.kind) {
    return false
  }

  return true
}

export function assertSafeRuntimeWorldEntryPlayerView(
  entry: unknown,
): asserts entry is RuntimeWorldEntryPlayerView {
  if (!isSafeRuntimeWorldEntryPlayerView(entry)) {
    throw new UnexpectedDmProjectionError()
  }
}

export function isPlayerJournalAuthorityLossError(err: unknown): boolean {
  if (err instanceof UnexpectedDmProjectionError) {
    return true
  }
  if (err instanceof CampaignRuntimeApiError) {
    return (
      err.code === 'campaign_runtime_forbidden' ||
      err.code === 'campaign_runtime_session_not_active' ||
      err.code === 'session_not_active'
    )
  }
  if (typeof err === 'object' && err !== null && 'code' in err) {
    const code = err.code
    return (
      code === 'campaign_runtime_forbidden' ||
      code === 'campaign_runtime_session_not_active' ||
      code === 'session_not_active'
    )
  }
  return false
}

export type PlayerJournalSelection = {
  publicEntries: RuntimeWorldEntryPlayerView[]
  characterEntries: RuntimeWorldEntryPlayerView[]
}

export function selectPlayerJournalProjection(
  entries: unknown[],
  allowCharacterKnowledge: boolean,
): PlayerJournalSelection {
  const publicEntries: RuntimeWorldEntryPlayerView[] = []
  const characterEntries: RuntimeWorldEntryPlayerView[] = []

  for (const rawEntry of entries) {
    assertSafeRuntimeWorldEntryPlayerView(rawEntry)

    if (rawEntry.visibility === 'public') {
      if (rawEntry.kind === 'quest' || rawEntry.kind === 'fact') {
        publicEntries.push(rawEntry)
      }
      // other public kinds excluded
    } else if (rawEntry.visibility === 'character') {
      if (!allowCharacterKnowledge) {
        throw new UnexpectedDmProjectionError(
          'Received character-visible entry when caller has no active character',
        )
      }
      characterEntries.push(rawEntry)
    } else {
      throw new UnexpectedDmProjectionError(
        'Unexpected visibility in player journal projection',
      )
    }
  }

  return { publicEntries, characterEntries }
}

export async function loadSessionPlayerJournal(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
  allowCharacterKnowledge: boolean,
): Promise<PlayerJournalSelection> {
  const entries = await listActiveRuntimeEntries(roomId, campaignId, sessionId, token)
  return selectPlayerJournalProjection(entries, allowCharacterKnowledge)
}

export type PlayerJournalCommitAction =
  | {
      kind: 'success'
      generation: number
      selection: PlayerJournalSelection
      cursor: number
    }
  | {
      kind: 'authority_loss'
      generation: number
      errorMessage: string
    }
  | {
      kind: 'generic_error'
      generation: number
      errorMessage: string
    }

export type PlayerJournalManagedState = {
  selection: PlayerJournalSelection | null
  error: string | null
  accessUnavailable: boolean
  lastLoadedCursor: number
}

export function applyPlayerJournalCommit(
  currentState: PlayerJournalManagedState,
  action: PlayerJournalCommitAction,
  coordinator: LoadCoordinator,
): PlayerJournalManagedState | null {
  if (!coordinator.isCurrent(action.generation)) {
    return null
  }

  if (action.kind === 'success') {
    return {
      selection: action.selection,
      error: null,
      accessUnavailable: false,
      lastLoadedCursor: action.cursor,
    }
  }

  if (action.kind === 'authority_loss') {
    coordinator.invalidate()
    return {
      selection: null,
      error: action.errorMessage,
      accessUnavailable: true,
      lastLoadedCursor: currentState.lastLoadedCursor,
    }
  }

  // generic_error preserves currentState.selection!
  return {
    selection: currentState.selection,
    error: action.errorMessage,
    accessUnavailable: false,
    lastLoadedCursor: currentState.lastLoadedCursor,
  }
}

export type UseSessionPlayerJournalParams = {
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  allowCharacterKnowledge: boolean
  worldEventCursor: number
  copy: CampaignRuntimeCopy
  onError: (cause: unknown) => void
}

export type SessionPlayerJournalState = {
  selection: PlayerJournalSelection | null
  loading: boolean
  error: string | null
  accessUnavailable: boolean
  retry: () => void
}

export function useSessionPlayerJournal({
  roomId,
  campaignId,
  sessionId,
  token,
  allowCharacterKnowledge,
  worldEventCursor,
  copy,
  onError,
}: UseSessionPlayerJournalParams): SessionPlayerJournalState {
  const [selection, setSelection] = useState<PlayerJournalSelection | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [accessUnavailable, setAccessUnavailable] = useState(false)

  const coordinatorRef = useRef<LoadCoordinator | null>(null)
  if (coordinatorRef.current === null) {
    coordinatorRef.current = new LoadCoordinator()
  }
  const loadCoordinator = coordinatorRef.current

  const stateRef = useRef<PlayerJournalManagedState>({
    selection: null,
    error: null,
    accessUnavailable: false,
    lastLoadedCursor: -1,
  })

  const load = useCallback(
    async (cursor: number) => {
      const generation = loadCoordinator.nextGeneration()
      setLoading(true)
      try {
        const nextSelection = await loadSessionPlayerJournal(
          roomId,
          campaignId,
          sessionId,
          token,
          allowCharacterKnowledge,
        )
        const next = applyPlayerJournalCommit(
          stateRef.current,
          { kind: 'success', generation, selection: nextSelection, cursor },
          loadCoordinator,
        )
        if (next) {
          stateRef.current = next
          setSelection(next.selection)
          setError(next.error)
          setAccessUnavailable(next.accessUnavailable)
        }
      } catch (cause) {
        const isAuthority = isPlayerJournalAuthorityLossError(cause)
        const isUnexpected = cause instanceof UnexpectedDmProjectionError
        const errorMessage = isAuthority
          ? (isUnexpected
              ? copy.journalUnexpectedDmProjection
              : copy.journalAccessUnavailable)
          : copy.journalLoadError

        const next = applyPlayerJournalCommit(
          stateRef.current,
          isAuthority
            ? { kind: 'authority_loss', generation, errorMessage }
            : { kind: 'generic_error', generation, errorMessage },
          loadCoordinator,
        )
        if (next) {
          stateRef.current = next
          setSelection(next.selection)
          setError(next.error)
          setAccessUnavailable(next.accessUnavailable)
          if (isAuthority) setLoading(false)
        }
        onError(cause)
      } finally {
        if (loadCoordinator.isCurrent(generation)) {
          setLoading(false)
        }
      }
    },
    [
      roomId,
      campaignId,
      sessionId,
      token,
      allowCharacterKnowledge,
      copy,
      onError,
      loadCoordinator,
    ],
  )

  useEffect(() => {
    if (stateRef.current.lastLoadedCursor === -1) {
      void load(worldEventCursor)
      return
    }
    if (worldEventCursor > stateRef.current.lastLoadedCursor) {
      void load(worldEventCursor)
    }
  }, [worldEventCursor, load])

  const retry = useCallback(() => {
    void load(worldEventCursor)
  }, [load, worldEventCursor])

  return {
    selection,
    loading,
    error,
    accessUnavailable,
    retry,
  }
}

export type SessionPlayerJournalViewProps = {
  selection: PlayerJournalSelection | null
  characterNames: string[]
  hasActiveCharacters: boolean
  loading: boolean
  error: string | null
  accessUnavailable: boolean
  copy: CampaignRuntimeCopy
  onRetry: () => void
}

export function SessionPlayerJournalView({
  selection,
  characterNames,
  hasActiveCharacters,
  loading,
  error,
  accessUnavailable,
  copy,
  onRetry,
}: SessionPlayerJournalViewProps) {
  const publicEntries = selection?.publicEntries ?? []
  const characterEntries = selection?.characterEntries ?? []

  return (
    <section className="session-journal-panel" aria-label={copy.playerJournalHeading}>
      <div className="session-journal-panel__header">
        <h2>{copy.playerJournalHeading}</h2>
        <p>{copy.playerJournalIntro}</p>
      </div>

      {loading && selection === null ? (
        <div className="session-journal-loading" role="status">
          {copy.loading}
        </div>
      ) : null}

      {error ? (
        <div className="error-banner session-journal-banner" role="alert">
          <span className="session-journal-error-message">{error}</span>
          <button
            type="button"
            className="button secondary session-journal-retry-btn"
            onClick={onRetry}
          >
            {copy.retryButton}
          </button>
        </div>
      ) : null}

      {!accessUnavailable && selection !== null ? (
        <div className="session-journal-content">
          <section className="session-journal-group" aria-label={copy.journalPublicGroupHeading}>
            <div className="session-journal-group__header">
              <h3 className="session-journal-group__title">{copy.journalPublicGroupHeading}</h3>
            </div>
            {publicEntries.length === 0 ? (
              <p className="session-journal-empty session-journal-empty--public">
                {copy.journalEmptyPublic}
              </p>
            ) : (
              <div className="workshop-list session-journal-list">
                {publicEntries.map((entry) => (
                  <article
                    className="workshop-card session-journal-entry session-journal-entry--public"
                    key={entry.id}
                    data-entry-kind={entry.kind}
                    data-entry-visibility={entry.visibility}
                  >
                    <div className="session-journal-entry__header">
                      <span className={`session-journal-badge session-journal-badge--${entry.kind}`}>
                        {anyEntryKindLabel(entry.kind, copy)}
                      </span>
                    </div>
                    {entry.title ? (
                      <h4 className="session-journal-entry__title">{entry.title}</h4>
                    ) : null}
                    {entry.body ? (
                      <p className="session-journal-entry__body">{entry.body}</p>
                    ) : null}
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="session-journal-group" aria-label={copy.journalCharacterGroupHeading}>
            <div className="session-journal-group__header">
              <h3 className="session-journal-group__title">{copy.journalCharacterGroupHeading}</h3>
              {characterNames.length > 0 ? (
                <span className="session-journal-group__names">
                  {characterNames.join(', ')}
                </span>
              ) : null}
            </div>
            {!hasActiveCharacters ? (
              <p className="session-journal-empty session-journal-empty--no-character">
                {copy.journalNoActiveCharacter}
              </p>
            ) : characterEntries.length === 0 ? (
              <p className="session-journal-empty session-journal-empty--no-knowledge">
                {copy.journalEmptyCharacterKnowledge}
              </p>
            ) : (
              <div className="workshop-list session-journal-list">
                {characterEntries.map((entry) => (
                  <article
                    className="workshop-card session-journal-entry session-journal-entry--character"
                    key={entry.id}
                    data-entry-kind={entry.kind}
                    data-entry-visibility={entry.visibility}
                  >
                    <div className="session-journal-entry__header">
                      <span className={`session-journal-badge session-journal-badge--${entry.kind}`}>
                        {anyEntryKindLabel(entry.kind, copy)}
                      </span>
                      <span className="session-journal-badge session-journal-badge--character">
                        {copy.visibilityCharacter}
                      </span>
                    </div>
                    {entry.title ? (
                      <h4 className="session-journal-entry__title">{entry.title}</h4>
                    ) : null}
                    {entry.body ? (
                      <p className="session-journal-entry__body">{entry.body}</p>
                    ) : null}
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      ) : null}
    </section>
  )
}

export type SessionPlayerJournalProps = {
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  identity: PlayerJournalIdentity
  characters: RoomCharacterSummary[]
  worldEventCursor: number
  onError: (cause: unknown) => void
}

export function formatPlayerJournalCharacterNames(
  activeCharacterIds: readonly string[],
  characters: readonly RoomCharacterSummary[],
  fallback: string,
): string[] {
  return activeCharacterIds.map((charId) => {
    const summary = characters.find((character) => character.id === charId)
    return summary?.name ?? fallback
  })
}

export function SessionPlayerJournal({
  roomId,
  campaignId,
  sessionId,
  token,
  identity,
  characters,
  worldEventCursor,
  onError,
}: SessionPlayerJournalProps) {
  const { locale } = useLocale()
  const copy = campaignRuntimeCopy(locale)

  const hasActiveCharacters = identity.activeCharacterIds.length > 0

  const characterNames = useMemo(() => {
    return formatPlayerJournalCharacterNames(
      identity.activeCharacterIds,
      characters,
      copy.journalActiveCharacterFallback,
    )
  }, [identity.activeCharacterIds, characters, copy.journalActiveCharacterFallback])

  const state = useSessionPlayerJournal({
    roomId,
    campaignId,
    sessionId,
    token,
    allowCharacterKnowledge: hasActiveCharacters,
    worldEventCursor,
    copy,
    onError,
  })

  return (
    <SessionPlayerJournalView
      selection={state.selection}
      characterNames={characterNames}
      hasActiveCharacters={hasActiveCharacters}
      loading={state.loading}
      error={state.error}
      accessUnavailable={state.accessUnavailable}
      copy={copy}
      onRetry={state.retry}
    />
  )
}
