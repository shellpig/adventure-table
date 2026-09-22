import { useCallback, useEffect, useRef, useState } from 'react'

import {
  listAdventureEntries,
  listCampaignAdventures,
  type AdventureEntry,
  type AttachedAdventure,
} from '../../api/adventures'
import {
  clearActiveRuntimeContext,
  createActiveRuntimeEntry,
  getActiveRuntimeContext,
  listActiveAdventureEntryOverlays,
  listActiveRuntimeEntries,
  updateActiveOverride,
  updateActiveRuntimeContext,
  updateActiveRuntimeEntry,
  CampaignRuntimeApiError,
  type CampaignAdventureEntryOverlayView,
  type CampaignRuntimeContext,
  type RuntimeWorldEntryDmView,
  type RuntimeWorldEntryPlayerView,
  type UpdateCampaignRuntimeContextRequest,
} from '../../api/campaignRuntime'
import {
  listRoomAssets,
  type RoomAsset,
} from '../../api/roomAssets'
import {
  getSessionStage,
  setSessionStageImageSource,
  type StageImageSource,
  type TableEvent,
} from '../../api/sessions'
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
      err.code === 'campaign_runtime_session_not_active' ||
      err.code === 'table_actor_unauthorized' ||
      err.code === 'session_not_active'
    )
  }
  return false
}

export function isCampaignRuntimeRevisionConflictError(err: unknown): boolean {
  if (err instanceof CampaignRuntimeApiError) {
    return err.code === 'campaign_runtime_revision_conflict'
  }
  if (typeof err === 'object' && err !== null && 'code' in err) {
    return (
      err.code === 'campaign_runtime_revision_conflict' ||
      err.code === 'stage_revision_conflict'
    )
  }
  return false
}

export type StageCandidate = {
  key: string
  label: string
  group: 'adventure' | 'runtime' | 'room'
  source: StageImageSource
}

