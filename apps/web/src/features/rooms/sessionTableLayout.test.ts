import { describe, expect, it } from 'vitest'

import {
  clampCardWidth,
  clampSidePanelRatio,
  DEFAULT_CARD_WIDTH,
  DEFAULT_SIDE_PANEL_RATIO,
  MAX_CARD_WIDTH,
  MIN_CARD_WIDTH,
  readCardWidth,
  readSidePanelRatio,
  resolveKeyboardCardWidth,
  resolveKeyboardSidePanelRatio,
  SESSION_CARD_WIDTH_STORAGE_KEY,
  SESSION_SIDE_PANEL_STORAGE_KEY,
  sidePanelRatioFromPointer,
  toggleCardWidth,
  writeCardWidth,
  writeSidePanelRatio,
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
  it('clamps the side panel ratio to its bounds and rounds to 4 decimals', () => {
    expect(clampSidePanelRatio(0.1)).toBe(0.3333)
    expect(clampSidePanelRatio(0.9)).toBe(0.6667)
    expect(clampSidePanelRatio(0.50004)).toBe(0.5)
    expect(clampSidePanelRatio(0.50006)).toBe(0.5001)
  })

  it('converts pointer positions to clamped side panel ratios', () => {
    expect(sidePanelRatioFromPointer(610, 1210, 1210)).toBe(0.5)
    expect(sidePanelRatioFromPointer(0, 1210, 1210)).toBe(0.6667)
    expect(sidePanelRatioFromPointer(1210, 1210, 1210)).toBe(0.3333)
    expect(sidePanelRatioFromPointer(610, 1210, 0)).toBe(DEFAULT_SIDE_PANEL_RATIO)
  })

  it('supports keyboard resizing without escaping layout bounds', () => {
    expect(resolveKeyboardSidePanelRatio(0.5, 'ArrowLeft')).toBe(0.52)
    expect(resolveKeyboardSidePanelRatio(0.5, 'ArrowRight')).toBe(0.48)
    expect(resolveKeyboardSidePanelRatio(0.6667, 'ArrowLeft')).toBe(0.6667)
    expect(resolveKeyboardSidePanelRatio(0.3333, 'ArrowRight')).toBe(0.3333)
    expect(resolveKeyboardSidePanelRatio(0.5, 'Home')).toBe(0.3333)
    expect(resolveKeyboardSidePanelRatio(0.5, 'End')).toBe(0.6667)
    expect(resolveKeyboardSidePanelRatio(0.5, 'Enter')).toBeNull()
  })

  it('persists and restores the client-only side panel ratio under the new key', () => {
    const storage = new MemoryStorage()
    expect(readSidePanelRatio(storage)).toBe(DEFAULT_SIDE_PANEL_RATIO)

    writeSidePanelRatio(0.5, storage)
    expect(storage.getItem(SESSION_SIDE_PANEL_STORAGE_KEY)).toBe('0.5')
    expect(readSidePanelRatio(storage)).toBe(0.5)
  })

  it('clamps persisted ratios, falls back safely, and ignores the old width key', () => {
    const storage = new MemoryStorage()

    storage.setItem(SESSION_SIDE_PANEL_STORAGE_KEY, '0.1')
    expect(readSidePanelRatio(storage)).toBe(0.3333)

    storage.setItem(SESSION_SIDE_PANEL_STORAGE_KEY, '0.9')
    expect(readSidePanelRatio(storage)).toBe(0.6667)

    storage.setItem(SESSION_SIDE_PANEL_STORAGE_KEY, 'not-a-number')
    expect(readSidePanelRatio(storage)).toBe(DEFAULT_SIDE_PANEL_RATIO)

    const oldStorage = new MemoryStorage()
    oldStorage.setItem('adventure-table.session-side-panel-width', '500')
    expect(readSidePanelRatio(oldStorage)).toBe(DEFAULT_SIDE_PANEL_RATIO)
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
