import { describe, expect, it } from 'vitest'

import {
  CHAT_COLOR_PALETTE,
  CHAT_SPEAKER_COLORS_STORAGE_KEY,
  DEFAULT_CHAT_COLOR,
  isValidChatColor,
  readSpeakerColors,
  writeSpeakerColor,
} from './chatColors'

class MemoryStorage {
  private readonly values = new Map<string, string>()

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value)
  }
}

describe('Chat Speaker 16-Color Palette', () => {
  it('provides exactly 16 distinct high-contrast colors with bilingual labels', () => {
    expect(CHAT_COLOR_PALETTE).toHaveLength(16)
    const uniqueValues = new Set(CHAT_COLOR_PALETTE.map((c) => c.value.toLowerCase()))
    expect(uniqueValues.size).toBe(16)

    for (const color of CHAT_COLOR_PALETTE) {
      expect(color.value).toMatch(/^#[0-9a-f]{6}$/i)
      expect(color.label['zh-TW']).toBeTruthy()
      expect(color.label.en).toBeTruthy()
      expect(isValidChatColor(color.value)).toBe(true)
    }
  })

  it('rejects invalid or non-palette hex colors', () => {
    expect(isValidChatColor('#000000')).toBe(false)
    expect(isValidChatColor('red')).toBe(false)
    expect(isValidChatColor('')).toBe(false)
    expect(isValidChatColor('#123456')).toBe(false)
  })

  it('reads and writes speaker colors to storage', () => {
    const storage = new MemoryStorage()
    expect(readSpeakerColors(storage)).toEqual({})

    writeSpeakerColor('seat-1', '#facc15', storage)
    expect(readSpeakerColors(storage)).toEqual({ 'seat-1': '#facc15' })

    writeSpeakerColor('dm', '#38bdf8', storage)
    expect(readSpeakerColors(storage)).toEqual({
      'seat-1': '#facc15',
      dm: '#38bdf8',
    })
    expect(storage.getItem(CHAT_SPEAKER_COLORS_STORAGE_KEY)).toContain('"dm":"#38bdf8"')
  })

  it('ignores invalid colors and corrupted storage entries safely', () => {
    const storage = new MemoryStorage()
    storage.setItem(
      CHAT_SPEAKER_COLORS_STORAGE_KEY,
      JSON.stringify({ 'seat-1': '#000000', 'seat-2': '#2dd4bf', bad: 123 }),
    )

    const colors = readSpeakerColors(storage)
    expect(colors).toEqual({ 'seat-2': '#2dd4bf' })

    writeSpeakerColor('seat-3', '#invalid', storage)
    expect(readSpeakerColors(storage)).toEqual({ 'seat-2': '#2dd4bf' })
  })

  it('falls back safely when storage is null or throws', () => {
    expect(readSpeakerColors(null)).toEqual({})
    expect(writeSpeakerColor('seat-1', '#facc15', null)).toEqual({})
  })
})
