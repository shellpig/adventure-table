import { useCallback, useEffect, useRef, useState } from 'react'

import {
  listCampaignAdventures,
  type AttachedAdventure,
} from '../../api/adventures'
import {
  clearActiveRuntimeContext,
  createActiveRuntimeEntry,
  getActiveRuntimeContext,
  listActiveAdventureEntryOverlays,
  listActiveRuntimeEntries,
  updateActiveRuntimeContext,
  CampaignRuntimeApiError,
  type CampaignAdventureEntryOverlayView,
  type CampaignRuntimeContext,
  type RuntimeWorldEntryDmView,
  type RuntimeWorldEntryPlayerView,
  type UpdateCampaignRuntimeContextRequest,
} from '../../api/campaignRuntime'
import type { TableEvent } from '../../api/sessions'
import {
  campaignRuntimeErrorMessage,
  type CampaignRuntimeCopy,
} from './campaignRuntimeCopy'
import {
  buildCreateEntryRequest,
  createInitialEntryFormState,
  generateRuntimeIdempotencyKey,
  type CreateRuntimeEntryFormState,
  type RuntimeEntryFormState,
} from './campaignRuntimeForm'
import {
  buildUpdateContextRequest,
  contextToFormState,
  type ContextFormState,
} from './campaignRuntimeOverrideForm'

export const SESSION_QUICK_ADD_KINDS = ['scene', 'npc', 'fact'] as const

export type ActiveSessionRuntimeSnapshot = {
  entries: RuntimeWorldEntryDmView[]
  context: CampaignRuntimeContext
  attachedAdventures: AttachedAdventure[]
  overlays: CampaignAdventureEntryOverlayView[]
}

export class UnexpectedPlayerProjectionError extends Error {
  constructor(message = 'Received unexpected player projection for runtime entry') {
    super(message)
    this.name = 'UnexpectedPlayerProjectionError'
  }
}

export function isRuntimeWorldEntryDmView(
  entry: RuntimeWorldEntryDmView | RuntimeWorldEntryPlayerView,
): entry is RuntimeWorldEntryDmView {
  if (!('character_recipient_ids' in entry)) return false
  if (!('needs_review' in entry)) return false
  if (!('created_by_actor_kind' in entry)) return false
  if (!('archived_at' in entry)) return false
  return (
    Array.isArray(entry.character_recipient_ids) &&
    typeof entry.needs_review === 'boolean' &&
    typeof entry.created_by_actor_kind === 'string'
  )
}

export function isCampaignRuntimeAuthorityLossError(err: unknown): boolean {
  if (err instanceof CampaignRuntimeApiError) {
    return (
      err.code === 'campaign_runtime_forbidden' ||
      err.code === 'campaign_runtime_session_not_active'
    )
  }
  if (typeof err === 'object' && err !== null && 'code' in err) {
    return (
      err.code === 'campaign_runtime_forbidden' ||
      err.code === 'campaign_runtime_session_not_active'
    )
  }
  return false
}

export function isCampaignRuntimeRevisionConflictError(err: unknown): boolean {
  if (err instanceof CampaignRuntimeApiError) {
    return err.code === 'campaign_runtime_revision_conflict'
  }
  if (typeof err === 'object' && err !== null && 'code' in err) {
    return err.code === 'campaign_runtime_revision_conflict'
  }
  return false
}

export function deriveLatestWorldEventSeq(events: TableEvent[], currentSessionId: string): number {
  let maxSeq = 0
  for (const event of events) {
    if (
      event.session_id === currentSessionId &&
      event.kind.startsWith('world.') &&
      typeof event.seq === 'number' &&
      event.seq > maxSeq
    ) {
      maxSeq = event.seq
    }
  }
  return maxSeq
}

export function shouldShowWaitingBanner(
  cursorAtMutationStart: number,
  latestCursor: number,
): boolean {
  return latestCursor <= cursorAtMutationStart
}

export class LoadCoordinator {
  private currentGeneration = 0

  nextGeneration(): number {
    this.currentGeneration += 1
    return this.currentGeneration
  }

  isCurrent(generation: number): boolean {
    return generation === this.currentGeneration
  }

  invalidate(): void {
    this.currentGeneration += 1
  }

  get generation(): number {
    return this.currentGeneration
  }
}

