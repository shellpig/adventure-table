import type { Locale } from '../../i18n/locale'

export const CHAT_SPEAKER_COLORS_STORAGE_KEY = 'adventure-table.chat-speaker-colors'

export type ChatColorItem = {
  value: string
  label: Record<Locale, string>
}

export const CHAT_COLOR_PALETTE: readonly ChatColorItem[] = [
  { value: '#f8fafc', label: { 'zh-TW': '雪白', en: 'Snow White' } },
  { value: '#cbd5e1', label: { 'zh-TW': '皓銀', en: 'Silver Gray' } },
  { value: '#facc15', label: { 'zh-TW': '金黃', en: 'Radiant Gold' } },
  { value: '#fb923c', label: { 'zh-TW': '琥珀', en: 'Amber Orange' } },
  { value: '#f87171', label: { 'zh-TW': '赤紅', en: 'Coral Red' } },
  { value: '#fb7185', label: { 'zh-TW': '緋櫻', en: 'Rose Blossom' } },
  { value: '#f472b6', label: { 'zh-TW': '桃粉', en: 'Flaming Pink' } },
  { value: '#e879f9', label: { 'zh-TW': '洋紅', en: 'Orchid Magenta' } },
  { value: '#c084fc', label: { 'zh-TW': '丁香', en: 'Mystic Lilac' } },
  { value: '#a78bfa', label: { 'zh-TW': '紫藤', en: 'Lavender Violet' } },
  { value: '#60a5fa', label: { 'zh-TW': '蔚藍', en: 'Cerulean Blue' } },
  { value: '#38bdf8', label: { 'zh-TW': '天青', en: 'Sky Cyan' } },
  { value: '#2dd4bf', label: { 'zh-TW': '翠綠', en: 'Mint Teal' } },
  { value: '#4ade80', label: { 'zh-TW': '碧草', en: 'Emerald Green' } },
  { value: '#a3e635', label: { 'zh-TW': '青檸', en: 'Lime Glow' } },
  { value: '#fed7aa', label: { 'zh-TW': '杏褐', en: 'Warm Sand' } },
] as const

export const DEFAULT_CHAT_COLOR = '#f8fafc'

type LayoutStorage = Pick<Storage, 'getItem' | 'setItem'>

function browserStorage(): LayoutStorage | null {
  if (typeof window !== 'undefined') {
    try {
      return window.localStorage
    } catch {
      return null
    }
  }
  if (typeof globalThis !== 'undefined' && 'localStorage' in globalThis) {
    try {
      return (globalThis as unknown as { localStorage: LayoutStorage }).localStorage
    } catch {
      return null
    }
  }
  return null
}

export function isValidChatColor(color: string): boolean {
  return CHAT_COLOR_PALETTE.some((item) => item.value.toLowerCase() === color.toLowerCase())
}

export function readSpeakerColors(
  storage: LayoutStorage | null = browserStorage(),
): Record<string, string> {
  if (!storage) return {}
  try {
    const raw = storage.getItem(CHAT_SPEAKER_COLORS_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    if (typeof parsed !== 'object' || parsed === null) return {}
    const result: Record<string, string> = {}
    for (const [key, val] of Object.entries(parsed)) {
      if (typeof key === 'string' && typeof val === 'string' && isValidChatColor(val)) {
        result[key] = val
      }
    }
    return result
  } catch {
    return {}
  }
}

export function writeSpeakerColor(
  speakerKey: string,
  color: string,
  storage: LayoutStorage | null = browserStorage(),
): Record<string, string> {
  if (!storage || !speakerKey || !isValidChatColor(color)) return readSpeakerColors(storage)
  try {
    const current = readSpeakerColors(storage)
    const next = { ...current, [speakerKey]: color }
    storage.setItem(CHAT_SPEAKER_COLORS_STORAGE_KEY, JSON.stringify(next))
    return next
  } catch {
    return readSpeakerColors(storage)
  }
}
