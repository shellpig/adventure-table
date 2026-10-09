export const MONSTER_LIST_WIDTH_STORAGE_KEY = 'adventure-table.monster-library.list-width.v1'
export const DEFAULT_LIST_WIDTH = 800
export const MIN_LIST_WIDTH = 280
export const MAX_LIST_WIDTH = 1200
export const LIST_KEYBOARD_STEP = 40
// Keep the detail panel usable: the list may never take the last DETAIL_MIN_WIDTH px.
export const DETAIL_MIN_WIDTH = 360
export const SPLITTER_WIDTH = 12

type LayoutStorage = Pick<Storage, 'getItem' | 'setItem'>

export function clampListWidth(width: number, containerWidth?: number): number {
  const maxAvailable =
    typeof containerWidth === 'number' && Number.isFinite(containerWidth)
      ? Math.max(MIN_LIST_WIDTH, Math.floor(containerWidth - SPLITTER_WIDTH - DETAIL_MIN_WIDTH))
      : MAX_LIST_WIDTH
  const maximum = Math.min(MAX_LIST_WIDTH, maxAvailable)
  return Math.min(maximum, Math.max(MIN_LIST_WIDTH, Math.round(width)))
}

export function resolveKeyboardListWidth(
  width: number,
  key: string,
  containerWidth?: number,
): number | null {
  switch (key) {
    case 'ArrowRight':
      return clampListWidth(width + LIST_KEYBOARD_STEP, containerWidth)
    case 'ArrowLeft':
      return clampListWidth(width - LIST_KEYBOARD_STEP, containerWidth)
    case 'Home':
      return clampListWidth(MIN_LIST_WIDTH, containerWidth)
    case 'End':
      return clampListWidth(MAX_LIST_WIDTH, containerWidth)
    default:
      return null
  }
}

function browserStorage(): LayoutStorage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function readListWidth(storage: LayoutStorage | null = browserStorage()): number {
  if (!storage) return DEFAULT_LIST_WIDTH
  try {
    const parsed = Number(storage.getItem(MONSTER_LIST_WIDTH_STORAGE_KEY))
    return Number.isFinite(parsed) && parsed > 0 ? clampListWidth(parsed) : DEFAULT_LIST_WIDTH
  } catch {
    return DEFAULT_LIST_WIDTH
  }
}

export function writeListWidth(
  width: number,
  storage: LayoutStorage | null = browserStorage(),
): void {
  if (!storage) return
  try {
    storage.setItem(MONSTER_LIST_WIDTH_STORAGE_KEY, String(clampListWidth(width)))
  } catch {
    // Layout preference is best-effort client state, never gameplay state.
  }
}
