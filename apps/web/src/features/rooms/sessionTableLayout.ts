export const SESSION_SIDE_PANEL_STORAGE_KEY = 'adventure-table.session-side-panel-ratio'
export const MIN_SIDE_PANEL_RATIO = 1 / 3
export const MAX_SIDE_PANEL_RATIO = 2 / 3
export const DEFAULT_SIDE_PANEL_RATIO = MIN_SIDE_PANEL_RATIO
export const DIVIDER_WIDTH = 10
export const SIDE_PANEL_KEYBOARD_STEP = 0.02

export const SESSION_CARD_WIDTH_STORAGE_KEY = 'adventure-table.session-card-width'
export const DEFAULT_CARD_WIDTH = 1180
export const MIN_CARD_WIDTH = 1180
export const MAX_CARD_WIDTH = 2560
export const CARD_KEYBOARD_STEP = 40
export const CARD_VIEWPORT_PADDING = 32

type LayoutStorage = Pick<Storage, 'getItem' | 'setItem'>

export function clampSidePanelRatio(ratio: number): number {
  const clamped = Math.min(
    MAX_SIDE_PANEL_RATIO,
    Math.max(MIN_SIDE_PANEL_RATIO, ratio),
  )
  return Math.round(clamped * 10000) / 10000
}

export function sidePanelRatioFromPointer(
  clientX: number,
  layoutRight: number,
  layoutWidth: number,
): number {
  const availableWidth = layoutWidth - DIVIDER_WIDTH
  if (availableWidth <= 0) {
    return DEFAULT_SIDE_PANEL_RATIO
  }
  return clampSidePanelRatio((layoutRight - clientX) / availableWidth)
}

export function resolveKeyboardSidePanelRatio(
  ratio: number,
  key: string,
): number | null {
  switch (key) {
    case 'ArrowLeft':
      return clampSidePanelRatio(ratio + SIDE_PANEL_KEYBOARD_STEP)
    case 'ArrowRight':
      return clampSidePanelRatio(ratio - SIDE_PANEL_KEYBOARD_STEP)
    case 'Home':
      return clampSidePanelRatio(MIN_SIDE_PANEL_RATIO)
    case 'End':
      return clampSidePanelRatio(MAX_SIDE_PANEL_RATIO)
    default:
      return null
  }
}

export function clampCardPreference(width: number): number {
  return Math.min(
    MAX_CARD_WIDTH,
    Math.max(MIN_CARD_WIDTH, Math.round(width)),
  )
}

export function clampCardWidth(width: number, viewportWidth?: number): number {
  const maxAvailable =
    typeof viewportWidth === 'number' && Number.isFinite(viewportWidth)
      ? Math.max(MIN_CARD_WIDTH, Math.floor(viewportWidth - CARD_VIEWPORT_PADDING))
      : MAX_CARD_WIDTH
  const maximum = Math.min(MAX_CARD_WIDTH, maxAvailable)
  return Math.min(maximum, Math.max(MIN_CARD_WIDTH, Math.round(width)))
}

export function resolveKeyboardCardWidth(
  width: number,
  key: string,
  viewportWidth?: number,
): number | null {
  const maxAvailable =
    typeof viewportWidth === 'number' && Number.isFinite(viewportWidth)
      ? Math.max(MIN_CARD_WIDTH, Math.floor(viewportWidth - CARD_VIEWPORT_PADDING))
      : MAX_CARD_WIDTH
  const maximum = Math.min(MAX_CARD_WIDTH, maxAvailable)

  switch (key) {
    case 'ArrowRight':
      return clampCardWidth(width + CARD_KEYBOARD_STEP, viewportWidth)
    case 'ArrowLeft':
      return clampCardWidth(width - CARD_KEYBOARD_STEP, viewportWidth)
    case 'Home':
      return clampCardWidth(MIN_CARD_WIDTH, viewportWidth)
    case 'End':
      return clampCardWidth(maximum, viewportWidth)
    default:
      return null
  }
}

export function toggleCardWidth(
  currentWidth: number,
  viewportWidth?: number,
): number {
  const maxAvailable =
    typeof viewportWidth === 'number' && Number.isFinite(viewportWidth)
      ? Math.max(MIN_CARD_WIDTH, Math.floor(viewportWidth - CARD_VIEWPORT_PADDING))
      : MAX_CARD_WIDTH
  const maximum = Math.min(MAX_CARD_WIDTH, maxAvailable)

  if (currentWidth > DEFAULT_CARD_WIDTH + 60) {
    return DEFAULT_CARD_WIDTH
  }
  return maximum
}

function browserStorage(): LayoutStorage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function readSidePanelRatio(storage: LayoutStorage | null = browserStorage()): number {
  if (!storage) return DEFAULT_SIDE_PANEL_RATIO
  try {
    const parsed = Number(storage.getItem(SESSION_SIDE_PANEL_STORAGE_KEY))
    return Number.isFinite(parsed) && parsed > 0
      ? clampSidePanelRatio(parsed)
      : DEFAULT_SIDE_PANEL_RATIO
  } catch {
    return DEFAULT_SIDE_PANEL_RATIO
  }
}

export function writeSidePanelRatio(
  ratio: number,
  storage: LayoutStorage | null = browserStorage(),
): void {
  if (!storage) return
  try {
    storage.setItem(
      SESSION_SIDE_PANEL_STORAGE_KEY,
      String(clampSidePanelRatio(ratio)),
    )
  } catch {
    // Layout preference is best-effort client state, never gameplay state.
  }
}

export function readCardWidth(storage: LayoutStorage | null = browserStorage()): number {
  if (!storage) return DEFAULT_CARD_WIDTH
  try {
    const parsed = Number(storage.getItem(SESSION_CARD_WIDTH_STORAGE_KEY))
    return Number.isFinite(parsed) && parsed > 0
      ? clampCardPreference(parsed)
      : DEFAULT_CARD_WIDTH
  } catch {
    return DEFAULT_CARD_WIDTH
  }
}

export function writeCardWidth(
  width: number,
  storage: LayoutStorage | null = browserStorage(),
): void {
  if (!storage) return
  try {
    storage.setItem(
      SESSION_CARD_WIDTH_STORAGE_KEY,
      String(clampCardPreference(width)),
    )
  } catch {
    // Layout preference is best-effort client state, never gameplay state.
  }
}
