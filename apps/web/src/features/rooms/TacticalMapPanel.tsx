import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { getBattleMap, type BattleMap } from '../../api/battleMaps'
import type { CombatDetailView } from '../../api/combat'
import type { TableEvent } from '../../api/sessions'
import {
  cancelPendingMovement,
  checkTarget,
  confirmMovement,
  getCombatBoard,
  placeCombatant,
  previewAoeSpell,
  previewMovement,
  repositionCombatant,
  resumeMovement,
  updateBoardDoorState,
  type AoeSpellPreviewView,
  type BoardDoorView,
  type CombatBoardView,
  type ConfirmMovementView,
  type PreviewMovementView,
  type TargetCheckResult,
} from '../../api/tacticalCombat'
import { BattleMapCanvas } from './BattleMapCanvas'
import type { CanvasDoor, CanvasToken, CanvasWall } from './BattleMapCanvas'
import { requestId } from './requestId'
import type { SessionCopy } from './sessionCopy'
import { combatantFor, isCombatEvent } from './sessionCombat'
import { useTacticalCamera } from './useTacticalCamera'

type TacticalMapPanelProps = {
  combat: CombatDetailView
  copy: SessionCopy
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  isCurrentDm: boolean
  myEntryIds: string[]
  events: TableEvent[]
  onError: (cause: unknown) => void
  refresh: () => void
}

export function doorIsHidden(boardDoor: BoardDoorView, battleMap: BattleMap | null): boolean {
  // Prefer server-provided hidden_origin when available (DM projection).
  if (typeof boardDoor.hidden_origin === 'boolean') return boardDoor.hidden_origin
  // Fallback: correlate with the battle map definition (DM only).
  if (!battleMap || !boardDoor.door_id) return false
  const def = battleMap.doors.find((d) => d.id === boardDoor.door_id)
  return def?.visibility === 'hidden'
}

const BOARD_RELOAD_DEBOUNCE_MS = 500

