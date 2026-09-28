import { useCallback, useMemo, useRef, useState } from 'react'

import type { BattleMap } from '../../api/battleMaps'
import { replaceBattleMapObjects } from '../../api/battleMaps'
import { SessionApiError } from '../../api/sessions'
import { localizedSessionRequestMessage } from '../../i18n/sessionMessages'
import type { Locale } from '../../i18n/locale'
import { BattleMapCanvas } from './BattleMapCanvas'
import type { CanvasDoor, CanvasTerrain, CanvasWall } from './BattleMapCanvas'
import {
  addDoor,
  addWall,
  deleteById,
  eraseAt,
  findAt,
  setTerrain,
  toggleHidden as toggleHiddenInState,
  toWorkingState,
  type WorkingState,
} from './mapEditorState'
import type { SessionCopy } from './sessionCopy'
import { useTacticalCamera } from './useTacticalCamera'

export type EditorTool =
  | 'select'
  | 'wall'
  | 'door'
  | 'terrain'
  | 'draw'
  | 'erase'

type BattleMapEditorProps = {
  map: BattleMap
  copy: SessionCopy
  locale: Locale
  roomId: string
  token: string
  imageUrl?: string | null
  onSaved: (map: BattleMap) => void
  onError: (cause: unknown) => void
  onClose: () => void
}

let localIdCounter = 0
function localId(prefix: string): string {
  localIdCounter += 1
  return `${prefix}-local-${localIdCounter}`
}

const TOOLS: EditorTool[] = [
  'select',
  'wall',
  'door',
  'terrain',
  'draw',
  'erase',
]

