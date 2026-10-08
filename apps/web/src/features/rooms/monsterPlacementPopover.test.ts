import { describe, expect, it } from 'vitest'

import {
  isPlacementDragBeyondThreshold,
  placementPopoverPosition,
  placementTokenScreenRect,
  PLACEMENT_DRAG_THRESHOLD_PX,
  PLACEMENT_POPOVER_GAP,
  PLACEMENT_POPOVER_SIZE,
} from './monsterPlacementPopover'

const camera = { x: 10, y: 20, zoom: 1 }

describe('placementTokenScreenRect', () => {
  it('maps the token footprint through the camera', () => {
    expect(placementTokenScreenRect(2, 3, 1, 1, 40, camera)).toEqual({
      x: 90,
      y: 140,
      width: 40,
      height: 40,
    })
  })

  it('scales multi-cell footprints with zoom', () => {
    expect(
      placementTokenScreenRect(1, 1, 2, 2, 40, { x: 0, y: 0, zoom: 2 }),
    ).toEqual({ x: 80, y: 80, width: 160, height: 160 })
  })
})

describe('placementPopoverPosition', () => {
  const wrap = { width: 800, height: 600 }

  it('prefers the right side of the token with a gap', () => {
    const token = { x: 90, y: 140, width: 40, height: 40 }
    expect(placementPopoverPosition(token, wrap)).toEqual({
      left: 90 + 40 + PLACEMENT_POPOVER_GAP,
      top: 140,
    })
  })

  it('flips to the left side when the right side would overflow', () => {
    const token = { x: 700, y: 100, width: 40, height: 40 }
    const pos = placementPopoverPosition(token, wrap)
    expect(pos.left).toBe(700 - PLACEMENT_POPOVER_SIZE.width - PLACEMENT_POPOVER_GAP)
    expect(pos.left + PLACEMENT_POPOVER_SIZE.width).toBeLessThanOrEqual(wrap.width)
    expect(pos.top).toBe(100)
  })

  it('clamps inside the wrap on every side and never goes negative', () => {
    // Token in the bottom-right corner: flip left, clamp bottom.
    const corner = placementPopoverPosition(
      { x: 780, y: 580, width: 40, height: 40 },
      wrap,
    )
    expect(corner.left).toBeGreaterThanOrEqual(0)
    expect(corner.top).toBeGreaterThanOrEqual(0)
    expect(corner.left + PLACEMENT_POPOVER_SIZE.width).toBeLessThanOrEqual(wrap.width)
    expect(corner.top + PLACEMENT_POPOVER_SIZE.height).toBeLessThanOrEqual(wrap.height)

    // Token at the top-left with a tiny wrap: clamped to the origin.
    const tiny = placementPopoverPosition(
      { x: 0, y: 0, width: 40, height: 40 },
      { width: 100, height: 100 },
    )
    expect(tiny.left).toBe(0)
    expect(tiny.top).toBe(0)
  })
})

describe('isPlacementDragBeyondThreshold', () => {
  it('treats sub-pixel click jitter as a click, not a drag', () => {
    expect(isPlacementDragBeyondThreshold(100, 100, 102, 101)).toBe(false)
    expect(
      isPlacementDragBeyondThreshold(
        100,
        100,
        100 + PLACEMENT_DRAG_THRESHOLD_PX,
        100,
      ),
    ).toBe(true)
    expect(isPlacementDragBeyondThreshold(100, 100, 200, 200)).toBe(true)
  })
})
