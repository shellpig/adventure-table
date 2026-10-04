import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type {
  BattleMap,
  BattleMapMonsterPlacementVisibility,
  BattleMapTerrainKind,
  MonsterPlacementProblem,
} from '../../api/battleMaps'
import { replaceBattleMapObjects, replaceMonsterPlacements } from '../../api/battleMaps'
import type { MonsterLibrarySummaryView } from '../../api/monsterLibrary'
import { getMonsterLibraryEntry, listMonsterLibrary } from '../../api/monsterLibrary'
import { SessionApiError } from '../../api/sessions'
import { localizedSessionRequestMessage } from '../../i18n/sessionMessages'
import type { Locale } from '../../i18n/locale'
import { BattleMapCanvas } from './BattleMapCanvas'
import type { CanvasDoor, CanvasTerrain, CanvasToken, CanvasWall } from './BattleMapCanvas'
import {
  availableMonsterTemplates,
  buildMonsterPlacementsBody,
  extractPlacementProblems,
  footprintForSizeName,
  monsterPlacementsFromMap,
  monsterSummaryFromDetail,
  moveMonsterPlacement,
  newPlacementClientId,
  removeMonsterPlacement,
  resolvePlacementTemplate,
  toggleMonsterPlacementVisibility,
  type WorkingMonsterPlacement,
} from './mapMonsterPlacements'
import {
  battleMapLibraryCopy,
  monsterPlacementProblemMessage,
} from './battleMapLibraryCopy'
import { formatMonsterName } from './monsterLibraryCopy'
import {
  addDoor,
  addDrawing,
  addWall,
  DRAWING_COLORS,
  DRAWING_WIDTH_DEFAULT,
  DRAWING_WIDTH_MAX,
  DRAWING_WIDTH_MIN,
  type DrawingColorKey,
  EDITOR_CANVAS_HEIGHT_DEFAULT,
  deleteById,
  eraseAt,
  findAt,
  roundCellCoord,
  setTerrain,
  shouldTriggerEditorUndo,
  thinDrawingPoints,
  toggleHidden as toggleHiddenInState,
  toReplaceObjects,
  toWorkingState,
  type GridSegment,
  type WorkingState,
  nearestGridSegment,
  placementLine,
  resizedCanvasHeight,
  snapToVertex,
  type CellPoint,
} from './mapEditorState'
import type { SessionCopy } from './sessionCopy'
import { BATTLE_MAP_CELL_SIZE, useTacticalCamera } from './useTacticalCamera'

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

