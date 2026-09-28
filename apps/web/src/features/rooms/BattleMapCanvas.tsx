import type { TacticalCamera } from './useTacticalCamera'

export type CanvasWall = {
  x1: number
  y1: number
  x2: number
  y2: number
  visibility?: 'public' | 'hidden'
}

export type CanvasDoor = {
  door_id: string | null
  x1: number
  y1: number
  x2: number
  y2: number
  state: string
  revealed: boolean
  isHidden?: boolean
}

export type CanvasTerrain = {
  x: number
  y: number
  terrain_kind: string
}

export type CanvasToken = {
  entry_id: string
  name: string
  anchor_x: number
  anchor_y: number
  footprint_width: number
  footprint_height: number
}

type BattleMapCanvasProps = {
  widthCells: number
  heightCells: number
  cellSize?: number
  walls: CanvasWall[]
  doors: CanvasDoor[]
  terrain: CanvasTerrain[]
  tokens: CanvasToken[]
  imageUrl?: string | null
  camera: TacticalCamera
  isDm: boolean
  selectedEntryId?: string | null
  onCellClick?: (x: number, y: number) => void
  onTokenClick?: (entryId: string) => void
  /** Pointer pressed on a token: start a drag (e.g. movement plan). */
  onTokenPointerDown?: (entryId: string) => void
  /** Pointer entered a cell while dragging (accumulates drag anchors). */
  onCellPointerEnter?: (x: number, y: number) => void
  onPointerUp?: () => void
  onDoorClick?: (doorId: string | null) => void
  onEmptyMouseDown?: (clientX: number, clientY: number, button: number) => void
  onMouseMove?: (clientX: number, clientY: number) => void
  onMouseUp?: () => void
  onWheel?: (event: { deltaY: number; clientX: number; clientY: number }) => void
  /** AoE template overlay cells (server preview). */
  aoeCells?: Array<{ x: number; y: number }>
  aoeOrigin?: { x: number; y: number } | null
  /** Whether tokens intercept pointer events (false during AoE targeting). */
  tokensInteractive?: boolean
}

const TERRAIN_COLORS: Record<string, string> = {
  difficult: '#d4a574',
  water: '#7ec8e3',
  lava: '#e74c3c',
}

function terrainColor(kind: string): string {
  return TERRAIN_COLORS[kind] ?? '#b8b8b8'
}

