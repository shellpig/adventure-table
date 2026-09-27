import { useCallback, useEffect, useMemo, useState } from 'react'

import type { BattleMap } from '../../api/battleMaps'
import type { CombatDetailView, CombatEntryView } from '../../api/combat'
import type { TableEvent } from '../../api/sessions'
import {
  getCombatBoard,
  getCombatBoardImageUrl,
  placeCombatant,
  type BoardDoorView,
  type CombatBoardView,
} from '../../api/tacticalCombat'
import type { Locale } from '../../i18n/locale'
import type {
  ContentFieldResolver,
  ContentNameResolver,
} from '../../i18n/useContentPresentations'
import { BattleMapCanvas } from './BattleMapCanvas'
import type { CanvasDoor, CanvasToken, CanvasWall } from './BattleMapCanvas'
import {
  combatantFor,
  orderedEntries,
} from './sessionCombat'
import type { CombatEntryLabelResolver } from './sessionCombatLog'
import { formatCombatLogEvent } from './sessionCombatLog'
import type { SessionCopy } from './sessionCopy'
import { requestId } from './SessionTableSurface'
import { useTacticalCamera } from './useTacticalCamera'

type TacticalStageProps = {
  combat: CombatDetailView
  myEntryIds: string[]
  copy: SessionCopy
  locale: Locale
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  isCurrentDm: boolean
  battleMap?: BattleMap | null
  logEvents: TableEvent[]
  resolveEntryLabel: CombatEntryLabelResolver
  resolveContentName: ContentNameResolver
  resolveContentField: ContentFieldResolver
  onError: (cause: unknown) => void
  refresh: () => void
}

function doorIsHidden(boardDoor: BoardDoorView, battleMap: BattleMap | null | undefined): boolean {
  if (!battleMap || !boardDoor.door_id) return false
  const def = battleMap.doors.find((d) => d.id === boardDoor.door_id)
  return def?.visibility === 'hidden'
}

