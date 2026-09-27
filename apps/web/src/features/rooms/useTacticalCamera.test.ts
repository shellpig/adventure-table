import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import {
  applyPan,
  applyZoom,
  clampZoom,
  computeCenterOn,
  computeFitMap,
  MAX_ZOOM,
  MIN_ZOOM,
} from './useTacticalCamera'

describe('useTacticalCamera pure logic', () => {
  it('clamps zoom to bounds', () => {
    expect(clampZoom(10)).toBe(MAX_ZOOM)
    expect(clampZoom(0.01)).toBe(MIN_ZOOM)
    expect(clampZoom(1)).toBe(1)
  })

  it('applyZoom scales around center when provided', () => {
    const camera = { x: 0, y: 0, zoom: 1 }
    const next = applyZoom(camera, 2, 100, 100)
    expect(next.zoom).toBe(2)
    // Point (100,100) stays stable: x = 100 - (100-0)*2 = -100.
    expect(next.x).toBe(-100)
    expect(next.y).toBe(-100)
  })

  it('applyZoom respects max bound and returns same ref when clamped', () => {
    const camera = { x: 0, y: 0, zoom: MAX_ZOOM }
    expect(applyZoom(camera, 2)).toBe(camera)
  })

  it('applyPan moves camera by drag delta', () => {
    const camera = { x: 10, y: 20, zoom: 1 }
    const next = applyPan(camera, 100, 100, 10, 20, 150, 120)
    expect(next.x).toBe(60)
    expect(next.y).toBe(40)
    expect(next.zoom).toBe(1)
  })

  it('computeFitMap centers map in viewport', () => {
    const fit = computeFitMap(800, 600, 800, 600)
    expect(fit).toEqual({ x: 0, y: 0, zoom: 1 })
    const fit2 = computeFitMap(1600, 1200, 800, 600)
    expect(fit2?.zoom).toBe(0.5)
    expect(computeFitMap(0, 600, 800, 600)).toBeNull()
  })

  it('computeCenterOn moves map point to viewport center', () => {
    const camera = { x: 0, y: 0, zoom: 1 }
    const next = computeCenterOn(camera, 400, 300, 800, 600)
    expect(next.x).toBe(0)
    expect(next.y).toBe(0)
  })

  it('camera module performs no network requests', () => {
    // The camera hook must be pure client state: no fetch, no storage.
    const source = readFileSync(new URL('./useTacticalCamera.ts', import.meta.url), 'utf8')
    expect(source).not.toContain('fetch(')
    expect(source).not.toContain('localStorage')
    expect(source).not.toContain('sessionStorage')
    expect(source).not.toMatch(/from '\.\.\/\.\.\/api\//)
  })
})