export function BattleMapCanvas({
  widthCells,
  heightCells,
  cellSize = 40,
  walls,
  doors,
  terrain,
  tokens,
  imageUrl,
  camera,
  isDm,
  selectedEntryId,
  onCellClick,
  onTokenClick,
  onTokenPointerDown,
  onCellPointerEnter,
  onPointerUp,
  onDoorClick,
  onEmptyMouseDown,
  onMouseMove,
  onMouseUp,
  onWheel,
  aoeCells,
  aoeOrigin,
  tokensInteractive = true,
}: BattleMapCanvasProps) {
  const mapWidth = widthCells * cellSize
  const mapHeight = heightCells * cellSize

  const gridLines: React.ReactNode[] = []
  for (let x = 0; x <= widthCells; x++) {
    gridLines.push(
      <line
        key={`v-${x}`}
        x1={x * cellSize}
        y1={0}
        x2={x * cellSize}
        y2={mapHeight}
        className="battle-map__grid-line"
      />,
    )
  }
  for (let y = 0; y <= heightCells; y++) {
    gridLines.push(
      <line
        key={`h-${y}`}
        x1={0}
        y1={y * cellSize}
        x2={mapWidth}
        y2={y * cellSize}
        className="battle-map__grid-line"
      />,
    )
  }

  const handleCellClick = (event: React.MouseEvent<SVGRectElement>, x: number, y: number) => {
    event.stopPropagation()
    onCellClick?.(x, y)
  }

  return (
    <svg
      className="battle-map"
      data-testid="battle-map"
      data-map-width={widthCells}
      data-map-height={heightCells}
      viewBox={`0 0 ${mapWidth} ${mapHeight}`}
      style={{
        transform: `translate(${camera.x}px, ${camera.y}px) scale(${camera.zoom})`,
        transformOrigin: '0 0',
      }}
      onMouseDown={(e) => {
        // Middle mouse (button 1) or drag on empty space starts pan.
        if (e.button === 1 || e.target === e.currentTarget) {
          onEmptyMouseDown?.(e.clientX, e.clientY, e.button)
        }
      }}
      onMouseMove={(e) => onMouseMove?.(e.clientX, e.clientY)}
      onMouseUp={() => onMouseUp?.()}
      onPointerUp={() => onPointerUp?.()}
      onPointerCancel={() => onPointerUp?.()}
      onWheel={(e) => {
        e.preventDefault()
        onWheel?.({ deltaY: e.deltaY, clientX: e.clientX, clientY: e.clientY })
      }}
    >
      {imageUrl ? (
        <image
          href={imageUrl}
          x={0}
          y={0}
          width={mapWidth}
          height={mapHeight}
          data-testid="battle-map-image"
          preserveAspectRatio="none"
        />
      ) : null}
      <g data-testid="battle-map-grid">{gridLines}</g>
      <g data-testid="battle-map-terrain">
        {terrain.map((t, index) => (
          <rect
            key={`terrain-${index}`}
            data-testid="battle-map-terrain-cell"
            data-terrain-kind={t.terrain_kind}
            x={t.x * cellSize}
            y={t.y * cellSize}
            width={cellSize}
            height={cellSize}
            fill={terrainColor(t.terrain_kind)}
            opacity={0.5}
          />
        ))}
      </g>
      <g data-testid="battle-map-walls">
        {walls.map((wall, index) => {
          const isHidden = wall.visibility === 'hidden'
          return (
            <line
              key={`wall-${index}`}
              data-testid="battle-map-wall"
              data-hidden={isHidden && isDm ? 'true' : undefined}
              x1={wall.x1 * cellSize}
              y1={wall.y1 * cellSize}
              x2={wall.x2 * cellSize}
              y2={wall.y2 * cellSize}
              className={`battle-map__wall${isHidden && isDm ? ' battle-map__wall--hidden' : ''}`}
              strokeWidth={4}
            />
          )
        })}
      </g>
      <g data-testid="battle-map-doors">
        {doors.map((door, index) => {
          const isHidden = door.isHidden === true
          return (
            <g
              key={`door-${door.door_id ?? index}`}
              data-testid="battle-map-door"
              data-door-id={door.door_id ?? undefined}
              data-hidden={isHidden && isDm ? 'true' : undefined}
              className={`battle-map__door${isHidden && isDm ? ' battle-map__door--hidden' : ''}`}
              onClick={(e) => {
                e.stopPropagation()
                onDoorClick?.(door.door_id)
              }}
              style={{ cursor: onDoorClick ? 'pointer' : 'default' }}
            >
              <line
                x1={door.x1 * cellSize}
                y1={door.y1 * cellSize}
                x2={door.x2 * cellSize}
                y2={door.y2 * cellSize}
                strokeWidth={6}
              />
              <text
                x={((door.x1 + door.x2) / 2) * cellSize}
                y={((door.y1 + door.y2) / 2) * cellSize}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize={10}
              >
                {door.state}
              </text>
            </g>
          )
        })}
      </g>
      <g data-testid="battle-map-cells">
        {Array.from({ length: widthCells * heightCells }, (_, i) => {
          const x = i % widthCells
          const y = Math.floor(i / widthCells)
          return (
            <rect
              key={`cell-${x}-${y}`}
              data-testid="battle-map-cell"
              data-cell-x={x}
              data-cell-y={y}
              x={x * cellSize}
              y={y * cellSize}
              width={cellSize}
              height={cellSize}
              fill="transparent"
              onClick={(e) => handleCellClick(e, x, y)}
              onPointerEnter={() => onCellPointerEnter?.(x, y)}
              style={{ cursor: onCellClick ? 'pointer' : 'default' }}
            />
          )
        })}
      </g>
      <g
        data-testid="battle-map-tokens"
        pointerEvents={tokensInteractive ? undefined : 'none'}
        style={tokensInteractive ? undefined : { pointerEvents: 'none' }}
      >
        {tokens.map((token) => {
          const isSelected = token.entry_id === selectedEntryId
          return (
            <g
              key={token.entry_id}
              data-testid="battle-map-token"
              data-entry-id={token.entry_id}
              data-selected={isSelected ? 'true' : undefined}
              className={`battle-map__token${isSelected ? ' battle-map__token--selected' : ''}`}
              onClick={(e) => {
                e.stopPropagation()
                onTokenClick?.(token.entry_id)
              }}
              onPointerDown={(e) => {
                // Left button only; a drag plans movement, it never confirms.
                if (e.button !== 0 || !onTokenPointerDown) return
                e.stopPropagation()
                onTokenPointerDown(token.entry_id)
              }}
              style={{ cursor: onTokenClick ? 'pointer' : 'default', touchAction: 'none' }}
            >
              <rect
                x={token.anchor_x * cellSize}
                y={token.anchor_y * cellSize}
                width={token.footprint_width * cellSize}
                height={token.footprint_height * cellSize}
                rx={4}
              />
              <text
                x={(token.anchor_x + token.footprint_width / 2) * cellSize}
                y={(token.anchor_y + token.footprint_height / 2) * cellSize}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize={11}
                // Long names overflow the token; the label must not swallow clicks on neighbouring cells.
                pointerEvents="none"
              >
                {token.name}
              </text>
            </g>
          )
        })}
      </g>
      {aoeCells && aoeCells.length > 0 ? (
        <g data-testid="battle-map-aoe-cells" pointerEvents="none">
          {aoeCells.map((cell) => (
            <rect
              key={`aoe-${cell.x}-${cell.y}`}
              data-testid="battle-map-aoe-cell"
              data-cell-x={cell.x}
              data-cell-y={cell.y}
              x={cell.x * cellSize}
              y={cell.y * cellSize}
              width={cellSize}
              height={cellSize}
              fill="#a855f7"
              opacity={0.35}
            />
          ))}
        </g>
      ) : null}
      {aoeOrigin ? (
        <g data-testid="battle-map-aoe-origin" pointerEvents="none">
          <rect
            x={aoeOrigin.x * cellSize}
            y={aoeOrigin.y * cellSize}
            width={cellSize}
            height={cellSize}
            fill="none"
            stroke="#a855f7"
            strokeWidth={3}
          />
        </g>
      ) : null}
    </svg>
  )
}
