export const SESSION_SIDE_PANEL_STORAGE_KEY = 'adventure-table.session-side-panel-width'
export const DEFAULT_SIDE_PANEL_WIDTH = 360
export const MIN_SIDE_PANEL_WIDTH = 300
export const MAX_SIDE_PANEL_WIDTH = 560
export const MIN_STAGE_WIDTH = 360
export const DIVIDER_WIDTH = 10
export const SIDE_PANEL_KEYBOARD_STEP = 24

type LayoutStorage = Pick<Storage, 'getItem' | 'setItem'>

export function clampSidePanelPreference(width: number): number {
  return Math.min(
    MAX_SIDE_PANEL_WIDTH,
    Math.max(MIN_SIDE_PANEL_WIDTH, Math.round(width)),
  )
}

export function clampSidePanelWidth(width: number, containerWidth: number): number {
  const availableMaximum = Math.max(
    MIN_SIDE_PANEL_WIDTH,
    Math.floor(containerWidth - MIN_STAGE_WIDTH - DIVIDER_WIDTH),
  )
  const maximum = Math.min(MAX_SIDE_PANEL_WIDTH, availableMaximum)
  return Math.min(maximum, Math.max(MIN_SIDE_PANEL_WIDTH, Math.round(width)))
}

export function resolveKeyboardSidePanelWidth(
  width: number,
  key: string,
  containerWidth: number,
): number | null {
  switch (key) {
    case 'ArrowLeft':
      return clampSidePanelWidth(width + SIDE_PANEL_KEYBOARD_STEP, containerWidth)
    case 'ArrowRight':
      return clampSidePanelWidth(width - SIDE_PANEL_KEYBOARD_STEP, containerWidth)
    case 'Home':
      return clampSidePanelWidth(MIN_SIDE_PANEL_WIDTH, containerWidth)
    case 'End':
      return clampSidePanelWidth(MAX_SIDE_PANEL_WIDTH, containerWidth)
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

export function readSidePanelWidth(storage: LayoutStorage | null = browserStorage()): number {
  if (!storage) return DEFAULT_SIDE_PANEL_WIDTH
  try {
    const parsed = Number(storage.getItem(SESSION_SIDE_PANEL_STORAGE_KEY))
    return Number.isFinite(parsed) && parsed > 0
      ? clampSidePanelPreference(parsed)
      : DEFAULT_SIDE_PANEL_WIDTH
  } catch {
    return DEFAULT_SIDE_PANEL_WIDTH
  }
}

export function writeSidePanelWidth(
  width: number,
  storage: LayoutStorage | null = browserStorage(),
): void {
  if (!storage) return
  try {
    storage.setItem(
      SESSION_SIDE_PANEL_STORAGE_KEY,
      String(clampSidePanelPreference(width)),
    )
  } catch {
    // Layout preference is best-effort client state, never gameplay state.
  }
}
