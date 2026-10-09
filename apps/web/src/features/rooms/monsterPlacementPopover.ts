import type { TacticalCamera } from './useTacticalCamera'

/**
 * M07-D D6d: monster-placement popover geometry (library editor).
 *
 * The popover is anchored next to the selected placement token on the
 * canvas. All positioning is pure and unit-tested here; BattleMapEditor
 * only feeds in the token's screen rect (derived from the camera, so it
 * follows pan/zoom and token moves automatically) and the measured wrap
 * size.
 */

export type ScreenRect = { x: number; y: number; width: number; height: number }

export type PopoverSize = { width: number; height: number }

/** Gap between the token edge and the popover card. */
export const PLACEMENT_POPOVER_GAP = 8

/**
 * Estimated popover card size used for flip/clamp math. The card is
 * compact (name + two small buttons + close), so the estimate only needs
 * to keep it inside the wrap; CSS max-width keeps the real card close.
 */
export const PLACEMENT_POPOVER_SIZE: PopoverSize = { width: 232, height: 148 }

/** Pointer travel below which a press on a token is a click, not a drag. */
export const PLACEMENT_DRAG_THRESHOLD_PX = 6

/**
 * Token rect in canvas-wrap pixels. The editor SVG sits at the wrap's
 * top-left at its natural map size with `translate(x, y) scale(zoom)`,
 * so map pixels map to wrap pixels through the camera directly.
 */
export function placementTokenScreenRect(
  anchor_x: number,
  anchor_y: number,
  footprintWidth: number,
  footprintHeight: number,
  cellSize: number,
  camera: TacticalCamera,
): ScreenRect {
  return {
    x: camera.x + anchor_x * cellSize * camera.zoom,
    y: camera.y + anchor_y * cellSize * camera.zoom,
    width: footprintWidth * cellSize * camera.zoom,
    height: footprintHeight * cellSize * camera.zoom,
  }
}

/**
 * Popover top-left in wrap pixels. Prefers the right side of the token,
 * flips to the left when it would overflow, then clamps inside the wrap
 * on both axes. Never returns negative coordinates.
 */
export function placementPopoverPosition(
  token: ScreenRect,
  wrap: { width: number; height: number },
  popover: PopoverSize = PLACEMENT_POPOVER_SIZE,
  gap: number = PLACEMENT_POPOVER_GAP,
): { left: number; top: number } {
  const maxLeft = Math.max(0, wrap.width - popover.width)
  let left = token.x + token.width + gap
  if (left + popover.width > wrap.width) {
    left = token.x - popover.width - gap
  }
  left = Math.min(Math.max(0, left), maxLeft)
  const maxTop = Math.max(0, wrap.height - popover.height)
  const top = Math.min(Math.max(0, token.y), maxTop)
  return { left, top }
}

/** True when the pointer moved far enough to count as a drag. */
export function isPlacementDragBeyondThreshold(
  startClientX: number,
  startClientY: number,
  clientX: number,
  clientY: number,
  thresholdPx: number = PLACEMENT_DRAG_THRESHOLD_PX,
): boolean {
  return Math.hypot(clientX - startClientX, clientY - startClientY) >= thresholdPx
}
