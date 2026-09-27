import type { TableEvent } from '../../api/sessions'
import type { TargetCheckResult } from '../../api/tacticalCombat'
import { isCombatEvent } from './sessionCombat'

/**
 * Pure decision logic for the Tactical map panel (P5-F F3b).
 *
 * These functions contain no React state or side effects so they can be
 * unit-tested directly. Every one is used by TacticalMapPanel.
 */

export type MapMode =
  | { kind: 'idle' }
  | { kind: 'placement'; entryId: string }
  | { kind: 'move'; entryId: string }
  | { kind: 'reposition' }
  | { kind: 'aoe-origin' }
  | { kind: 'aoe-aim' }

export type CellClickAction =
  | { action: 'place'; x: number; y: number }
  | { action: 'add-anchor'; x: number; y: number }
  | { action: 'set-reposition-target'; x: number; y: number }
  | { action: 'set-aoe-origin'; x: number; y: number }
  | { action: 'set-aoe-aim'; x: number; y: number }
  | { action: 'none' }

/** Decide what a map cell click does in the current mode. */
export function cellClickAction(mode: MapMode, x: number, y: number): CellClickAction {
  switch (mode.kind) {
    case 'placement':
      return { action: 'place', x, y }
    case 'move':
      return { action: 'add-anchor', x, y }
    case 'reposition':
      return { action: 'set-reposition-target', x, y }
    case 'aoe-origin':
      return { action: 'set-aoe-origin', x, y }
    case 'aoe-aim':
      return { action: 'set-aoe-aim', x, y }
    case 'idle':
      return { action: 'none' }
  }
}

/** Append an anchor, dropping consecutive duplicates. Pure. */
export function appendAnchor(
  anchors: Array<{ x: number; y: number }>,
  x: number,
  y: number,
): Array<{ x: number; y: number }> {
  const last = anchors[anchors.length - 1]
  if (last && last.x === x && last.y === y) return anchors
  return [...anchors, { x, y }]
}

/** Convert a drag cell sequence into anchors (dedup consecutive). Pure. */
export function dragCellsToAnchors(
  cells: Array<{ x: number; y: number }>,
): Array<{ x: number; y: number }> {
  const out: Array<{ x: number; y: number }> = []
  for (const c of cells) {
    const last = out[out.length - 1]
    if (!last || last.x !== c.x || last.y !== c.y) out.push({ x: c.x, y: c.y })
  }
  return out
}

export type DoorClickResult =
  | { kind: 'select'; doorId: string | null } // toggles selection
  | { kind: 'ignore' }

/**
 * DM clicking a door toggles its selection; Player clicks are ignored.
 * Returns null selection when clicking the already-selected door.
 */
export function doorClickAction(
  isDm: boolean,
  doorId: string | null,
  selectedDoorId: string | null,
): DoorClickResult {
  if (!isDm || !doorId) return { kind: 'ignore' }
  return { kind: 'select', doorId: selectedDoorId === doorId ? null : doorId }
}

export type TokenClickResult =
  | { kind: 'start-move'; entryId: string }
  | { kind: 'select-reposition'; entryId: string }
  | { kind: 'select'; entryId: string }
  | { kind: 'ignore' }

/**
 * Decide what clicking a token does.
 * - reposition mode (DM): select token for reposition.
 * - own/DM-controllable token and not placing: start (or keep) move draft.
 * - otherwise: plain selection toggle (handled by caller).
 */
export function tokenClickAction(
  entryId: string,
  opts: {
    isDm: boolean
    repositionMode: boolean
    placing: boolean
    moveEntryId: string | null
    canMove: boolean
  },
): TokenClickResult {
  if (opts.repositionMode && opts.isDm) return { kind: 'select-reposition', entryId }
  if (opts.canMove && !opts.placing) {
    if (opts.moveEntryId === entryId) return { kind: 'ignore' }
    return { kind: 'start-move', entryId }
  }
  return { kind: 'select', entryId }
}

/** Whether new table events should trigger a board reload. Pure. */
export function shouldReloadOnEvents(
  events: TableEvent[],
  lastSeq: number,
): { reload: boolean; newLastSeq: number } {
  const unseen = events.filter((e) => e.seq > lastSeq)
  if (unseen.length === 0) return { reload: false, newLastSeq: lastSeq }
  const newLastSeq = Math.max(...unseen.map((e) => e.seq))
  return { reload: unseen.some(isCombatEvent), newLastSeq }
}

export type TargetBand = 'in-range' | 'long-range' | 'blocked' | 'out-of-range'

/**
 * Map a target-check result to a display band. Pure; the server is the
 * authority — `range_band` is its canonical value ("reach" | "normal" |
 * "long" | "out_of_range" | "unknown").
 */
export function targetCheckBand(result: TargetCheckResult): TargetBand {
  if (result.blocked) return 'blocked'
  switch (result.range_band) {
    case 'reach':
    case 'normal':
      return 'in-range'
    case 'long':
      return 'long-range'
    default:
      return 'out-of-range'
  }
}

/** Whether a preview response is still the latest request. Pure. */
export function isLatestPreview(requestId: number, latestId: number): boolean {
  return requestId === latestId
}

export type AoeShapeKind = 'circle' | 'square' | 'cone' | 'line'

/** Cone and line templates need a second click for aim direction. Pure. */
export function aoeShapeNeedsAim(shape: AoeShapeKind): boolean {
  return shape === 'cone' || shape === 'line'
}