export function BattleMapEditor({
  map,
  copy,
  locale,
  roomId,
  token,
  imageUrl,
  onSaved,
  onError,
  onClose,
}: BattleMapEditorProps) {
  const [working, setWorking] = useState<WorkingState>(() => toWorkingState(map))
  const [history, setHistory] = useState<WorkingState[]>([])
  const [tool, setTool] = useState<EditorTool>('select')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [terrainKind, setTerrainKind] = useState('difficult')
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const dragStartRef = useRef<{ x: number; y: number } | null>(null)
  const { camera, zoomIn, zoomOut, handleWheel, startPan, panBy, endPan, fitMap } =
    useTacticalCamera()

  const pushHistory = useCallback((prev: WorkingState) => {
    setHistory((h) => [...h.slice(-49), prev])
  }, [])

  const updateWorking = useCallback(
    (updater: (prev: WorkingState) => WorkingState) => {
      setWorking((prev) => {
        pushHistory(prev)
        return updater(prev)
      })
      setSelectedId(null)
      setSaveMessage(null)
    },
    [pushHistory],
  )

  const handleUndo = useCallback(() => {
    setHistory((h) => {
      if (h.length === 0) return h
      const prev = h[h.length - 1]
      setWorking(prev)
      setSelectedId(null)
      return h.slice(0, -1)
    })
  }, [])

  const handleCellClick = useCallback(
    (x: number, y: number) => {
      if (tool === 'terrain') {
        updateWorking((prev) => setTerrain(prev, { x, y, terrain_kind: terrainKind }))
      } else if (tool === 'erase') {
        updateWorking((prev) => eraseAt(prev, x, y))
      } else if (tool === 'select') {
        // Select wall/door under the cell.
        const hit = findAt(working, x, y)
        setSelectedId(hit?.id ?? null)
      }
    },
    [tool, terrainKind, updateWorking, working],
  )

  const handleCellMouseDown = useCallback(
    (x: number, y: number) => {
      if (tool === 'wall' || tool === 'door' || tool === 'draw') {
        dragStartRef.current = { x, y }
      }
    },
    [tool],
  )

  const handleCellMouseUp = useCallback(
    (x: number, y: number) => {
      const start = dragStartRef.current
      dragStartRef.current = null
      if (!start) return
      if (start.x === x && start.y === y) return
      if (tool === 'wall') {
        updateWorking((prev) =>
          addWall(prev, {
            id: localId('wall'),
            x1: start.x,
            y1: start.y,
            x2: x,
            y2: y,
            visibility: 'public',
          }),
        )
      } else if (tool === 'door') {
        updateWorking((prev) =>
          addDoor(prev, {
            id: localId('door'),
            x1: start.x,
            y1: start.y,
            x2: x,
            y2: y,
            default_state: 'closed',
            visibility: 'public',
          }),
        )
      }
      // 'draw' freehand is handled via drawings in a future step; drag creates a wall segment.
    },
    [tool, updateWorking],
  )

  const toggleHidden = useCallback(() => {
    if (!selectedId) return
    updateWorking((prev) => toggleHiddenInState(prev, selectedId))
  }, [selectedId, updateWorking])

  const deleteSelected = useCallback(() => {
    if (!selectedId) return
    updateWorking((prev) => deleteById(prev, selectedId))
  }, [selectedId, updateWorking])

  const handleSave = useCallback(async () => {
    setSaving(true)
    setSaveMessage(null)
    try {
      const saved = await replaceBattleMapObjects(
        roomId,
        map.id,
        {
          expected_revision: map.revision,
          walls: working.walls,
          doors: working.doors,
          terrain: working.terrain,
          drawings: [],
        },
        token,
      )
      setSaveMessage(copy.tacticalMapSaved)
      setHistory([])
      onSaved(saved)
    } catch (cause) {
      if (cause instanceof SessionApiError && cause.code === 'battle_map_revision_conflict') {
        setSaveMessage(
          localizedSessionRequestMessage(cause.code, cause.status, cause.message, locale),
        )
      } else {
        onError(cause)
      }
    } finally {
      setSaving(false)
    }
  }, [roomId, map.id, map.revision, working, token, copy, locale, onSaved, onError])

  const canvasWalls: CanvasWall[] = useMemo(
    () =>
      working.walls.map((w) => ({
        x1: w.x1,
        y1: w.y1,
        x2: w.x2,
        y2: w.y2,
        visibility: w.visibility ?? 'public',
      })),
    [working.walls],
  )

  const canvasDoors: CanvasDoor[] = useMemo(
    () =>
      working.doors.map((d) => ({
        door_id: d.id ?? null,
        x1: d.x1,
        y1: d.y1,
        x2: d.x2,
        y2: d.y2,
        state: d.default_state ?? 'closed',
        revealed: true,
        isHidden: d.visibility === 'hidden',
      })),
    [working.doors],
  )

  const canvasTerrain: CanvasTerrain[] = useMemo(
    () => working.terrain.map((t) => ({ x: t.x, y: t.y, terrain_kind: t.terrain_kind })),
    [working.terrain],
  )

  const selectedItem = useMemo(() => {
    if (!selectedId) return null
    const wall = working.walls.find((w) => w.id === selectedId)
    if (wall) return { kind: 'wall' as const, visibility: wall.visibility ?? 'public' }
    const door = working.doors.find((d) => d.id === selectedId)
    if (door) return { kind: 'door' as const, visibility: door.visibility ?? 'public' }
    return null
  }, [selectedId, working])

  const toolLabel = (t: EditorTool): string => {
    switch (t) {
      case 'select':
        return copy.tacticalToolSelect
      case 'wall':
        return copy.tacticalToolWall
      case 'door':
        return copy.tacticalToolDoor
      case 'terrain':
        return copy.tacticalToolTerrain
      case 'draw':
        return copy.tacticalToolDraw
      case 'erase':
        return copy.tacticalToolErase
    }
  }

  return (
    <section className="battle-map-editor" aria-label={copy.tacticalMapEditorTitle}>
      <header className="battle-map-editor__header">
        <h3>{copy.tacticalMapEditorTitle}: {map.name}</h3>
        <div className="battle-map-editor__actions">
          <button
            type="button"
            className="button secondary compact"
            disabled={saving}
            onClick={() => void handleSave()}
            data-testid="map-editor-save"
          >
            {saving ? copy.tacticalMapSaving : copy.tacticalMapSave}
          </button>
          <button
            type="button"
            className="button secondary compact"
            onClick={onClose}
            aria-label={copy.close}
          >
            ×
          </button>
        </div>
      </header>

      <div className="battle-map-editor__toolbar" role="toolbar" aria-label={copy.tacticalMapEditorTitle}>
        {TOOLS.map((t) => (
          <button
            key={t}
            type="button"
            className={`button secondary compact${tool === t ? ' battle-map-editor__tool--active' : ''}`}
            data-testid={`map-editor-tool-${t}`}
            data-active={tool === t ? 'true' : undefined}
            onClick={() => setTool(t)}
          >
            {toolLabel(t)}
          </button>
        ))}
        <button
          type="button"
          className="button secondary compact"
          disabled={history.length === 0}
          onClick={handleUndo}
          data-testid="map-editor-undo"
        >
          {copy.tacticalToolUndo}
        </button>
        <button
          type="button"
          className="button secondary compact"
          onClick={() => fitMap(map.width_cells * 40, map.height_cells * 40, 800, 600)}
          data-testid="map-editor-fit"
        >
          {copy.tacticalToolFitMap}
        </button>
        <button type="button" className="button secondary compact" onClick={zoomIn}>
          {copy.tacticalZoomIn}
        </button>
        <button type="button" className="button secondary compact" onClick={zoomOut}>
          {copy.tacticalZoomOut}
        </button>
      </div>

      {tool === 'terrain' ? (
        <div className="battle-map-editor__terrain-picker">
          <label>
            {copy.tacticalToolTerrain}:
            <select value={terrainKind} onChange={(e) => setTerrainKind(e.target.value)}>
              <option value="difficult">{copy.tacticalTerrainDifficult}</option>
              <option value="water">{copy.tacticalTerrainWater}</option>
              <option value="lava">{copy.tacticalTerrainLava}</option>
            </select>
          </label>
        </div>
      ) : null}

      {selectedItem ? (
        <div className="battle-map-editor__selection" data-testid="map-editor-selection">
          <span>
            {selectedItem.kind === 'wall' ? copy.tacticalToolWall : copy.tacticalToolDoor}
          </span>
          <button
            type="button"
            className="button secondary compact"
            onClick={toggleHidden}
            data-testid="map-editor-toggle-hidden"
            data-hidden={selectedItem.visibility === 'hidden' ? 'true' : undefined}
          >
            {copy.tacticalHiddenToggle}: {selectedItem.visibility === 'hidden' ? '✓' : '—'}
          </button>
          <button
            type="button"
            className="button secondary compact"
            onClick={deleteSelected}
            data-testid="map-editor-delete"
          >
            {copy.tacticalToolErase}
          </button>
        </div>
      ) : null}

      {saveMessage ? (
        <p className="battle-map-editor__save-message" data-testid="map-editor-save-message">
          {saveMessage}
        </p>
      ) : null}

      <div
        className="battle-map-editor__canvas-wrap"
        data-testid="map-editor-canvas"
        onMouseDown={(e) => {
          const cell = (e.target as HTMLElement).closest('[data-cell-x]')
          if (cell) {
            const x = Number(cell.getAttribute('data-cell-x'))
            const y = Number(cell.getAttribute('data-cell-y'))
            handleCellMouseDown(x, y)
          } else if (e.button === 1) {
            startPan(e.clientX, e.clientY)
          }
        }}
        onMouseUp={(e) => {
          const cell = (e.target as HTMLElement).closest('[data-cell-x]')
          if (cell && dragStartRef.current) {
            const x = Number(cell.getAttribute('data-cell-x'))
            const y = Number(cell.getAttribute('data-cell-y'))
            handleCellMouseUp(x, y)
          }
          endPan()
        }}
        onMouseMove={(e) => panBy(e.clientX, e.clientY)}
      >
        <BattleMapCanvas
          widthCells={map.width_cells}
          heightCells={map.height_cells}
          walls={canvasWalls}
          doors={canvasDoors}
          terrain={canvasTerrain}
          tokens={[]}
          imageUrl={imageUrl}
          camera={camera}
          isDm={true}
          onCellClick={handleCellClick}
          onWheel={handleWheel}
        />
      </div>
    </section>
  )
}