export function buildStageCandidates(
  attachedAdventures: AttachedAdventure[],
  adventureEntriesByAdventureId: Record<string, AdventureEntry[]>,
  runtimeEntries: RuntimeWorldEntryDmView[],
  roomAssets: RoomAsset[],
  unnamedLabel = '(Unnamed)',
): {
  adventureCandidates: StageCandidate[]
  runtimeCandidates: StageCandidate[]
  roomCandidates: StageCandidate[]
  allCandidates: StageCandidate[]
} {
  const adventureCandidates: StageCandidate[] = []
  const runtimeCandidates: StageCandidate[] = []
  const roomCandidates: StageCandidate[] = []
  let counter = 0

  for (const adv of attachedAdventures) {
    const entries = adventureEntriesByAdventureId[adv.adventure_id] ?? []
    for (const entry of entries) {
      for (const entryAsset of entry.assets) {
        if (entryAsset.role !== 'image' && entryAsset.role !== 'map') continue
        const title = entry.title || unnamedLabel
        counter += 1
        adventureCandidates.push({
          key: `candidate-adv-${counter}`,
          label: `${title} — ${entryAsset.asset.original_filename}`,
          group: 'adventure',
          source: {
            kind: 'adventure_entry_asset',
            adventure_id: adv.adventure_id,
            adventure_entry_id: entry.id,
            asset_id: entryAsset.asset.id,
          },
        })
      }
    }
  }

  const loadedEntriesById = new Map<string, { advEntry: AdventureEntry; adventureId: string }>()
  for (const adv of attachedAdventures) {
    const entries = adventureEntriesByAdventureId[adv.adventure_id] ?? []
    for (const entry of entries) {
      loadedEntriesById.set(entry.id, { advEntry: entry, adventureId: adv.adventure_id })
    }
  }

  for (const rtEntry of runtimeEntries) {
    if (rtEntry.archived_at || !rtEntry.source_adventure_entry_id) continue
    const matched = loadedEntriesById.get(rtEntry.source_adventure_entry_id)
    if (!matched) continue
    const { advEntry, adventureId } = matched
    for (const entryAsset of advEntry.assets) {
      if (entryAsset.role !== 'image' && entryAsset.role !== 'map') continue
      const title = rtEntry.title || unnamedLabel
      counter += 1
      runtimeCandidates.push({
        key: `candidate-rt-${counter}`,
        label: `${title} — ${entryAsset.asset.original_filename}`,
        group: 'runtime',
        source: {
          kind: 'runtime_entry_image',
          runtime_entry_id: rtEntry.id,
          adventure_id: adventureId,
          asset_id: entryAsset.asset.id,
        },
      })
    }
  }

  for (const asset of roomAssets) {
    if (asset.kind !== 'image') continue
    counter += 1
    roomCandidates.push({
      key: `candidate-room-${counter}`,
      label: asset.original_filename,
      group: 'room',
      source: {
        kind: 'room_asset',
        asset_id: asset.id,
      },
    })
  }

  return {
    adventureCandidates,
    runtimeCandidates,
    roomCandidates,
    allCandidates: [...adventureCandidates, ...runtimeCandidates, ...roomCandidates],
  }
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
  stagePickerOpen: boolean
  stagePickerLoading: boolean
  stagePickerError: string | null
  stageSuccess: string | null
  stageCandidates: StageCandidate[] | null
  stageSelectedKey: string | null
  onOpenStagePicker: () => void
  onCloseStagePicker: () => void
  onSelectStageCandidate: (key: string) => void
  onSubmitStageImage: () => Promise<void>
  onToggleEntryNeedsReview: (entry: RuntimeWorldEntryDmView) => Promise<void>
  onToggleOverrideNeedsReview: (overlay: CampaignAdventureEntryOverlayView) => Promise<void>
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

  const [stagePickerOpen, setStagePickerOpen] = useState(false)
  const [stagePickerLoading, setStagePickerLoading] = useState(false)
  const [stagePickerError, setStagePickerError] = useState<string | null>(null)
  const [stageSuccess, setStageSuccess] = useState<string | null>(null)
  const [stageCandidates, setStageCandidates] = useState<StageCandidate[] | null>(null)
  const [stageSelectedKey, setStageSelectedKey] = useState<string | null>(null)
  const [stagePending, setStagePending] = useState(false)
  const [reviewPending, setReviewPending] = useState(false)

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
      setStagePickerOpen(false)
      setStagePickerLoading(false)
      setStagePickerError(null)
      setStageSuccess(null)
      setStagePending(false)
      setReviewPending(false)
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

  const onOpenStagePicker = useCallback(async () => {
    setStagePickerOpen(true)
    setStagePickerError(null)
    setStageSuccess(null)
    if (stageCandidates !== null) {
      return
    }
    if (!snapshot) return
    setStagePickerLoading(true)
    try {
      const advPromises = snapshot.attachedAdventures.map((adv) =>
        listAdventureEntries(roomId, adv.adventure_id, token).then((entries) => ({
          adventureId: adv.adventure_id,
          entries,
        })),
      )
      const [advResults, roomAssets] = await Promise.all([
        Promise.all(advPromises),
        listRoomAssets(roomId, token, 'image'),
      ])
      const entriesMap: Record<string, AdventureEntry[]> = {}
      for (const res of advResults) {
        entriesMap[res.adventureId] = res.entries
      }
      const built = buildStageCandidates(
        snapshot.attachedAdventures,
        entriesMap,
        snapshot.entries,
        roomAssets,
        copy.unnamedEntry,
      )
      setStageCandidates(built.allCandidates)
      if (built.allCandidates.length > 0) {
        setStageSelectedKey(built.allCandidates[0].key)
      }
    } catch (err) {
      setStagePickerError(campaignRuntimeErrorMessage(err, copy))
    } finally {
      setStagePickerLoading(false)
    }
  }, [snapshot, roomId, token, stageCandidates, copy])

  const onCloseStagePicker = useCallback(() => {
    setStagePickerOpen(false)
    setStagePickerError(null)
  }, [])

  const onSelectStageCandidate = useCallback((key: string) => {
    setStageSelectedKey(key)
  }, [])

  const onSubmitStageImage = useCallback(async () => {
    if (!stageCandidates || !stageSelectedKey || !snapshot) return
    const selected = stageCandidates.find((c) => c.key === stageSelectedKey)
    if (!selected) return

    setStagePending(true)
    setStagePickerError(null)
    setStageSuccess(null)

    try {
      await executeActiveSessionMutation({
        action: async () => {
          const stageState = await getSessionStage(roomId, campaignId, sessionId, token)
          const idempotencyKey = generateRuntimeIdempotencyKey('session-stage-image')
          return setSessionStageImageSource(
            roomId,
            campaignId,
            sessionId,
            {
              source: selected.source,
              expected_revision: stageState.revision,
              idempotency_key: idempotencyKey,
            },
            token,
          )
        },
        onSuccess: () => {
          setStagePickerOpen(false)
          setStagePickerError(null)
          setStageSuccess(copy.stageImageSuccess)
        },
        onError: (msg) => {
          setStagePickerError(msg)
        },
        onAuthorityLoss: handleAuthorityLoss,
        copy,
      })
    } finally {
      setStagePending(false)
    }
  }, [stageCandidates, stageSelectedKey, snapshot, roomId, campaignId, sessionId, token, copy, handleAuthorityLoss])

  const toggleNeedsReview = useCallback(
    async (action: (idempotencyKey: string) => Promise<unknown>) => {
      setReviewPending(true)
      setError(null)
      const idempotencyKey = generateRuntimeIdempotencyKey('session-toggle-review')
      const startCursor = latestWorldCursorRef.current

      try {
        await executeActiveSessionMutation({
          action: () => action(idempotencyKey),
          onSuccess: () => {
            setError(null)
            if (shouldShowWaitingBanner(startCursor, latestWorldCursorRef.current)) {
              setRefreshStatus(copy.refreshingFromEvents)
            }
          },
          onConflictReload: reloadForConflict,
          onConflictSuccess: (fresh) => {
            setSnapshot(fresh)
            setRefreshStatus(null)
            setError(copy.errCampaignRuntimeRevisionConflict)
          },
          onConflictReloadError: (msg) => setError(msg),
          onError: (msg) => setError(msg),
          onAuthorityLoss: handleAuthorityLoss,
          copy,
        })
      } finally {
        setReviewPending(false)
      }
    },
    [copy, reloadForConflict, handleAuthorityLoss],
  )

  const onToggleEntryNeedsReview = useCallback(
    (entry: RuntimeWorldEntryDmView) =>
      toggleNeedsReview((idempotencyKey) =>
        updateActiveRuntimeEntry(roomId, campaignId, sessionId, entry.id, token, {
          idempotency_key: idempotencyKey,
          expected_revision: entry.revision,
          needs_review: !entry.needs_review,
        }),
      ),
    [toggleNeedsReview, roomId, campaignId, sessionId, token],
  )

  const onToggleOverrideNeedsReview = useCallback(
    async (overlay: CampaignAdventureEntryOverlayView) => {
      const override = overlay.override
      if (!override) return
      await toggleNeedsReview((idempotencyKey) =>
        updateActiveOverride(roomId, campaignId, sessionId, overlay.id, token, {
          idempotency_key: idempotencyKey,
          expected_override_id: override.id,
          expected_revision: override.revision,
          needs_review: !override.needs_review,
        }),
      )
    },
    [toggleNeedsReview, roomId, campaignId, sessionId, token],
  )

  const onRetry = useCallback(() => {
    setLoading(true)
    void performLoad(false)
  }, [performLoad])

  const pending = quickAddPending || contextPending || stagePending || reviewPending

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
        stagePickerOpen,
        stagePickerLoading,
        stagePickerError,
        stageSuccess,
        stageCandidates,
        stageSelectedKey,
        onOpenStagePicker,
        onCloseStagePicker,
        onSelectStageCandidate,
        onSubmitStageImage,
        onToggleEntryNeedsReview,
        onToggleOverrideNeedsReview,
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
