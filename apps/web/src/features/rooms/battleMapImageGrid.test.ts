import { describe, expect, it } from 'vitest'

import {
  battleMapImageRect,
  imageGridFromValues,
  previewGridLines,
  resolveCreateImageGrid,
} from './battleMapImageGrid'

describe('M07-D F13 background-image grid alignment', () => {
  it('maps image pixels to grid cells through the saved alignment', () => {
    // 400x400 image, 40 px per cell, grid origin 5/7 px inside the image.
    const grid = imageGridFromValues(40, 5, 7)!
    expect(grid).toEqual({ pixelSize: 40, offsetX: 5, offsetY: 7 })
    expect(battleMapImageRect(grid, { width: 400, height: 400 }, 40)).toEqual({
      x: -5,
      y: -7,
      width: 400,
      height: 400,
    })
  })

  it('scales the image when a grid cell is not one image pixel wide', () => {
    const grid = imageGridFromValues(20, 5, 0)!
    expect(battleMapImageRect(grid, { width: 200, height: 100 }, 40)).toEqual({
      x: -10,
      y: -0,
      width: 400,
      height: 200,
    })
  })

  it('returns null only when no positive saved size exists', () => {
    expect(imageGridFromValues(null, 0, 0)).toBeNull()
    expect(imageGridFromValues(undefined, 0, 0)).toBeNull()
    expect(imageGridFromValues(0, 0, 0)).toBeNull()
    expect(imageGridFromValues(-8, 0, 0)).toBeNull()
    expect(imageGridFromValues(Number.NaN, 0, 0)).toBeNull()
  })

  it('defaults absent offsets to zero when a positive size is saved', () => {
    expect(imageGridFromValues(40, null, null)).toEqual({ pixelSize: 40, offsetX: 0, offsetY: 0 })
    expect(imageGridFromValues(40, undefined, undefined)).toEqual({
      pixelSize: 40,
      offsetX: 0,
      offsetY: 0,
    })
    expect(imageGridFromValues(40, null, 7)).toEqual({ pixelSize: 40, offsetX: 0, offsetY: 7 })
    // A size-only save renders aligned instead of falling back to stretch.
    const grid = imageGridFromValues(40, null, null)!
    expect(battleMapImageRect(grid, { width: 400, height: 400 }, 40)).toEqual({
      x: -0,
      y: -0,
      width: 400,
      height: 400,
    })
  })

  it('resolves new-upload blanks to the explicit size-40/offset-0 defaults', () => {
    expect(resolveCreateImageGrid('', '', '')).toEqual({ pixelSize: 40, offsetX: 0, offsetY: 0 })
    expect(resolveCreateImageGrid('40', '', '')).toEqual({ pixelSize: 40, offsetX: 0, offsetY: 0 })
    expect(resolveCreateImageGrid('40', '5', '7')).toEqual({ pixelSize: 40, offsetX: 5, offsetY: 7 })
  })

  it('draws overlay lines through the offset on the pixel grid', () => {
    const lines = previewGridLines({ width: 100, height: 100 }, 40, 5, 0)
    const verticals = lines.filter((l) => l.key.startsWith('v-')).map((l) => l.x1)
    const horizontals = lines.filter((l) => l.key.startsWith('h-')).map((l) => l.y1)
    expect(verticals).toEqual([5, 45, 85])
    expect(horizontals).toEqual([0, 40, 80])
    expect(previewGridLines({ width: 100, height: 100 }, 0, 0, 0)).toEqual([])
  })
})