const DRAWING_COLOR_LABEL: Record<DrawingColorKey, `tacticalDrawColor${Capitalize<DrawingColorKey>}`> = {
  white: 'tacticalDrawColorWhite',
  black: 'tacticalDrawColorBlack',
  red: 'tacticalDrawColorRed',
  orange: 'tacticalDrawColorOrange',
  yellow: 'tacticalDrawColorYellow',
  green: 'tacticalDrawColorGreen',
  blue: 'tacticalDrawColorBlue',
  purple: 'tacticalDrawColorPurple',
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
  const [terrainKind, setTerrainKind] = useState<BattleMapTerrainKind>('difficult')
  const [penColor, setPenColor] = useState<string>(DRAWING_COLORS[0].hex)
  const [penWidth, setPenWidth] = useState(DRAWING_WIDTH_DEFAULT)
  const [canvasHeight, setCanvasHeight] = useState(EDITOR_CANVAS_HEIGHT_DEFAULT)
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState<string | null>(null)

  // M07-C monster pre-placements (library only; never a live combat API).
  const libraryCopy = battleMapLibraryCopy(locale)
  const [monsterMode, setMonsterMode] = useState(false)
  const [placements, setPlacements] = useState<WorkingMonsterPlacement[]>(() =>
    monsterPlacementsFromMap(map.monster_placements ?? []),
  )
  const [templates, setTemplates] = useState<MonsterLibrarySummaryView[] | null>(null)
  const [templatesLoading, setTemplatesLoading] = useState(false)
  const [templateSearch, setTemplateSearch] = useState('')
  // Saved placements may reference templates outside the current menu page
  // (the menu only loads one page of 50). Those refs are resolved separately
  // below, including archived custom templates the picker never offers.
  const [resolvedTemplates, setResolvedTemplates] = useState<
    Record<string, MonsterLibrarySummaryView>
  >({})
  // Only the latest menu request may update state; an older response that
  // arrives later (e.g. an earlier keystroke after a later one) is dropped.
  const templateListRequestSeq = useRef(0)
  const unresolvableRefs = useRef<Set<string>>(new Set())
  const [selectedTemplateRef, setSelectedTemplateRef] = useState('')
  const [selectedPlacementId, setSelectedPlacementId] = useState<string | null>(null)
  const [newPlacementVisibility, setNewPlacementVisibility] =
    useState<BattleMapMonsterPlacementVisibility>('public')
  const [placementProblems, setPlacementProblems] = useState<MonsterPlacementProblem[]>([])
  const [placementsSaving, setPlacementsSaving] = useState(false)
  const [placementsMessage, setPlacementsMessage] = useState<string | null>(null)

  // Editor previews and highlights
  const [highlightSegment, setHighlightSegment] = useState<GridSegment | null>(null)
  const [highlightCell, setHighlightCell] = useState<{ x: number; y: number } | null>(null)
  const [highlightObjectId, setHighlightObjectId] = useState<string | null>(null)
  const [previewLine, setPreviewLine] = useState<{
    x1: number
    y1: number
    x2: number
    y2: number
  } | null>(null)
  const [previewDrawingPoints, setPreviewDrawingPoints] = useState<Array<[number, number]> | null>(
    null,
  )

  const containerRef = useRef<HTMLDivElement | null>(null)
  const dragStartVertexRef = useRef<{ x: number; y: number } | null>(null)
  const lastSnappedVertexRef = useRef<{ x: number; y: number } | null>(null)
  const clickSegmentRef = useRef<GridSegment | null>(null)
  const drawingPointsRef = useRef<Array<[number, number]>>([])
  const isDrawingRef = useRef(false)
  // Key of the last cell a terrain drag painted; null when no terrain stroke is in progress.
  const paintingCellRef = useRef<string | null>(null)

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

  const selectTool = useCallback((nextTool: EditorTool) => {
    setTool(nextTool)
    setHighlightSegment(null)
    setHighlightCell(null)
    setHighlightObjectId(null)
    setPreviewLine(null)
    setPreviewDrawingPoints(null)
    dragStartVertexRef.current = null
    lastSnappedVertexRef.current = null
    isDrawingRef.current = false
    drawingPointsRef.current = []
  }, [])

  const getMapCell = useCallback((clientX: number, clientY: number): CellPoint | null => {
    // The SVG's screen CTM already includes the wrapper centring, the camera CSS transform and
    // the SVG's rendered size, so it maps the pointer straight into viewBox pixels.
    const svg = containerRef.current?.querySelector<SVGSVGElement>('svg[data-testid="battle-map"]')
    const ctm = svg?.getScreenCTM()
    if (!ctm) return null
    const point = new DOMPoint(clientX, clientY).matrixTransform(ctm.inverse())
    return { cellX: point.x / BATTLE_MAP_CELL_SIZE, cellY: point.y / BATTLE_MAP_CELL_SIZE }
  }, [])

  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (e.button === 1) {
        // Middle button pans the map; stop the browser's middle-click autoscroll.
        e.preventDefault()
        startPan(e.clientX, e.clientY)
        return
      }
      if (e.button !== 0) return

      const cell = getMapCell(e.clientX, e.clientY)
      if (!cell) return

      if (tool === 'terrain') {
        const x = Math.floor(cell.cellX)
        const y = Math.floor(cell.cellY)
        if (x < 0 || x >= map.width_cells || y < 0 || y >= map.height_cells) return
        // One stroke is one undo step: only its first cell records history.
        paintingCellRef.current = `${x},${y}`
        updateWorking((prev) => setTerrain(prev, { x, y, terrain_kind: terrainKind }))
        return
      }

      if (tool === 'wall' || tool === 'door') {
        const start = snapToVertex(cell.cellX, cell.cellY, map.width_cells, map.height_cells)
        dragStartVertexRef.current = start
        lastSnappedVertexRef.current = start
        clickSegmentRef.current = nearestGridSegment(cell.cellX, cell.cellY, map.width_cells, map.height_cells)
        setPreviewLine({ x1: start.x, y1: start.y, x2: start.x, y2: start.y })
        setHighlightSegment(null)
      } else if (tool === 'draw') {
        const coords = cell
        const rx = roundCellCoord(coords.cellX)
        const ry = roundCellCoord(coords.cellY)
        drawingPointsRef.current = [[rx, ry]]
        isDrawingRef.current = true
        setPreviewDrawingPoints([[rx, ry]])
      }
    },
    [getMapCell, map.height_cells, map.width_cells, startPan, terrainKind, tool, updateWorking],
  )

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      panBy(e.clientX, e.clientY)

      const cell = getMapCell(e.clientX, e.clientY)
      if (!cell) return

      // Dragging wall/door
      if (dragStartVertexRef.current && (tool === 'wall' || tool === 'door')) {
        const snapped = snapToVertex(cell.cellX, cell.cellY, map.width_cells, map.height_cells)
        lastSnappedVertexRef.current = snapped
        setPreviewLine({
          x1: dragStartVertexRef.current.x,
          y1: dragStartVertexRef.current.y,
          x2: snapped.x,
          y2: snapped.y,
        })
        return
      }

      // Dragging terrain paint
      if (paintingCellRef.current !== null && tool === 'terrain') {
        const x = Math.floor(cell.cellX)
        const y = Math.floor(cell.cellY)
        const key = `${x},${y}`
        if (x >= 0 && x < map.width_cells && y >= 0 && y < map.height_cells && key !== paintingCellRef.current) {
          paintingCellRef.current = key
          setWorking((prev) => setTerrain(prev, { x, y, terrain_kind: terrainKind }))
        }
        return
      }

      // Dragging free drawing
      if (isDrawingRef.current && tool === 'draw') {
        const coords = cell
        const rx = roundCellCoord(coords.cellX)
        const ry = roundCellCoord(coords.cellY)
        const last = drawingPointsRef.current[drawingPointsRef.current.length - 1]
        if (!last || last[0] !== rx || last[1] !== ry) {
          drawingPointsRef.current.push([rx, ry])
          setPreviewDrawingPoints([...drawingPointsRef.current])
        }
        return
      }

      // Hover states (no button pressed)
      if (tool === 'wall' || tool === 'door') {
        const segment = nearestGridSegment(
          cell.cellX,
          cell.cellY,
          map.width_cells,
          map.height_cells,
        )
        setHighlightSegment(segment)
        setHighlightCell(null)
        setHighlightObjectId(null)
      } else if (tool === 'terrain' || tool === 'erase') {
        const coords = cell
        const cx = Math.floor(coords.cellX)
        const cy = Math.floor(coords.cellY)
        if (cx >= 0 && cx < map.width_cells && cy >= 0 && cy < map.height_cells) {
          setHighlightCell({ x: cx, y: cy })
        } else {
          setHighlightCell(null)
        }
        setHighlightSegment(null)
        setHighlightObjectId(null)
      } else if (tool === 'select') {
        const coords = cell
        const cx = Math.floor(coords.cellX)
        const cy = Math.floor(coords.cellY)
        const hit = findAt(working, cx, cy)
        setHighlightObjectId(hit?.id ?? null)
        setHighlightSegment(null)
        setHighlightCell(null)
      } else {
        setHighlightSegment(null)
        setHighlightCell(null)
        setHighlightObjectId(null)
      }
    },
    [getMapCell, map.height_cells, map.width_cells, panBy, terrainKind, tool, working],
  )

  const handleMouseUp = useCallback(() => {
    endPan()
    paintingCellRef.current = null

    if (dragStartVertexRef.current && (tool === 'wall' || tool === 'door')) {
      const start = dragStartVertexRef.current
      const end = lastSnappedVertexRef.current ?? start
      const clicked = clickSegmentRef.current
      dragStartVertexRef.current = null
      lastSnappedVertexRef.current = null
      clickSegmentRef.current = null
      setPreviewLine(null)

      const line = placementLine(start, end, clicked)
      if (line) {
        if (tool === 'wall') {
          updateWorking((prev) =>
            addWall(prev, {
              id: localId('wall'),
              ...line,
              visibility: 'public',
            }),
          )
        } else if (tool === 'door') {
          updateWorking((prev) =>
            addDoor(prev, {
              id: localId('door'),
              ...line,
              default_state: 'closed',
              visibility: 'public',
            }),
          )
        }
      }
    }

    if (isDrawingRef.current && tool === 'draw') {
      isDrawingRef.current = false
      const raw = drawingPointsRef.current
      drawingPointsRef.current = []
      setPreviewDrawingPoints(null)

      const thinned = thinDrawingPoints(raw)
      if (thinned.length >= 1) {
        updateWorking((prev) =>
          addDrawing(prev, {
            id: localId('drawing'),
            payload: { kind: 'freehand', points: thinned, color: penColor, width: penWidth },
          }),
        )
      }
    }
  }, [endPan, penColor, penWidth, tool, updateWorking])

  const handleMouseLeave = useCallback(() => {
    if (!dragStartVertexRef.current && !isDrawingRef.current) {
      setHighlightSegment(null)
      setHighlightCell(null)
      setHighlightObjectId(null)
    }
  }, [])

  useEffect(() => {
    const handleGlobalMouseUp = () => {
      if (dragStartVertexRef.current || isDrawingRef.current || paintingCellRef.current !== null) {
        handleMouseUp()
      }
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (dragStartVertexRef.current) {
          dragStartVertexRef.current = null
          lastSnappedVertexRef.current = null
          clickSegmentRef.current = null
          setPreviewLine(null)
        }
        if (isDrawingRef.current) {
          isDrawingRef.current = false
          drawingPointsRef.current = []
          setPreviewDrawingPoints(null)
        }
        return
      }

      if (shouldTriggerEditorUndo(e)) {
        e.preventDefault()
        handleUndo()
      }
    }

    window.addEventListener('mouseup', handleGlobalMouseUp)
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('mouseup', handleGlobalMouseUp)
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [handleMouseUp, handleUndo])

  const startResize = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (e.button !== 0) return
      e.preventDefault()
      const startY = e.clientY
      const startHeight = canvasHeight
      const handleMove = (event: PointerEvent) => {
        setCanvasHeight(resizedCanvasHeight(startHeight, event.clientY - startY))
      }
      const handleUp = () => {
        window.removeEventListener('pointermove', handleMove)
        window.removeEventListener('pointerup', handleUp)
      }
      window.addEventListener('pointermove', handleMove)
      window.addEventListener('pointerup', handleUp)
    },
    [canvasHeight],
  )

  const handleCellClick = useCallback(
    (x: number, y: number) => {
      if (tool === 'erase') {
        updateWorking((prev) => eraseAt(prev, x, y))
      } else if (tool === 'select') {
        const hit = findAt(working, x, y)
        setSelectedId(hit?.id ?? null)
      }
    },
    [tool, updateWorking, working],
  )

  const toggleHidden = useCallback(() => {
    if (!selectedId) return
    updateWorking((prev) => toggleHiddenInState(prev, selectedId))
  }, [selectedId, updateWorking])

  const deleteSelected = useCallback(() => {
    if (!selectedId) return
    updateWorking((prev) => deleteById(prev, selectedId))
  }, [selectedId, updateWorking])

  const enterMonsterMode = useCallback(() => {
    setMonsterMode(true)
    setSelectedId(null)
    setHighlightSegment(null)
    setHighlightCell(null)
    setHighlightObjectId(null)
    setPreviewLine(null)
    setPreviewDrawingPoints(null)
  }, [])

  useEffect(() => {
    if (!monsterMode) return
    const requestSeq = ++templateListRequestSeq.current
    setTemplatesLoading(true)
    listMonsterLibrary(roomId, token, {
      query: templateSearch.trim() || undefined,
      include_archived: false,
      limit: 50,
    })
      .then((list) => {
        if (requestSeq !== templateListRequestSeq.current) return
        setTemplates(list)
        setTemplatesLoading(false)
      })
      .catch((cause) => {
        if (requestSeq !== templateListRequestSeq.current) return
        setTemplatesLoading(false)
        onError(cause)
      })
  }, [monsterMode, templateSearch, roomId, token, onError])

  // Resolve saved placements whose template is not on the current menu page.
  // Each missing ref is fetched once via the detail endpoint (archived custom
  // templates included); refs the server rejects are remembered so a reopen
  // with a deleted template does not refetch in a loop.
  useEffect(() => {
    if (!monsterMode || templates === null) return
    const known = new Set([
      ...templates.map((t) => t.ref),
      ...Object.keys(resolvedTemplates),
    ])
    const missing = Array.from(new Set(placements.map((p) => p.templateRef))).filter(
      (ref) => ref && !known.has(ref) && !unresolvableRefs.current.has(ref),
    )
    if (missing.length === 0) return
    let cancelled = false
    void (async () => {
      for (const ref of missing) {
        try {
          const detail = await getMonsterLibraryEntry(roomId, ref, token)
          if (cancelled) return
          const summary = monsterSummaryFromDetail(detail)
          setResolvedTemplates((prev) => (prev[ref] ? prev : { ...prev, [ref]: summary }))
        } catch {
          if (!cancelled) unresolvableRefs.current.add(ref)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [monsterMode, templates, placements, resolvedTemplates, roomId, token])

  const templateForPlacement = useCallback(
    (templateRef: string): MonsterLibrarySummaryView | undefined => {
      if (templates) {
        const hit = resolvePlacementTemplate(templateRef, templates)
        if (hit) return hit
      }
      return resolvedTemplates[templateRef]
    },
    [templates, resolvedTemplates],
  )

  const placementDisplayName = useCallback(
    (placement: WorkingMonsterPlacement): string => {
      const template = templateForPlacement(placement.templateRef)
      if (template) {
        return formatMonsterName(
          { name: template.name, names: template.names, name_is_custom: template.name_is_custom },
          locale,
        )
      }
      return placement.templateRef || libraryCopy.monsterPlacementUnknownTemplate
    },
    [templateForPlacement, locale, libraryCopy],
  )

  const placementAt = useCallback(
    (x: number, y: number): WorkingMonsterPlacement | undefined =>
      placements.find((p) => {
        const footprint = footprintForSizeName(templateForPlacement(p.templateRef)?.size)
        return (
          x >= p.anchor_x &&
          x < p.anchor_x + footprint.width &&
          y >= p.anchor_y &&
          y < p.anchor_y + footprint.height
        )
      }),
    [placements, templateForPlacement],
  )

  const handleMonsterCellClick = useCallback(
    (x: number, y: number) => {
      const hit = placementAt(x, y)
      if (hit) {
        setSelectedPlacementId((prev) => (prev === hit.clientId ? null : hit.clientId))
        return
      }
      if (selectedPlacementId) {
        setPlacements((prev) => moveMonsterPlacement(prev, selectedPlacementId, x, y))
        setPlacementsMessage(null)
        return
      }
      if (selectedTemplateRef) {
        setPlacements((prev) => [
          ...prev,
          {
            clientId: newPlacementClientId(),
            templateRef: selectedTemplateRef,
            anchor_x: x,
            anchor_y: y,
            visibility: newPlacementVisibility,
          },
        ])
        setPlacementsMessage(null)
      }
    },
    [placementAt, selectedPlacementId, selectedTemplateRef, newPlacementVisibility],
  )

  const handlePlacementTokenClick = useCallback((clientId: string) => {
    setSelectedPlacementId((prev) => (prev === clientId ? null : clientId))
  }, [])

  const togglePlacementHidden = useCallback(() => {
    if (!selectedPlacementId) return
    setPlacements((prev) => toggleMonsterPlacementVisibility(prev, selectedPlacementId))
    setPlacementsMessage(null)
  }, [selectedPlacementId])

  const removeSelectedPlacement = useCallback(() => {
    if (!selectedPlacementId) return
    setPlacements((prev) => removeMonsterPlacement(prev, selectedPlacementId))
    setSelectedPlacementId(null)
    setPlacementsMessage(null)
  }, [selectedPlacementId])

  const handleSavePlacements = useCallback(async () => {
    if (placementsSaving) return
    setPlacementsSaving(true)
    setPlacementsMessage(null)
    try {
      const saved = await replaceMonsterPlacements(
        roomId,
        map.id,
        buildMonsterPlacementsBody(map.revision, placements),
        token,
      )
      setPlacements(monsterPlacementsFromMap(saved.monster_placements ?? []))
      setPlacementProblems([])
      setSelectedPlacementId(null)
      setPlacementsMessage(libraryCopy.monsterPlacementSaved)
      onSaved(saved)
    } catch (cause) {
      if (cause instanceof SessionApiError && cause.code === 'map_monster_placement_invalid') {
        setPlacementProblems(extractPlacementProblems(cause))
        setPlacementsMessage(libraryCopy.errMapMonsterPlacementInvalid)
      } else if (
        cause instanceof SessionApiError &&
        cause.code === 'battle_map_revision_conflict'
      ) {
        setPlacementsMessage(
          localizedSessionRequestMessage(cause.code, cause.status, cause.message, locale),
        )
      } else {
        onError(cause)
      }
    } finally {
      setPlacementsSaving(false)
    }
  }, [
    placementsSaving,
    roomId,
    map.id,
    map.revision,
    placements,
    token,
    libraryCopy,
    locale,
    onSaved,
    onError,
  ])

  const handleSave = useCallback(async () => {
    setSaving(true)
    setSaveMessage(null)
    try {
      const saved = await replaceBattleMapObjects(
        roomId,
        map.id,
        { expected_revision: map.revision, ...toReplaceObjects(working) },
        token,
      )
      setSaveMessage(copy.tacticalMapSaved)
      setHistory([])
      // Continue from the saved map so new objects carry their server-assigned ids.
      setWorking(toWorkingState(saved))
      setSelectedId(null)
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
        id: w.id ?? undefined,
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

  const placementTokens: CanvasToken[] = useMemo(
    () =>
      placements.map((p) => {
        const footprint = footprintForSizeName(templateForPlacement(p.templateRef)?.size)
        return {
          entry_id: p.clientId,
          name: placementDisplayName(p),
          anchor_x: p.anchor_x,
          anchor_y: p.anchor_y,
          footprint_width: footprint.width,
          footprint_height: footprint.height,
          isHidden: p.visibility === 'hidden',
        }
      }),
    [placements, templateForPlacement, placementDisplayName],
  )

  const problemPlacementIds = useMemo(
    () => new Set(placementProblems.map((p) => p.placement_id)),
    [placementProblems],
  )

  const availableTemplates = useMemo(
    () => (templates ? availableMonsterTemplates(templates) : []),
    [templates],
  )

  const selectedPlacement = useMemo(
    () => placements.find((p) => p.clientId === selectedPlacementId) ?? null,
    [placements, selectedPlacementId],
  )

  const handleCanvasCellClick = useCallback(
    (x: number, y: number) => {
      if (monsterMode) {
        handleMonsterCellClick(x, y)
      } else {
        handleCellClick(x, y)
      }
    },
    [monsterMode, handleMonsterCellClick, handleCellClick],
  )

  const selectedItem = useMemo(() => {
    if (!selectedId) return null
    const wall = working.walls.find((w) => w.id === selectedId)
    if (wall) return { kind: 'wall' as const, visibility: wall.visibility ?? 'public' }
    const door = working.doors.find((d) => d.id === selectedId)
    if (door) return { kind: 'door' as const, visibility: door.visibility ?? 'public' }
    const drawing = working.drawings.find((d) => d.id === selectedId)
    if (drawing) return { kind: 'drawing' as const, visibility: 'public' as const }
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
            className={`button secondary compact${tool === t && !monsterMode ? ' battle-map-editor__tool--active' : ''}`}
            data-testid={`map-editor-tool-${t}`}
            data-active={tool === t && !monsterMode ? 'true' : undefined}
            aria-pressed={tool === t && !monsterMode}
            disabled={monsterMode}
            onClick={() => selectTool(t)}
          >
            {toolLabel(t)}
          </button>
        ))}
        <button
          type="button"
          className={`button secondary compact${monsterMode ? ' battle-map-editor__tool--active' : ''}`}
          data-testid="map-editor-tool-monster"
          data-active={monsterMode ? 'true' : undefined}
          aria-pressed={monsterMode}
          onClick={() => {
            if (monsterMode) {
              setMonsterMode(false)
              setSelectedPlacementId(null)
            } else {
              enterMonsterMode()
            }
          }}
        >
          {copy.tacticalToolMonster}
        </button>
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
          onClick={() => fitMap(map.width_cells * BATTLE_MAP_CELL_SIZE, map.height_cells * BATTLE_MAP_CELL_SIZE, 800, 600)}
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
            <select
              value={terrainKind}
              onChange={(e) => setTerrainKind(e.target.value as BattleMapTerrainKind)}
            >
              <option value="normal">{copy.tacticalTerrainNormal}</option>
              <option value="difficult">{copy.tacticalTerrainDifficult}</option>
              <option value="blocked">{copy.tacticalTerrainBlocked}</option>
            </select>
          </label>
        </div>
      ) : null}

      {tool === 'draw' ? (
        <div className="battle-map-editor__pen-picker" data-testid="map-editor-pen-picker">
          <span>{copy.tacticalDrawColor}:</span>
          <div className="battle-map-editor__swatches" role="group" aria-label={copy.tacticalDrawColor}>
            {DRAWING_COLORS.map((color) => (
              <button
                key={color.key}
                type="button"
                className={`battle-map-editor__swatch${penColor === color.hex ? ' battle-map-editor__swatch--active' : ''}`}
                style={{ background: color.hex }}
                data-testid={`map-editor-color-${color.key}`}
                aria-label={copy[DRAWING_COLOR_LABEL[color.key]]}
                aria-pressed={penColor === color.hex}
                onClick={() => setPenColor(color.hex)}
              />
            ))}
          </div>
          <label>
            {copy.tacticalDrawWidth}:
            <input
              type="range"
              min={DRAWING_WIDTH_MIN}
              max={DRAWING_WIDTH_MAX}
              step={1}
              value={penWidth}
              onChange={(e) => setPenWidth(Number(e.target.value))}
              data-testid="map-editor-pen-width"
            />
            <span>{penWidth}</span>
          </label>
        </div>
      ) : null}

      {selectedItem ? (
        <div className="battle-map-editor__selection" data-testid="map-editor-selection">
          <span>
            {selectedItem.kind === 'wall'
              ? copy.tacticalToolWall
              : selectedItem.kind === 'door'
                ? copy.tacticalToolDoor
                : copy.tacticalToolDraw}
          </span>
          {selectedItem.kind !== 'drawing' ? (
            <button
              type="button"
              className="button secondary compact"
              onClick={toggleHidden}
              data-testid="map-editor-toggle-hidden"
              data-hidden={selectedItem.visibility === 'hidden' ? 'true' : undefined}
            >
              {copy.tacticalHiddenToggle}: {selectedItem.visibility === 'hidden' ? '✓' : '—'}
            </button>
          ) : null}
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

      {monsterMode ? (
        <div className="battle-map-editor__monster-panel" data-testid="monster-placement-panel">
          <h4>{libraryCopy.monsterPlacementsHeading}</h4>
          <p>{libraryCopy.monsterPlacementsHint}</p>
          {templates === null ? (
            <p>{libraryCopy.monsterPlacementLoadingTemplates}</p>
          ) : (
            <div className="battle-map-editor__monster-picker">
              <label>
                {libraryCopy.monsterTemplateSearchLabel}:
                <input
                  type="search"
                  value={templateSearch}
                  placeholder={libraryCopy.monsterTemplateSearchPlaceholder}
                  onChange={(e) => setTemplateSearch(e.target.value)}
                  data-testid="monster-placement-template-search"
                />
              </label>
              <label>
                {libraryCopy.monsterTemplatePickerLabel}:
                <select
                  value={selectedTemplateRef}
                  onChange={(e) => {
                    const ref = e.target.value
                    setSelectedTemplateRef(ref)
                    const hit = templates ? resolvePlacementTemplate(ref, templates) : undefined
                    if (ref && hit) {
                      setResolvedTemplates((prev) =>
                        prev[ref] ? prev : { ...prev, [ref]: hit },
                      )
                    }
                  }}
                  data-testid="monster-placement-template-picker"
                >
                  <option value="">{libraryCopy.monsterTemplatePickerPlaceholder}</option>
                  {availableTemplates.map((t) => (
                    <option key={t.ref} value={t.ref}>
                      {formatMonsterName(
                        { name: t.name, names: t.names, name_is_custom: t.name_is_custom },
                        locale,
                      )}
                    </option>
                  ))}
                  {selectedTemplateRef &&
                  !availableTemplates.some((t) => t.ref === selectedTemplateRef)
                    ? (() => {
                        const kept =
                          templateForPlacement(selectedTemplateRef) ??
                          (templates
                            ? resolvePlacementTemplate(selectedTemplateRef, templates)
                            : undefined)
                        return kept ? (
                          <option key={kept.ref} value={kept.ref}>
                            {formatMonsterName(
                              {
                                name: kept.name,
                                names: kept.names,
                                name_is_custom: kept.name_is_custom,
                              },
                              locale,
                            )}
                          </option>
                        ) : null
                      })()
                    : null}
                </select>
              </label>
              {!templatesLoading && availableTemplates.length === 0 && templateSearch.trim() ? (
                <p className="room-empty-text">{libraryCopy.monsterTemplateNoMatch}</p>
              ) : null}
              <label>
                {libraryCopy.monsterPlacementVisibilityLabel}:
                <select
                  value={newPlacementVisibility}
                  onChange={(e) =>
                    setNewPlacementVisibility(
                      e.target.value as BattleMapMonsterPlacementVisibility,
                    )
                  }
                  data-testid="monster-placement-visibility-picker"
                >
                  <option value="public">{libraryCopy.monsterVisibilityPublic}</option>
                  <option value="hidden">{libraryCopy.monsterVisibilityHidden}</option>
                </select>
              </label>
              <button
                type="button"
                className="button secondary compact"
                disabled={placementsSaving}
                onClick={() => void handleSavePlacements()}
                data-testid="monster-placement-save"
              >
                {placementsSaving
                  ? libraryCopy.monsterPlacementSaving
                  : libraryCopy.monsterPlacementSave}
              </button>
            </div>
          )}
          {selectedPlacement ? (
            <div
              className="battle-map-editor__monster-selection"
              data-testid="monster-placement-selection"
              data-placement-id={selectedPlacement.clientId}
              data-problem={
                problemPlacementIds.has(selectedPlacement.clientId) ? 'true' : undefined
              }
            >
              <span>{placementDisplayName(selectedPlacement)}</span>
              {templateForPlacement(selectedPlacement.templateRef)?.archived_at ? (
                <span className="badge warning">{libraryCopy.monsterPlacementArchivedBadge}</span>
              ) : null}
              <button
                type="button"
                className="button secondary compact"
                onClick={togglePlacementHidden}
                data-testid="monster-placement-toggle-hidden"
                data-hidden={selectedPlacement.visibility === 'hidden' ? 'true' : undefined}
              >
                {libraryCopy.monsterPlacementVisibilityLabel}:{' '}
                {selectedPlacement.visibility === 'hidden'
                  ? libraryCopy.monsterVisibilityHidden
                  : libraryCopy.monsterVisibilityPublic}
              </button>
              <button
                type="button"
                className="button secondary compact"
                onClick={removeSelectedPlacement}
                data-testid="monster-placement-remove"
              >
                {libraryCopy.monsterPlacementRemove}
              </button>
            </div>
          ) : null}
          {placementsMessage ? (
            <p
              className="battle-map-editor__save-message"
              data-testid="monster-placement-save-message"
            >
              {placementsMessage}
            </p>
          ) : null}
          {placementProblems.length > 0 ? (
            <div
              className="battle-map-editor__monster-problems"
              data-testid="monster-placement-problems"
            >
              <h5>{libraryCopy.monsterPlacementProblemsHeading}</h5>
              <ul>
                {placementProblems.map((problem, index) => {
                  const match = placements.find((p) => p.clientId === problem.placement_id)
                  const label = match
                    ? placementDisplayName(match)
                    : problem.placement_id.slice(0, 8)
                  return (
                    <li
                      key={`${problem.placement_id}-${problem.code}-${index}`}
                      data-placement-id={problem.placement_id}
                      data-problem-code={problem.code}
                    >
                      {label}: {monsterPlacementProblemMessage(problem.code, libraryCopy)}
                    </li>
                  )
                })}
              </ul>
              <p>{libraryCopy.monsterPlacementRetryHint}</p>
            </div>
          ) : null}
        </div>
      ) : null}

      <div
        ref={containerRef}
        className="battle-map-editor__canvas-wrap"
        data-testid="map-editor-canvas"
        style={{ height: canvasHeight }}
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        <BattleMapCanvas
          widthCells={map.width_cells}
          heightCells={map.height_cells}
          walls={canvasWalls}
          doors={canvasDoors}
          terrain={canvasTerrain}
          drawings={working.drawings}
          tokens={monsterMode ? placementTokens : []}
          imageUrl={imageUrl}
          camera={camera}
          isDm={true}
          selectedEntryId={monsterMode ? selectedPlacementId : selectedId}
          selectedObjectId={selectedId}
          highlightSegment={highlightSegment}
          highlightCell={highlightCell}
          highlightObjectId={highlightObjectId}
          previewLine={previewLine}
          previewDrawingPoints={previewDrawingPoints}
          previewDrawingStroke={{ color: penColor, width: penWidth }}
          onCellClick={handleCanvasCellClick}
          onTokenClick={monsterMode ? handlePlacementTokenClick : undefined}
          onWheel={handleWheel}
        />
      </div>
      <div
        className="battle-map-editor__resize-handle"
        role="separator"
        aria-orientation="horizontal"
        aria-label={copy.tacticalMapResize}
        title={copy.tacticalMapResize}
        data-testid="map-editor-resize-handle"
        onPointerDown={startResize}
      />
    </section>
  )
}
