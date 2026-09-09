import { describe, expect, it } from 'vitest'

import {
  DEFAULT_SIDE_PANEL_WIDTH,
  MAX_SIDE_PANEL_WIDTH,
  MIN_SIDE_PANEL_WIDTH,
  SESSION_SIDE_PANEL_STORAGE_KEY,
  clampSidePanelWidth,
  readSidePanelWidth,
  writeSidePanelWidth,
} from './sessionTableLayout'

class MemoryStorage {
  private readonly values = new Map<string, string>()

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value)
  }
}

describe('P3-B Session table layout preference', () => {
  it('clamps the side panel to its product bounds and preserves Main Stage space', () => {
    expect(clampSidePanelWidth(100, 1200)).toBe(MIN_SIDE_PANEL_WIDTH)
    expect(clampSidePanelWidth(900, 1400)).toBe(MAX_SIDE_PANEL_WIDTH)
    expect(clampSidePanelWidth(500, 760)).toBe(390)
  })

  it('persists and restores the client-only side panel width', () => {
    const storage = new MemoryStorage()
    expect(readSidePanelWidth(storage)).toBe(DEFAULT_SIDE_PANEL_WIDTH)

    writeSidePanelWidth(412.4, storage)
    expect(storage.getItem(SESSION_SIDE_PANEL_STORAGE_KEY)).toBe('412')
    expect(readSidePanelWidth(storage)).toBe(412)
  })

  it('falls back safely for invalid persisted values', () => {
    const storage = new MemoryStorage()
    storage.setItem(SESSION_SIDE_PANEL_STORAGE_KEY, 'not-a-number')
    expect(readSidePanelWidth(storage)).toBe(DEFAULT_SIDE_PANEL_WIDTH)
  })
})