export function TacticalStage({
  combat,
  myEntryIds,
  copy,
  locale,
  roomId,
  campaignId,
  sessionId,
  token,
  isCurrentDm,
  battleMap,
  logEvents,
  resolveEntryLabel,
  resolveContentName,
  resolveContentField,
  onError,
  refresh,
}: TacticalStageProps) {
  const [board, setBoard] = useState<CombatBoardView | null>(null)
  const [boardError, setBoardError] = useState(false)
  const [selectedEntryId, setSelectedEntryId] = useState<string | null>(null)
  const [placingEntryId, setPlacingEntryId] = useState<string | null>(null)
  const [placing, setPlacing] = useState(false)
  const { camera, zoomIn, zoomOut, handleWheel, startPan, panBy, endPan, fitMap, centerOn } =
    useTacticalCamera()

  const loadBoard = useCallback(async () => {
    try {
      const view = await getCombatBoard(roomId, campaignId, sessionId, token)
      setBoard(view)
      setBoardError(false)
    } catch (cause) {
      setBoardError(true)
      onError(cause)
    }
  }, [roomId, campaignId, sessionId, token, onError])

  useEffect(() => {
    void loadBoard()
  }, [loadBoard, combat.revision])

  const roundText =
    typeof combat.round_number === 'number'
      ? copy.combatRound.replace('{round}', String(combat.round_number))
      : copy.combatPreInitiative
  const currentTurnEntry = combat.current_turn_entry_id
    ? combat.entries.find((entry) => entry.id === combat.current_turn_entry_id)
    : null
  const currentTurnName = currentTurnEntry ? currentTurnEntry.display_name : '-'
  const isMyTurn = Boolean(
    combat.current_turn_entry_id && myEntryIds.includes(combat.current_turn_entry_id),
  )
  const entries = orderedEntries(combat)

  const placedEntryIds = useMemo(
    () => new Set((board?.positions ?? []).map((p) => p.entry_id)),
    [board],
  )
  const unplacedEntries = useMemo(
    () => entries.filter((e) => !placedEntryIds.has(e.id) && e.status === 'active'),
    [entries, placedEntryIds],
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
        return {
          entry_id: p.entry_id,
          name: combatant?.projection.name || entry?.display_name || p.entry_id.slice(0, 8),
          anchor_x: p.anchor_x,
          anchor_y: p.anchor_y,
          footprint_width: p.footprint_width,
          footprint_height: p.footprint_height,
        }
      }),
    [board, combat],
  )

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

  const handleFitMap = useCallback(() => {
    if (!board) return
    fitMap(board.width_cells * 40, board.height_cells * 40, 800, 600)
  }, [board, fitMap])

  const handleCenterParty = useCallback(() => {
    if (!board || board.positions.length === 0) return
    const xs = board.positions.map((p) => p.anchor_x)
    const ys = board.positions.map((p) => p.anchor_y)
    const cx = (Math.min(...xs) + Math.max(...xs) + 1) / 2
    const cy = (Math.min(...ys) + Math.max(...ys) + 1) / 2
    centerOn(cx * 40, cy * 40, 800, 600)
  }, [board, centerOn])

  const imageUrl = board?.has_image
    ? getCombatBoardImageUrl(roomId, campaignId, sessionId)
    : null

  return (
    <section
      className="tactical-stage"
      aria-label={copy.tacticalStageTitle}
      data-testid="tactical-stage"
    >
      <header
        className="tactical-stage__header"
        data-testid="tactical-header"
        data-combat-round={combat.round_number ?? 'pre-initiative'}
        data-combat-current-turn={currentTurnName}
      >
        <div className="tactical-stage__round-indicator" data-testid="tactical-round">
          <span className="tactical-stage__round-badge">{roundText}</span>
        </div>
        <div className="tactical-stage__turn-indicator" data-testid="tactical-turn">
          <span className="tactical-stage__turn-label">{copy.combatCurrentTurn}:</span>
          <span className="tactical-stage__turn-name">{currentTurnName}</span>
          {isMyTurn ? (
            <span className="tactical-stage__your-turn-badge">{copy.combatYourTurn}</span>
          ) : null}
        </div>
      </header>

      {isCurrentDm && unplacedEntries.length > 0 ? (
        <div className="tactical-stage__placement" data-testid="tactical-placement">
          <h3>{copy.tacticalPlacementHeading}</h3>
          <div className="tactical-stage__placement-list">
            {unplacedEntries.map((entry: CombatEntryView) => (
              <button
                key={entry.id}
                type="button"
                className={`button secondary compact${placingEntryId === entry.id ? ' tactical-stage__placing--active' : ''}`}
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

      <div className="tactical-stage__toolbar" role="toolbar">
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
      </div>

      <div
        className="tactical-stage__board-wrap"
        data-testid="tactical-board-wrap"
        onMouseDown={(e) => {
          if (e.button === 1) startPan(e.clientX, e.clientY)
        }}
        onMouseMove={(e) => panBy(e.clientX, e.clientY)}
        onMouseUp={endPan}
      >
        {boardError ? (
          <p className="tactical-stage__error" data-testid="tactical-board-error">
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
            imageUrl={imageUrl}
            camera={camera}
            isDm={isCurrentDm}
            selectedEntryId={selectedEntryId}
            onCellClick={isCurrentDm && placingEntryId ? handleCellClick : undefined}
            onTokenClick={(entryId) =>
              setSelectedEntryId((prev) => (prev === entryId ? null : entryId))
            }
            onEmptyMouseDown={(x, y) => startPan(x, y)}
            onMouseMove={(x, y) => panBy(x, y)}
            onMouseUp={endPan}
            onWheel={handleWheel}
          />
        ) : (
          <p className="tactical-stage__loading">{copy.tacticalBoardLoading}</p>
        )}
      </div>

      <div className="tactical-stage__initiative">
        <h3 className="tactical-stage__section-heading">{copy.combatInitiativeHeading}</h3>
        <ol className="tactical-stage__initiative-list">
          {entries.map((entry) => {
            const isCurrent = entry.id === combat.current_turn_entry_id
            const isSelected = entry.id === selectedEntryId
            return (
              <li
                key={entry.id}
                data-testid="tactical-initiative-row"
                data-combat-entry={entry.id}
                data-selected={isSelected ? 'true' : undefined}
                aria-current={isCurrent ? 'true' : undefined}
                onClick={() => setSelectedEntryId(entry.id)}
                style={{ cursor: 'pointer' }}
              >
                <span>{entry.turn_order ?? '–'}</span>
                <span>{entry.display_name}</span>
                {isCurrent ? <span>{copy.combatCurrentTurn}</span> : null}
              </li>
            )
          })}
        </ol>
      </div>

      <div className="tactical-stage__log">
        <h3 className="tactical-stage__section-heading">{copy.log}</h3>
        <div className="tactical-stage__log-list" data-testid="tactical-combat-log">
          {logEvents.slice(-20).map((event) => {
            const presentation = formatCombatLogEvent(
              event,
              locale,
              resolveEntryLabel,
              resolveContentName,
              resolveContentField,
            )
            return (
              <p key={`log:${event.session_id}:${event.seq}`}>
                {presentation ? presentation.summary : event.kind}
              </p>
            )
          })}
        </div>
      </div>
    </section>
  )
}