export async function loadActiveSessionRuntime(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
): Promise<ActiveSessionRuntimeSnapshot> {
  const [entriesRaw, context, attachedAdventures] = await Promise.all([
    listActiveRuntimeEntries(roomId, campaignId, sessionId, token),
    getActiveRuntimeContext(roomId, campaignId, sessionId, token),
    listCampaignAdventures(roomId, campaignId, token),
  ])

  const entries: RuntimeWorldEntryDmView[] = []
  for (const entry of entriesRaw) {
    if (!isRuntimeWorldEntryDmView(entry)) {
      throw new UnexpectedPlayerProjectionError()
    }
    entries.push(entry)
  }

  let overlays: CampaignAdventureEntryOverlayView[] = []
  if (attachedAdventures.length > 0) {
    const sortedAdventures = [...attachedAdventures].sort(
      (a, b) => a.sort_order - b.sort_order || a.adventure_id.localeCompare(b.adventure_id),
    )
    const overlayLists = await Promise.all(
      sortedAdventures.map((adv) =>
        listActiveAdventureEntryOverlays(roomId, campaignId, sessionId, adv.adventure_id, token),
      ),
    )
    overlays = overlayLists.flat()
  }

  return {
    entries,
    context,
    attachedAdventures,
    overlays,
  }
}

export type ExecuteActiveSessionMutationOptions<T> = {
  action: () => Promise<T>
  onSuccess: (result: T) => void
  onError: (errorMessage: string) => void
  onAuthorityLoss?: (errorMessage: string) => void
  onConflictReload?: () => Promise<ActiveSessionRuntimeSnapshot>
  onConflictSuccess?: (freshSnapshot: ActiveSessionRuntimeSnapshot) => void
  onConflictReloadError?: (errorMessage: string) => void
  copy: CampaignRuntimeCopy
}

export async function executeActiveSessionMutation<T>({
  action,
  onSuccess,
  onError,
  onAuthorityLoss,
  onConflictReload,
  onConflictSuccess,
  onConflictReloadError,
  copy,
}: ExecuteActiveSessionMutationOptions<T>): Promise<boolean> {
  let result: T
  try {
    result = await action()
  } catch (err) {
    if (isCampaignRuntimeAuthorityLossError(err)) {
      const message = campaignRuntimeErrorMessage(err, copy)
      onAuthorityLoss?.(message)
      return false
    }

    const isConflict = isCampaignRuntimeRevisionConflictError(err)

    if (isConflict && onConflictReload) {
      try {
        const freshSnapshot = await onConflictReload()
        onConflictSuccess?.(freshSnapshot)
        return false
      } catch (reloadErr) {
        if (isCampaignRuntimeAuthorityLossError(reloadErr)) {
          const message = campaignRuntimeErrorMessage(reloadErr, copy)
          onAuthorityLoss?.(message)
          return false
        }
        if (reloadErr instanceof UnexpectedPlayerProjectionError) {
          onAuthorityLoss?.(copy.unexpectedProjectionError)
          return false
        }
        const reloadMessage = copy.eventRefreshError
        onConflictReloadError?.(reloadMessage)
        return false
      }
    }

    const message = campaignRuntimeErrorMessage(err, copy)
    onError(message)
    return false
  }

  onSuccess(result)
  return true
}

export type SessionCampaignRuntimeActions = {
  pending: boolean
  quickAddOpen: boolean
  quickAddForm: CreateRuntimeEntryFormState | null
  quickAddError: string | null
  onOpenQuickAdd: () => void
  onCloseQuickAdd: () => void
  onChangeQuickAdd: (updater: (prev: RuntimeEntryFormState) => RuntimeEntryFormState) => void
  onSubmitQuickAdd: (e: React.FormEvent) => void
  contextForm: ContextFormState | null
  contextError: string | null
  onOpenContextEdit: () => void
  onCancelContextEdit: () => void
  onChangeContextForm: (updater: (prev: ContextFormState) => ContextFormState) => void
  onSubmitContextForm: (e: React.FormEvent) => void
  onClearContext: () => void
}

export type UseSessionCampaignRuntimeOptions = {
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  worldEventCursor: number
  copy: CampaignRuntimeCopy
  onError: (message: string) => void
}

export type UseSessionCampaignRuntimeResult = {
  snapshot: ActiveSessionRuntimeSnapshot | null
  loading: boolean
  error: string | null
  refreshStatus: string | null
  actions: SessionCampaignRuntimeActions | null
  onRetry: () => void
}

