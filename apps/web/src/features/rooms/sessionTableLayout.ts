export const SESSION_SIDE_PANEL_STORAGE_KEY = 'adventure-table.session-side-panel-width'
export const DEFAULT_SIDE_PANEL_WIDTH = 360
export const MIN_SIDE_PANEL_WIDTH = 300
export const MAX_SIDE_PANEL_WIDTH = 720
export const MIN_STAGE_WIDTH = 360
export const DIVIDER_WIDTH = 10
export const SIDE_PANEL_KEYBOARD_STEP = 24

export const SESSION_CARD_WIDTH_STORAGE_KEY = 'adventure-table.session-card-width'
export const DEFAULT_CARD_WIDTH = 1180
export const MIN_CARD_WIDTH = 1180
export const MAX_CARD_WIDTH = 2560
export const CARD_KEYBOARD_STEP = 40
export const CARD_VIEWPORT_PADDING = 32

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