export function TacticalMapPanel({
  combat,
  copy,
  roomId,
  campaignId,
  sessionId,
  token,
  isCurrentDm,
  myEntryIds,
  events,
  onError,
  refresh,
}: TacticalMapPanelProps) {
  const [board, setBoard] = useState<CombatBoardView | null>(null)
  const [battleMap, setBattleMap] = useState<BattleMap | null>(null)
  const [boardError, setBoardError] = useState(false)
  const [imageObjectUrl, setImageObjectUrl] = useState<string | null>(null)
  const [selectedEntryId, setSelectedEntryId] = useState<string | null>(null)
  const [selectedDoorId, setSelectedDoorId] = useState<string | null>(null)
  const [placingEntryId, setPlacingEntryId] = useState<string | null>(null)
  const [placing, setPlacing] = useState(false)
  const [doorPending, setDoorPending] = useState(false)
  // Movement draft (client-only until Confirm).
  const [moveEntryId, setMoveEntryId] = useState<string | null>(null)
  const [moveAnchors, setMoveAnchors] = useState<Array<{ x: number; y: number }>>([])
  const [movePreview, setMovePreview] = useState<PreviewMovementView | null>(null)
  const [moveBusy, setMoveBusy] = useState(false)
  const [lastMoveOutcome, setLastMoveOutcome] = useState<ConfirmMovementView | null>(null)
  // Pending (paused) movement from confirm outcome.
  const [pausedMove, setPausedMove] = useState<{
    entryId: string
    pendingRevision: number
  } | null>(null)
  const [cancelReason, setCancelReason] = useState('')
  // DM reposition mode (distinct from gameplay movement).
  const [repositionMode, setRepositionMode] = useState(false)
  const [repositionEntryId, setRepositionEntryId] = useState<string | null>(null)
  const [repositionReason, setRepositionReason] = useState('')
  const [repositionTarget, setRepositionTarget] = useState<{ x: number; y: number } | null>(null)
  // AoE preview.
  const [aoePreview, setAoePreview] = useState<AoeSpellPreviewView | null>(null)
  const [aoeOrigin, setAoeOrigin] = useState<{ x: number; y: number } | null>(null)
  // Range feedback for the currently selected target.
  const [targetCheck, setTargetCheck] = useState<TargetCheckResult | null>(null)
  const boardWrapRef = useRef<HTMLDivElement | null>(null)
  const reloadTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const {
    camera,
    zoomIn,
    zoomOut,
    handleWheel,
    startPan,
    panBy,
    endPan,
    startPinch,
    pinchBy,
    endPinch,
    fitMap,
    centerOn,
  } = useTacticalCamera()

  const loadBoard = useCallback(async () => {
    try {
      const view = await getCombatBoard(roomId, campaignId, sessionId, token)
      setBoard(view)
      setBoardError(false)
      // DM loads the source battle map definition for hidden door correlation.
      if (isCurrentDm && view.source_battle_map_id) {
        try {
          const map = await getBattleMap(roomId, view.source_battle_map_id, token)
          setBattleMap(map)
        } catch {
          setBattleMap(null)
        }
      }
    } catch (cause) {
      setBoardError(true)
      onError(cause)
    }
  }, [roomId, campaignId, sessionId, token, isCurrentDm, onError])

  // Initial load and reload on combat revision change.
  useEffect(() => {
    void loadBoard()
  }, [loadBoard, combat.revision])

  // Reload on table events for this combat (placement, door, movement may not
  // bump combat.revision). Debounced to avoid storms.
  const lastEventSeqRef = useRef<number>(-1)
  useEffect(() => {
    const unseen = events.filter(
      (e) => e.seq > lastEventSeqRef.current,
    )
    if (unseen.length === 0) return
    lastEventSeqRef.current = Math.max(...unseen.map((e) => e.seq))
    if (!unseen.some(isCombatEvent)) return
    if (reloadTimerRef.current) clearTimeout(reloadTimerRef.current)
    reloadTimerRef.current = setTimeout(() => {
      void loadBoard()
    }, BOARD_RELOAD_DEBOUNCE_MS)
    return () => {
      if (reloadTimerRef.current) clearTimeout(reloadTimerRef.current)
    }
  }, [events, loadBoard])

  // Load board image as blob with auth token (the image route requires auth).
  useEffect(() => {
    if (!board?.has_image) {
      setImageObjectUrl(null)
      return
    }
    let cancelled = false
    let objectUrl: string | null = null
    const load = async () => {
      try {
        const url = `/api/rooms/${roomId}/campaigns/${campaignId}/sessions/${sessionId}/combat/board/image`
        const resp = await fetch(url, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!resp.ok) throw new Error(`image fetch failed: ${resp.status}`)
        const blob = await resp.blob()
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setImageObjectUrl(objectUrl)
      } catch (cause) {
        if (!cancelled) onError(cause)
      }
    }
    void load()
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
      setImageObjectUrl(null)
    }
  }, [board?.has_image, roomId, campaignId, sessionId, token, onError])

  const placedEntryIds = useMemo(
    () => new Set((board?.positions ?? []).map((p) => p.entry_id)),
    [board],
  )
  const unplacedEntries = useMemo(
    () =>
      combat.entries.filter((e) => !placedEntryIds.has(e.id) && e.status === 'active'),
    [combat.entries, placedEntryIds],
  )

  const canvasWalls: CanvasWall[] = useMemo(
    () =>
      (board?.walls ?? []).map((w) => ({
        x1: w.x1,
        y1: w.y1,
        x2: w.x2,
        y2: w.y2,
        visibility: w.visibility,
      })),
    [board],
  )

  const canvasDoors: CanvasDoor[] = useMemo(
    () =>
      (board?.doors ?? []).map((d) => ({
        door_id: d.door_id,
        x1: d.x1,
        y1: d.y1,
        x2: d.x2,
        y2: d.y2,
        state: d.state,
        revealed: d.revealed,
        isHidden: isCurrentDm ? doorIsHidden(d, battleMap) : false,
      })),
    [board, battleMap, isCurrentDm],
  )

  const canvasTokens: CanvasToken[] = useMemo(
    () =>
      (board?.positions ?? []).map((p) => {
        const entry = combat.entries.find((e) => e.id === p.entry_id)
        const combatant = combatantFor(combat, p.entry_id)
        const name = combatant?.projection.name || entry?.display_name || ''
        return {
          entry_id: p.entry_id,
          name,
          anchor_x: p.anchor_x,
          anchor_y: p.anchor_y,
          footprint_width: p.footprint_width,
          footprint_height: p.footprint_height,
        }
      }),
    [board, combat],
  )

  const getViewportSize = useCallback((): { width: number; height: number } => {
    const el = boardWrapRef.current
    if (el) {
      const rect = el.getBoundingClientRect()
      if (rect.width > 0 && rect.height > 0) {
        return { width: rect.width, height: rect.height }
      }
    }
    return { width: 800, height: 600 }
  }, [])

  const handleFitMap = useCallback(() => {
    if (!board) return
    const { width, height } = getViewportSize()
    fitMap(board.width_cells * 40, board.height_cells * 40, width, height)
  }, [board, fitMap, getViewportSize])

  const handleCenterParty = useCallback(() => {
    if (!board || board.positions.length === 0) return
    const xs = board.positions.map((p) => p.anchor_x)
    const ys = board.positions.map((p) => p.anchor_y)
    const cx = (Math.min(...xs) + Math.max(...xs) + 1) / 2
    const cy = (Math.min(...ys) + Math.max(...ys) + 1) / 2
    const { width, height } = getViewportSize()
    centerOn(cx * 40, cy * 40, width, height)
  }, [board, centerOn, getViewportSize])

  const handleCellClick = useCallback(
    async (x: number, y: number) => {
      if (!isCurrentDm || !placingEntryId || placing) return
      setPlacing(true)
      try {
        await placeCombatant(
          roomId,
          campaignId,
          sessionId,
          placingEntryId,
          { anchor_x: x, anchor_y: y, idempotency_key: requestId('place') },
          token,
        )
        setPlacingEntryId(null)
        await loadBoard()
        refresh()
      } catch (cause) {
        onError(cause)
      } finally {
        setPlacing(false)
      }
    },
    [isCurrentDm, placingEntryId, placing, roomId, campaignId, sessionId, token, loadBoard, refresh, onError],
  )

  const handleDoorClick = useCallback(
    (doorId: string | null) => {
      // Only DM can operate doors; Player clicks do nothing.
      if (!isCurrentDm || !doorId) return
      setSelectedDoorId((prev) => (prev === doorId ? null : doorId))
    },
    [isCurrentDm],
  )

  const handleDoorStateChange = useCallback(
    async (state: 'open' | 'closed' | 'locked' | 'broken', revealed: boolean) => {
      if (!isCurrentDm || !selectedDoorId || !board || doorPending) return
      setDoorPending(true)
      try {
        await updateBoardDoorState(
          roomId,
          campaignId,
          sessionId,
          selectedDoorId,
          {
            state,
            revealed,
            expected_runtime_revision: board.runtime_revision,
            idempotency_key: requestId('door'),
          },
          token,
        )
        await loadBoard()
        refresh()
      } catch (cause) {
        onError(cause)
      } finally {
        setDoorPending(false)
      }
    },
    [isCurrentDm, selectedDoorId, board, doorPending, roomId, campaignId, sessionId, token, loadBoard, refresh, onError],
  )

  const selectedDoor = useMemo(
    () => (board?.doors ?? []).find((d) => d.door_id === selectedDoorId) ?? null,
    [board, selectedDoorId],
  )

  // --- Movement draft (P5-F F3) ---
  // The user can only move their own tokens (or DM can move any as proxy).
  const canMoveEntry = useCallback(
    (entryId: string) => isCurrentDm || myEntryIds.includes(entryId),
    [isCurrentDm, myEntryIds],
  )

  const startMoveDraft = useCallback(
    (entryId: string) => {
      if (!canMoveEntry(entryId) || !board) return
      const pos = board.positions.find((p) => p.entry_id === entryId)
      if (!pos) return
      setMoveEntryId(entryId)
      setMoveAnchors([{ x: pos.anchor_x, y: pos.anchor_y }])
      setMovePreview(null)
      setLastMoveOutcome(null)
    },
    [canMoveEntry, board],
  )

  const addMoveAnchor = useCallback(
    async (x: number, y: number) => {
      if (!moveEntryId) return
      setMoveAnchors((prev) => {
        const last = prev[prev.length - 1]
        if (last && last.x === x && last.y === y) return prev
        const next = [...prev, { x, y }]
        // Preview on each change (debounced by React batching; server is authority).
        if (next.length >= 2) {
          setMoveBusy(true)
          previewMovement(
            roomId,
            campaignId,
            sessionId,
            { entry_id: moveEntryId, path: next },
            token,
          )
            .then((view) => setMovePreview(view))
            .catch(onError)
            .finally(() => setMoveBusy(false))
        }
        return next
      })
    },
    [moveEntryId, roomId, campaignId, sessionId, token, onError],
  )

  const clearMoveDraft = useCallback(() => {
    setMoveEntryId(null)
    setMoveAnchors([])
    setMovePreview(null)
  }, [])

  const confirmMoveDraft = useCallback(async () => {
    if (!moveEntryId || moveAnchors.length < 2 || !board || !movePreview) return
    const pos = board.positions.find((p) => p.entry_id === moveEntryId)
    if (!pos) return
    setMoveBusy(true)
    try {
      const view = await confirmMovement(
        roomId,
        campaignId,
        sessionId,
        {
          entry_id: moveEntryId,
          path: moveAnchors,
          expected_position_revision: pos.revision,
          expected_board_revision: board.runtime_revision,
          idempotency_key: requestId('move'),
        },
        token,
      )
      setLastMoveOutcome(view)
      clearMoveDraft()
      if (view.outcome === 'paused') {
        setPausedMove({ entryId: view.entry_id, pendingRevision: view.pending_revision })
      }
      await loadBoard()
      refresh()
    } catch (cause) {
      onError(cause)
    } finally {
      setMoveBusy(false)
    }
  }, [moveEntryId, moveAnchors, board, movePreview, roomId, campaignId, sessionId, token, clearMoveDraft, loadBoard, refresh, onError])

  const handleResumeMove = useCallback(async () => {
    if (!pausedMove) return
    setMoveBusy(true)
    try {
      const view = await resumeMovement(
        roomId,
        campaignId,
        sessionId,
        {
          entry_id: pausedMove.entryId,
          expected_pending_revision: pausedMove.pendingRevision,
          idempotency_key: requestId('resume'),
        },
        token,
      )
      if (view.outcome === 'resumed' || view.outcome === 'stopped') {
        setPausedMove(null)
      } else {
        setPausedMove({ entryId: view.entry_id, pendingRevision: view.pending_revision })
      }
      await loadBoard()
      refresh()
    } catch (cause) {
      onError(cause)
    } finally {
      setMoveBusy(false)
    }
  }, [pausedMove, roomId, campaignId, sessionId, token, loadBoard, refresh, onError])

  const handleCancelPending = useCallback(async () => {
    if (!pausedMove || !isCurrentDm || !cancelReason.trim()) return
    setMoveBusy(true)
    try {
      await cancelPendingMovement(
        roomId,
        campaignId,
        sessionId,
        {
          entry_id: pausedMove.entryId,
          reason: cancelReason.trim(),
          idempotency_key: requestId('cancel-pending'),
        },
        token,
      )
      setPausedMove(null)
      setCancelReason('')
      await loadBoard()
      refresh()
    } catch (cause) {
      onError(cause)
    } finally {
      setMoveBusy(false)
    }
  }, [pausedMove, isCurrentDm, cancelReason, roomId, campaignId, sessionId, token, loadBoard, refresh, onError])

  // --- DM reposition (distinct mode from gameplay movement) ---
  const handleRepositionConfirm = useCallback(async () => {
    if (!isCurrentDm || !repositionEntryId || !repositionTarget || !repositionReason.trim() || !board) return
    const pos = board.positions.find((p) => p.entry_id === repositionEntryId)
    if (!pos) return
    setMoveBusy(true)
    try {
      await repositionCombatant(
        roomId,
        campaignId,
        sessionId,
        {
          entry_id: repositionEntryId,
          anchor_x: repositionTarget.x,
          anchor_y: repositionTarget.y,
          reason: repositionReason.trim(),
          expected_position_revision: pos.revision,
          idempotency_key: requestId('reposition'),
        },
        token,
      )
      setRepositionMode(false)
      setRepositionEntryId(null)
      setRepositionTarget(null)
      setRepositionReason('')
      await loadBoard()
      refresh()
    } catch (cause) {
      onError(cause)
    } finally {
      setMoveBusy(false)
    }
  }, [isCurrentDm, repositionEntryId, repositionTarget, repositionReason, board, roomId, campaignId, sessionId, token, loadBoard, refresh, onError])

  // --- Range / target feedback ---
  const handleTargetCheck = useCallback(
    async (sourceEntryId: string, targetEntryId: string, attackSourceRef?: string, spellRef?: string) => {
      try {
        const result = await checkTarget(
          roomId,
          campaignId,
          sessionId,
          {
            source_entry_id: sourceEntryId,
            target_entry_id: targetEntryId,
            attack_source_ref: attackSourceRef ?? null,
            spell_ref: spellRef ?? null,
          },
          token,
        )
        setTargetCheck(result)
      } catch (cause) {
        onError(cause)
      }
    },
    [roomId, campaignId, sessionId, token, onError],
  )

  // --- AoE preview ---
  const handleAoeMapClick = useCallback(
    async (x: number, y: number, casterEntryId: string, spellRef: string, shape: 'circle' | 'square' | 'cone' | 'line', sizeFeet: number) => {
      if (!aoeOrigin) {
        setAoeOrigin({ x, y })
        return
      }
      setMoveBusy(true)
      try {
        const view = await previewAoeSpell(
          roomId,
          campaignId,
          sessionId,
          {
            caster_entry_id: casterEntryId,
            spell_ref: spellRef,
            template: {
              shape,
              size_feet: sizeFeet,
              origin_x: aoeOrigin.x,
              origin_y: aoeOrigin.y,
              aim_x: shape === 'cone' || shape === 'line' ? x : null,
              aim_y: shape === 'cone' || shape === 'line' ? y : null,
            },
          },
          token,
        )
        setAoePreview(view)
        setAoeOrigin(null)
      } catch (cause) {
        onError(cause)
      } finally {
        setMoveBusy(false)
      }
    },
    [aoeOrigin, roomId, campaignId, sessionId, token, onError],
  )

  // Touch handlers for pinch zoom.
  const handleTouchStart = useCallback(
    (e: React.TouchEvent) => {
      if (e.touches.length === 2) {
        e.preventDefault()
        const [t1, t2] = [e.touches[0], e.touches[1]]
        startPinch({ x: t1.clientX, y: t1.clientY }, { x: t2.clientX, y: t2.clientY })
      }
    },
    [startPinch],
  )
  const handleTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (e.touches.length === 2) {
        e.preventDefault()
        const [t1, t2] = [e.touches[0], e.touches[1]]
        pinchBy({ x: t1.clientX, y: t1.clientY }, { x: t2.clientX, y: t2.clientY })
      }
    },
    [pinchBy],
  )
  const handleTouchEnd = useCallback(() => {
    endPinch()
  }, [endPinch])

  return (
    <section
      className="tactical-map-panel"
      aria-label={copy.tacticalStageTitle}
      data-testid="tactical-map-panel"
    >
      {isCurrentDm && unplacedEntries.length > 0 ? (
        <div className="tactical-map-panel__placement" data-testid="tactical-placement">
          <h3>{copy.tacticalPlacementHeading}</h3>
          <div className="tactical-map-panel__placement-list">
            {unplacedEntries.map((entry) => (
              <button
                key={entry.id}
                type="button"
                className={`button secondary compact${placingEntryId === entry.id ? ' tactical-map-panel__placing--active' : ''}`}
                data-testid={`tactical-place-${entry.id}`}
                data-placing={placingEntryId === entry.id ? 'true' : undefined}
                disabled={placing}
                onClick={() =>
                  setPlacingEntryId((prev) => (prev === entry.id ? null : entry.id))
                }
              >
                {placing && placingEntryId === entry.id
                  ? copy.tacticalPlacing
                  : `${copy.tacticalPlaceToken}: ${entry.display_name}`}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="tactical-map-panel__toolbar" role="toolbar">
        <button type="button" className="button secondary compact" onClick={zoomIn}>
          {copy.tacticalZoomIn}
        </button>
        <button type="button" className="button secondary compact" onClick={zoomOut}>
          {copy.tacticalZoomOut}
        </button>
        <button
          type="button"
          className="button secondary compact"
          onClick={handleFitMap}
          data-testid="tactical-fit-map"
        >
          {copy.tacticalToolFitMap}
        </button>
        <button
          type="button"
          className="button secondary compact"
          onClick={handleCenterParty}
          data-testid="tactical-center-party"
        >
          {copy.tacticalCenterParty}
        </button>
        {isCurrentDm ? (
          <button
            type="button"
            className={`button secondary compact${placingEntryId ? ' tactical-map-panel__token-mode--active' : ''}`}
            data-testid="tactical-token-mode"
            data-active={placingEntryId ? 'true' : undefined}
            disabled={unplacedEntries.length === 0}
            onClick={() => {
              // Token tool = placement mode. Pick the first unplaced entry,
              // or clear if already placing.
              if (placingEntryId) {
                setPlacingEntryId(null)
              } else if (unplacedEntries.length > 0) {
                setPlacingEntryId(unplacedEntries[0].id)
              }
            }}
          >
            {copy.tacticalToolToken}
          </button>
        ) : null}
        {isCurrentDm ? (
          <button
            type="button"
            className={`button secondary compact${repositionMode ? ' tactical-map-panel__token-mode--active' : ''}`}
            data-testid="tactical-reposition-mode"
            data-active={repositionMode ? 'true' : undefined}
            onClick={() => {
              setRepositionMode((v) => !v)
              setRepositionEntryId(null)
              setRepositionTarget(null)
            }}
          >
            {copy.tacticalRepositionMode}
          </button>
        ) : null}
      </div>

      {/* Movement draft panel */}
      {moveEntryId ? (
        <div className="tactical-map-panel__movement" data-testid="tactical-movement">
          <h3>{copy.tacticalMoveHeading}</h3>
          <p data-testid="tactical-move-draft-label">{copy.tacticalMoveDraft}</p>
          {movePreview ? (
            <dl>
              <div>
                <dt>{copy.tacticalMoveUsed}</dt>
                <dd data-testid="tactical-move-used">{movePreview.used_feet} {copy.tacticalFeetUnit}</dd>
              </div>
              <div>
                <dt>{copy.tacticalMoveRemaining}</dt>
                <dd data-testid="tactical-move-remaining">{movePreview.remaining_feet} {copy.tacticalFeetUnit}</dd>
              </div>
              <div>
                <dt>{copy.tacticalMoveBudget}</dt>
                <dd>{movePreview.budget_feet} {copy.tacticalFeetUnit}</dd>
              </div>
            </dl>
          ) : null}
          {movePreview && !movePreview.valid && movePreview.failure ? (
            <p data-testid="tactical-move-invalid">
              {copy.tacticalMoveInvalid}: {movePreview.failure}
            </p>
          ) : null}
          <div>
            <button
              type="button"
              className="button primary compact"
              data-testid="tactical-move-confirm"
              disabled={!movePreview?.valid || moveBusy}
              onClick={() => void confirmMoveDraft()}
            >
              {copy.tacticalMoveConfirm}
            </button>
            <button
              type="button"
              className="button secondary compact"
              data-testid="tactical-move-cancel"
              disabled={moveBusy}
              onClick={clearMoveDraft}
            >
              {copy.tacticalMoveCancel}
            </button>
          </div>
        </div>
      ) : null}

      {/* Pending (paused) movement */}
      {pausedMove ? (
        <div className="tactical-map-panel__paused" data-testid="tactical-move-paused">
          <h4>{copy.tacticalMovePendingHeading}</h4>
          <p>{copy.tacticalMovePausedWaiting}</p>
          <button
            type="button"
            className="button primary compact"
            data-testid="tactical-move-resume"
            disabled={moveBusy}
            onClick={() => void handleResumeMove()}
          >
            {copy.tacticalMoveResume}
          </button>
          {isCurrentDm ? (
            <div>
              <label>
                {copy.tacticalMoveCancelReasonLabel}
                <input
                  type="text"
                  data-testid="tactical-move-cancel-reason"
                  value={cancelReason}
                  placeholder={copy.tacticalMoveCancelReasonPlaceholder}
                  onChange={(e) => setCancelReason(e.target.value)}
                />
              </label>
              <button
                type="button"
                className="button secondary compact"
                data-testid="tactical-move-cancel-pending"
                disabled={moveBusy || !cancelReason.trim()}
                onClick={() => void handleCancelPending()}
              >
                {copy.tacticalMoveCancelPending}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Last move outcome */}
      {lastMoveOutcome && !pausedMove ? (
        <p data-testid="tactical-move-outcome">
          {lastMoveOutcome.outcome === 'committed'
            ? copy.tacticalMoveOutcomeCommitted
            : lastMoveOutcome.outcome === 'interrupted'
              ? copy.tacticalMoveOutcomeInterrupted
              : copy.tacticalMoveOutcomePaused}
        </p>
      ) : null}

      {/* DM reposition mode */}
      {repositionMode && isCurrentDm ? (
        <div className="tactical-map-panel__reposition" data-testid="tactical-reposition">
          <h3>{copy.tacticalRepositionHeading}</h3>
          <p>{copy.tacticalRepositionHint}</p>
          <label>
            {copy.tacticalRepositionReasonLabel}
            <input
              type="text"
              data-testid="tactical-reposition-reason"
              value={repositionReason}
              placeholder={copy.tacticalRepositionReasonPlaceholder}
              onChange={(e) => setRepositionReason(e.target.value)}
            />
          </label>
          {repositionTarget ? (
            <p data-testid="tactical-reposition-target">
              ({repositionTarget.x}, {repositionTarget.y})
            </p>
          ) : null}
          <button
            type="button"
            className="button primary compact"
            data-testid="tactical-reposition-confirm"
            disabled={!repositionEntryId || !repositionTarget || !repositionReason.trim() || moveBusy}
            onClick={() => void handleRepositionConfirm()}
          >
            {copy.tacticalRepositionConfirm}
          </button>
          {!repositionEntryId || !repositionTarget || !repositionReason.trim() ? (
            <p>{copy.tacticalRepositionConfirmMissing}</p>
          ) : null}
        </div>
      ) : null}

      {/* Range feedback */}
      {targetCheck ? (
        <div className="tactical-map-panel__target-check" data-testid="tactical-target-check">
          <h4>{copy.tacticalTargetCheckLabel}</h4>
          <p data-testid="tactical-target-band">
            {targetCheck.blocked
              ? copy.tacticalTargetBlocked
              : !targetCheck.in_range
                ? copy.tacticalTargetOutOfRange
                : targetCheck.is_long_range
                  ? copy.tacticalTargetLongRange
                  : copy.tacticalTargetInRange}
            {targetCheck.distance_feet !== null ? ` (${targetCheck.distance_feet} ft)` : ''}
          </p>
        </div>
      ) : null}

      <div
        ref={boardWrapRef}
        className="tactical-map-panel__board-wrap"
        data-testid="tactical-board-wrap"
        onMouseDown={(e) => {
          if (e.button === 1) startPan(e.clientX, e.clientY)
        }}
        onMouseMove={(e) => panBy(e.clientX, e.clientY)}
        onMouseUp={endPan}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        {boardError ? (
          <p className="tactical-map-panel__error" data-testid="tactical-board-error">
            {copy.tacticalBoardLoadFailed}
          </p>
        ) : board ? (
          <BattleMapCanvas
            widthCells={board.width_cells}
            heightCells={board.height_cells}
            walls={canvasWalls}
            doors={canvasDoors}
            terrain={board.terrain.map((t) => ({
              x: t.x,
              y: t.y,
              terrain_kind: t.terrain_kind,
            }))}
            tokens={canvasTokens}
            imageUrl={imageObjectUrl}
            camera={camera}
            isDm={isCurrentDm}
            selectedEntryId={selectedEntryId}
            onCellClick={
              placingEntryId && isCurrentDm
                ? handleCellClick
                : moveEntryId
                  ? (x, y) => void addMoveAnchor(x, y)
                  : repositionMode && repositionEntryId
                    ? (x, y) => setRepositionTarget({ x, y })
                    : undefined
            }
            onTokenClick={(entryId) => {
              // DM reposition mode: select token to reposition.
              if (repositionMode && isCurrentDm) {
                setRepositionEntryId(entryId)
                return
              }
              // Movement: click own token to start/continue draft.
              if (canMoveEntry(entryId) && !placingEntryId) {
                if (moveEntryId === entryId) {
                  // Already moving this token; keep draft.
                  return
                }
                startMoveDraft(entryId)
                return
              }
              setSelectedEntryId((prev) => (prev === entryId ? null : entryId))
            }}
            onDoorClick={handleDoorClick}
            onEmptyMouseDown={(x, y) => startPan(x, y)}
            onMouseMove={(x, y) => panBy(x, y)}
            onMouseUp={endPan}
            onWheel={handleWheel}
          />
        ) : (
          <p className="tactical-map-panel__loading">{copy.tacticalBoardLoading}</p>
        )}
      </div>

      {isCurrentDm && selectedDoor ? (
        <div className="tactical-map-panel__door-controls" data-testid="tactical-door-controls">
          <h4>{copy.tacticalDoorControlsHeading}</h4>
          <div role="group" aria-label={copy.tacticalDoorStateLabel}>
            {(['open', 'closed', 'locked', 'broken'] as const).map((state) => (
              <button
                key={state}
                type="button"
                className="button secondary compact"
                data-testid={`tactical-door-state-${state}`}
                data-active={selectedDoor.state === state ? 'true' : undefined}
                disabled={doorPending}
                onClick={() => void handleDoorStateChange(state, selectedDoor.revealed)}
              >
                {copy[`tacticalDoorState_${state}` as keyof SessionCopy] as string}
              </button>
            ))}
          </div>
          <label>
            <input
              type="checkbox"
              data-testid="tactical-door-revealed"
              checked={selectedDoor.revealed}
              disabled={doorPending}
              onChange={(e) =>
                void handleDoorStateChange(
                  selectedDoor.state as 'open' | 'closed' | 'locked' | 'broken',
                  e.target.checked,
                )
              }
            />
            {copy.tacticalDoorRevealedLabel}
          </label>
        </div>
      ) : null}
    </section>
  )
}
