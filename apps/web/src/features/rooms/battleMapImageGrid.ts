import { useEffect, useState } from 'react'

/**
 * M07-D D2 (F13): background-image grid alignment.
 *
 * Semantics (frontend-defined; the server stores the three fields but never
 * renders): image pixel `(offsetX, offsetY)` sits exactly on the grid origin
 * (the top-left corner of cell (0, 0)), and one grid cell spans `pixelSize`
 * image pixels. Rule distances are unaffected: 1 cell is still 5 ft.
 */
export type ImageGridAlignment = {
  pixelSize: number
  offsetX: number
  offsetY: number
}

export type ImageNaturalSize = {
  width: number
  height: number
}

/** Image rectangle in map pixels for the SVG `<image>` element. */
export type ImageMapRect = {
  x: number
  y: number
  width: number
  height: number
}

/**
 * Alignment from possibly-missing values. A positive pixel size aligns the
 * image; absent offsets default to zero so a size-only save still renders
 * aligned. Returns null only when no positive saved size exists (legacy
 * stretch-to-grid rendering) or any present value is not finite.
 * Zero/negative sizes stay invalid.
 */
export function imageGridFromValues(
  pixelSize: number | null | undefined,
  offsetX: number | null | undefined,
  offsetY: number | null | undefined,
): ImageGridAlignment | null {
  if (
    typeof pixelSize !== 'number' ||
    !Number.isFinite(pixelSize) ||
    pixelSize <= 0
  ) {
    return null
  }
  const ox = offsetX ?? 0
  const oy = offsetY ?? 0
  if (
    typeof ox !== 'number' ||
    !Number.isFinite(ox) ||
    typeof oy !== 'number' ||
    !Number.isFinite(oy)
  ) {
    return null
  }
  return { pixelSize, offsetX: ox, offsetY: oy }
}

/** Explicit new-upload defaults so the create preview and payload agree. */
export const CREATE_IMAGE_GRID_DEFAULTS = {
  pixelSize: 40,
  offsetX: 0,
  offsetY: 0,
} as const

/**
 * Effective grid for a new image-map upload. Empty inputs fall back to the
 * explicit defaults (size 40, offsets 0); anything else must already be valid
 * (callers gate the save on isValid* helpers, keeping zero/negative invalid).
 */
export function resolveCreateImageGrid(
  sizeRaw: string,
  offsetXRaw: string,
  offsetYRaw: string,
): ImageGridAlignment {
  return {
    pixelSize: parseGridPixelSizeInput(sizeRaw) ?? CREATE_IMAGE_GRID_DEFAULTS.pixelSize,
    offsetX: parseGridOffsetInput(offsetXRaw) ?? CREATE_IMAGE_GRID_DEFAULTS.offsetX,
    offsetY: parseGridOffsetInput(offsetYRaw) ?? CREATE_IMAGE_GRID_DEFAULTS.offsetY,
  }
}

export function battleMapImageRect(
  grid: ImageGridAlignment,
  natural: ImageNaturalSize,
  cellSize: number,
): ImageMapRect {
  const scale = cellSize / grid.pixelSize
  return {
    x: -grid.offsetX * scale,
    y: -grid.offsetY * scale,
    width: natural.width * scale,
    height: natural.height * scale,
  }
}

export type PreviewGridLine = {
  key: string
  x1: number
  y1: number
  x2: number
  y2: number
}

/**
 * Grid overlay lines over an image in its own pixel space: verticals at
 * `offsetX + k * pixelSize`, horizontals at `offsetY + k * pixelSize`.
 */
export function previewGridLines(
  natural: ImageNaturalSize,
  pixelSize: number,
  offsetX: number,
  offsetY: number,
): PreviewGridLine[] {
  const lines: PreviewGridLine[] = []
  if (!(pixelSize > 0)) return lines
  const firstVertical = offsetX - Math.ceil(offsetX / pixelSize) * pixelSize
  for (let x = firstVertical; x <= natural.width; x += pixelSize) {
    if (x < 0) continue
    lines.push({ key: `v-${x}`, x1: x, y1: 0, x2: x, y2: natural.height })
  }
  const firstHorizontal = offsetY - Math.ceil(offsetY / pixelSize) * pixelSize
  for (let y = firstHorizontal; y <= natural.height; y += pixelSize) {
    if (y < 0) continue
    lines.push({ key: `h-${y}`, x1: 0, y1: y, x2: natural.width, y2: y })
  }
  return lines
}

/** Natural pixel size of an image URL; null while loading, on error, or unset. */
export function useImageNaturalSize(url: string | null | undefined): ImageNaturalSize | null {
  const [loaded, setLoaded] = useState<{ url: string; size: ImageNaturalSize } | null>(null)
  useEffect(() => {
    if (!url) {
      setLoaded(null)
      return
    }
    let active = true
    const image = new Image()
    image.onload = () => {
      if (!active) return
      setLoaded({ url, size: { width: image.naturalWidth, height: image.naturalHeight } })
    }
    image.onerror = () => {
      if (active) setLoaded(null)
    }
    image.src = url
    return () => {
      active = false
    }
  }, [url])
  return loaded && loaded.url === url ? loaded.size : null
}

/**
 * Grid field input parsing shared by the upload modal and the editor grid
 * panel. Empty means "no saved value"; anything else must be an integer
 * (positive for the pixel size).
 */
export function parseGridPixelSizeInput(raw: string): number | null {
  if (raw.trim() === '') return null
  const value = Number(raw)
  return Number.isInteger(value) && value > 0 ? value : null
}

export function parseGridOffsetInput(raw: string): number | null {
  if (raw.trim() === '') return null
  const value = Number(raw)
  return Number.isInteger(value) ? value : null
}

export function isValidGridPixelSizeInput(raw: string): boolean {
  if (raw.trim() === '') return true
  return parseGridPixelSizeInput(raw) !== null
}

export function isValidGridOffsetInput(raw: string): boolean {
  if (raw.trim() === '') return true
  return parseGridOffsetInput(raw) !== null
}
