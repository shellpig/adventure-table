import { describe, expect, it } from 'vitest'

import {
  clampCardWidth,
  clampSidePanelWidth,
  DEFAULT_CARD_WIDTH,
  DEFAULT_SIDE_PANEL_WIDTH,
  MAX_CARD_WIDTH,
  MAX_SIDE_PANEL_WIDTH,
  MIN_CARD_WIDTH,
  MIN_SIDE_PANEL_WIDTH,
  readCardWidth,
  readSidePanelWidth,
  resolveKeyboardCardWidth,
  resolveKeyboardSidePanelWidth,
  SESSION_CARD_WIDTH_STORAGE_KEY,
  SESSION_SIDE_PANEL_STORAGE_KEY,
  toggleCardWidth,
  writeCardWidth,
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

  it('clamps persisted widths and falls back safely for invalid values', () => {
    const storage = new MemoryStorage()

    storage.setItem(SESSION_SIDE_PANEL_STORAGE_KEY, '100')
    expect(readSidePanelWidth(storage)).toBe(MIN_SIDE_PANEL_WIDTH)

    storage.setItem(SESSION_SIDE_PANEL_STORAGE_KEY, '900')
    expect(readSidePanelWidth(storage)).toBe(MAX_SIDE_PANEL_WIDTH)

    storage.setItem(SESSION_SIDE_PANEL_STORAGE_KEY, 'not-a-number')
    expect(readSidePanelWidth(storage)).toBe(DEFAULT_SIDE_PANEL_WIDTH)
  })

  it('supports keyboard resizing without escaping layout bounds', () => {
    expect(resolveKeyboardSidePanelWidth(360, 'ArrowLeft', 1200)).toBe(384)
    expect(resolveKeyboardSidePanelWidth(360, 'ArrowRight', 1200)).toBe(336)
    expect(resolveKeyboardSidePanelWidth(MIN_SIDE_PANEL_WIDTH, 'ArrowRight', 1200)).toBe(
      MIN_SIDE_PANEL_WIDTH,
    )
    expect(resolveKeyboardSidePanelWidth(MAX_SIDE_PANEL_WIDTH, 'ArrowLeft', 1200)).toBe(
      MAX_SIDE_PANEL_WIDTH,
    )
    expect(resolveKeyboardSidePanelWidth(400, 'Home', 1200)).toBe(MIN_SIDE_PANEL_WIDTH)
    expect(resolveKeyboardSidePanelWidth(400, 'End', 1200)).toBe(MAX_SIDE_PANEL_WIDTH)
    expect(resolveKeyboardSidePanelWidth(400, 'Enter', 1200)).toBeNull()
  })

  it('clamps the card width to its bounds and viewport constraints', () => {
    expect(clampCardWidth(900)).toBe(MIN_CARD_WIDTH)
    expect(clampCardWidth(1400)).toBe(1400)
    expect(clampCardWidth(3000)).toBe(MAX_CARD_WIDTH)
    expect(clampCardWidth(2000, 1600)).toBe(1568)
    expect(clampCardWidth(800, 1000)).toBe(MIN_CARD_WIDTH)
  })

  it('persists and restores client-only card width', () => {
    const storage = new MemoryStorage()
    expect(readCardWidth(storage)).toBe(DEFAULT_CARD_WIDTH)

    writeCardWidth(1440.4, storage)
    expect(storage.getItem(SESSION_CARD_WIDTH_STORAGE_KEY)).toBe('1440')
    expect(readCardWidth(storage)).toBe(1440)
  })

  it('clamps persisted card widths and falls back safely', () => {
    const storage = new MemoryStorage()

    storage.setItem(SESSION_CARD_WIDTH_STORAGE_KEY, '800')
    expect(readCardWidth(storage)).toBe(MIN_CARD_WIDTH)

    storage.setItem(SESSION_CARD_WIDTH_STORAGE_KEY, '5000')
    expect(readCardWidth(storage)).toBe(MAX_CARD_WIDTH)

    storage.setItem(SESSION_CARD_WIDTH_STORAGE_KEY, 'not-a-number')
    expect(readCardWidth(storage)).toBe(DEFAULT_CARD_WIDTH)
  })

  it('supports keyboard resizing for card width', () => {
    expect(resolveKeyboardCardWidth(1200, 'ArrowRight', 1920)).toBe(1240)
    expect(resolveKeyboardCardWidth(1200, 'ArrowLeft', 1920)).toBe(1180)
    expect(resolveKeyboardCardWidth(1180, 'ArrowLeft', 1920)).toBe(1180)
    expect(resolveKeyboardCardWidth(1400, 'Home', 1920)).toBe(MIN_CARD_WIDTH)
    expect(resolveKeyboardCardWidth(1400, 'End', 1920)).toBe(1888)
    expect(resolveKeyboardCardWidth(1400, 'Enter', 1920)).toBeNull()
  })

  it('toggles card width between default and max available', () => {
    expect(toggleCardWidth(DEFAULT_CARD_WIDTH, 1920)).toBe(1888)
    expect(toggleCardWidth(1600, 1920)).toBe(DEFAULT_CARD_WIDTH)
  })
})
