import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { getBattleMap, type BattleMap } from '../../api/battleMaps'
import type { CombatDetailView } from '../../api/combat'
import type { TableEvent } from '../../api/sessions'
import {
  getCombatBoard,
  placeCombatant,
  updateBoardDoorState,
  type BoardDoorView,
  type CombatBoardView,
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
      </div>

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
            onCellClick={isCurrentDm && placingEntryId ? handleCellClick : undefined}
            onTokenClick={(entryId) =>
              setSelectedEntryId((prev) => (prev === entryId ? null : entryId))
            }
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