export function useSessionCampaignRuntime({
  roomId,
  campaignId,
  sessionId,
  token,
  worldEventCursor,
  copy,
  onError,
}: UseSessionCampaignRuntimeOptions): UseSessionCampaignRuntimeResult {
  const [snapshot, setSnapshot] = useState<ActiveSessionRuntimeSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshStatus, setRefreshStatus] = useState<string | null>(null)
  const [authorityLost, setAuthorityLost] = useState(false)

  const [quickAddOpen, setQuickAddOpen] = useState(false)
  const [quickAddForm, setQuickAddForm] = useState<CreateRuntimeEntryFormState | null>(null)
  const [quickAddError, setQuickAddError] = useState<string | null>(null)
  const [quickAddPending, setQuickAddPending] = useState(false)

  const [contextForm, setContextForm] = useState<ContextFormState | null>(null)
  const [contextError, setContextError] = useState<string | null>(null)
  const [contextPending, setContextPending] = useState(false)

  const loadCoordinatorRef = useRef(new LoadCoordinator())
  const latestWorldCursorRef = useRef(worldEventCursor)
  latestWorldCursorRef.current = worldEventCursor

  const handleAuthorityLoss = useCallback(
    (message: string) => {
      loadCoordinatorRef.current.invalidate()
      setLoading(false)
      setSnapshot(null)
      setAuthorityLost(true)
      setQuickAddOpen(false)
      setQuickAddForm(null)
      setQuickAddError(null)
      setQuickAddPending(false)
      setContextForm(null)
      setContextError(null)
      setContextPending(false)
      setRefreshStatus(null)
      setError(message)
      onError(message)
    },
    [onError],
  )

  const performLoad = useCallback(
    async (isEventRefresh = false): Promise<ActiveSessionRuntimeSnapshot | null> => {
      const gen = loadCoordinatorRef.current.nextGeneration()
      try {
        const fresh = await loadActiveSessionRuntime(roomId, campaignId, sessionId, token)
        if (!loadCoordinatorRef.current.isCurrent(gen)) {
          return null
        }
        setSnapshot(fresh)
        setAuthorityLost(false)
        setError(null)
        setRefreshStatus(null)
        return fresh
      } catch (err) {
        if (!loadCoordinatorRef.current.isCurrent(gen)) {
          return null
        }
        if (err instanceof UnexpectedPlayerProjectionError) {
          handleAuthorityLoss(copy.unexpectedProjectionError)
          return null
        }
        if (isCampaignRuntimeAuthorityLossError(err)) {
          handleAuthorityLoss(campaignRuntimeErrorMessage(err, copy))
          return null
        }
        const defaultMsg = isEventRefresh ? copy.eventRefreshError : copy.loadError
        const mapped = campaignRuntimeErrorMessage(err, copy)
        const displayError = mapped !== copy.requestFailed ? mapped : defaultMsg
        setError(displayError)
        onError(displayError)
        return null
      } finally {
        if (loadCoordinatorRef.current.isCurrent(gen)) {
          setLoading(false)
        }
      }
    },
    [roomId, campaignId, sessionId, token, copy, onError, handleAuthorityLoss],
  )

  const reloadForConflict = useCallback(async (): Promise<ActiveSessionRuntimeSnapshot> => {
    const gen = loadCoordinatorRef.current.nextGeneration()
    const fresh = await loadActiveSessionRuntime(roomId, campaignId, sessionId, token)
    if (!loadCoordinatorRef.current.isCurrent(gen)) {
      throw new Error('stale_generation')
    }
    return fresh
  }, [roomId, campaignId, sessionId, token])

  const seenCursorRef = useRef<number | null>(null)
  const isInitialMount = useRef(true)

  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false
      seenCursorRef.current = worldEventCursor
      void performLoad(false)
      return
    }

    if (seenCursorRef.current !== null && worldEventCursor > seenCursorRef.current) {
      seenCursorRef.current = worldEventCursor
      void performLoad(true)
    }
  }, [worldEventCursor, performLoad])

  const onOpenQuickAdd = useCallback(() => {
    setQuickAddForm(createInitialEntryFormState('scene'))
    setQuickAddOpen(true)
    setQuickAddError(null)
  }, [])

  const onCloseQuickAdd = useCallback(() => {
    setQuickAddOpen(false)
    setQuickAddForm(null)
    setQuickAddError(null)
  }, [])

  const onChangeQuickAdd = useCallback(
    (updater: (prev: RuntimeEntryFormState) => RuntimeEntryFormState) => {
      setQuickAddForm((prev) => {
        if (!prev) return null
        const next = updater(prev)
        return next.mode === 'create' ? next : prev
      })
    },
    [],
  )

  const onSubmitQuickAdd = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      if (!quickAddForm) return
      const idempotencyKey = generateRuntimeIdempotencyKey('session-quick-add')
      const validation = buildCreateEntryRequest(quickAddForm, idempotencyKey)
      if (!validation.ok) {
        const errMsg = copy[validation.errorKey]
        setQuickAddError(errMsg)
        return
      }

      setQuickAddPending(true)
      setQuickAddError(null)
      const startCursor = latestWorldCursorRef.current

      try {
        await executeActiveSessionMutation({
          action: () =>
            createActiveRuntimeEntry(
              roomId,
              campaignId,
              sessionId,
              token,
              validation.value,
            ),
          onSuccess: () => {
            setQuickAddOpen(false)
            setQuickAddForm(null)
            setError(null)
            if (shouldShowWaitingBanner(startCursor, latestWorldCursorRef.current)) {
              setRefreshStatus(copy.refreshingFromEvents)
            }
          },
          onError: (msg) => setQuickAddError(msg),
          onAuthorityLoss: handleAuthorityLoss,
          copy,
        })
      } finally {
        setQuickAddPending(false)
      }
    },
    [quickAddForm, roomId, campaignId, sessionId, token, copy, handleAuthorityLoss],
  )

  const onOpenContextEdit = useCallback(() => {
    if (!snapshot) return
    setContextForm(contextToFormState(snapshot.context))
    setContextError(null)
  }, [snapshot])

  const onCancelContextEdit = useCallback(() => {
    setContextForm(null)
    setContextError(null)
  }, [])

  const onChangeContextForm = useCallback(
    (updater: (prev: ContextFormState) => ContextFormState) => {
      setContextForm((prev) => (prev ? updater(prev) : prev))
    },
    [],
  )

  const onSubmitContextForm = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      if (!contextForm || !snapshot) return
      const idempotencyKey = generateRuntimeIdempotencyKey('session-runtime-context')
      const req: UpdateCampaignRuntimeContextRequest = buildUpdateContextRequest(
        contextForm,
        idempotencyKey,
      )

      setContextPending(true)
      setContextError(null)
      const startCursor = latestWorldCursorRef.current

      try {
        await executeActiveSessionMutation({
          action: () => updateActiveRuntimeContext(roomId, campaignId, sessionId, token, req),
          onSuccess: () => {
            setContextForm(null)
            setError(null)
            if (shouldShowWaitingBanner(startCursor, latestWorldCursorRef.current)) {
              setRefreshStatus(copy.refreshingFromEvents)
            }
          },
          onConflictReload: reloadForConflict,
          onConflictSuccess: (fresh) => {
            setSnapshot(fresh)
            setContextForm(null)
            setRefreshStatus(null)
            setError(copy.errCampaignRuntimeRevisionConflict)
          },
          onConflictReloadError: (msg) => setContextError(msg),
          onError: (msg) => setContextError(msg),
          onAuthorityLoss: handleAuthorityLoss,
          copy,
        })
      } finally {
        setContextPending(false)
      }
    },
    [contextForm, snapshot, roomId, campaignId, sessionId, token, copy, reloadForConflict, handleAuthorityLoss],
  )

  const onClearContext = useCallback(async () => {
    if (!snapshot) return
    if (typeof window !== 'undefined' && !window.confirm(copy.confirmClearContext)) {
      return
    }

    setContextPending(true)
    const idempotencyKey = generateRuntimeIdempotencyKey('session-clear-context')
    const startCursor = latestWorldCursorRef.current

    try {
      await executeActiveSessionMutation({
        action: () =>
          clearActiveRuntimeContext(roomId, campaignId, sessionId, token, {
            expected_revision: snapshot.context.revision,
            idempotency_key: idempotencyKey,
          }),
        onSuccess: () => {
          setError(null)
          if (shouldShowWaitingBanner(startCursor, latestWorldCursorRef.current)) {
            setRefreshStatus(copy.refreshingFromEvents)
          }
        },
        onConflictReload: reloadForConflict,
        onConflictSuccess: (fresh) => {
          setSnapshot(fresh)
          setContextForm(null)
          setRefreshStatus(null)
          setError(copy.errCampaignRuntimeRevisionConflict)
        },
        onConflictReloadError: (msg) => setError(msg),
        onError: (msg) => setError(msg),
        onAuthorityLoss: handleAuthorityLoss,
        copy,
      })
    } finally {
      setContextPending(false)
    }
  }, [snapshot, roomId, campaignId, sessionId, token, copy, reloadForConflict, handleAuthorityLoss])

  const onRetry = useCallback(() => {
    setLoading(true)
    void performLoad(false)
  }, [performLoad])

  const pending = quickAddPending || contextPending

  const actions: SessionCampaignRuntimeActions | null = authorityLost
    ? null
    : {
        pending,
        quickAddOpen,
        quickAddForm,
        quickAddError,
        onOpenQuickAdd,
        onCloseQuickAdd,
        onChangeQuickAdd,
        onSubmitQuickAdd,
        contextForm,
        contextError,
        onOpenContextEdit,
        onCancelContextEdit,
        onChangeContextForm,
        onSubmitContextForm,
        onClearContext,
      }

  return {
    snapshot,
    loading,
    error,
    refreshStatus,
    actions,
    onRetry,
  }
}
