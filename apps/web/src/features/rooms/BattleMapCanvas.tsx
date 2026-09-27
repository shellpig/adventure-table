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
  onEmptyMouseDown?: (clientX: number, clientY: number, button: number) => void
  onMouseMove?: (clientX: number, clientY: number) => void
  onMouseUp?: () => void
  onWheel?: (event: { deltaY: number; clientX: number; clientY: number }) => void
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
  onEmptyMouseDown,
  onMouseMove,
  onMouseUp,
  onWheel,
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
      <g data-testid="battle-map-tokens">
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
              style={{ cursor: onTokenClick ? 'pointer' : 'default' }}
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
              >
                {token.name.slice(0, 8)}
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
              style={{ cursor: onCellClick ? 'pointer' : 'default' }}
            />
          )
        })}
      </g>
    </svg>
  )
}
