import type {
  BattleMapMonsterPlacement,
  BattleMapMonsterPlacementVisibility,
  MonsterPlacementInput,
  MonsterPlacementProblem,
  MonsterPlacementsReplaceInput,
} from '../../api/battleMaps'
import { SessionApiError } from '../../api/sessions'
import type { MonsterLibrarySummaryView } from '../../api/monsterLibrary'
import type { MonsterLibraryDetailView } from '../../api/monsterLibrary'

/**
 * M07-C map monster pre-placements (library editor working state).
 *
 * The editor never touches live combat APIs: placement edits only build the
 * full-set body sent to PUT .../monster-placements. `clientId` is the server
 * UUID for saved placements; newly added rows get a client-generated UUID
 * (kept by the server when supplied) so 409 `map_monster_placement_invalid`
 * problems map back onto the exact row. Non-UUID ids are still stripped to
 * null in the payload, mirroring `toReplaceObjects` in mapEditorState.ts.
 */
export type WorkingMonsterPlacement = {
  clientId: string
  templateRef: string
  anchor_x: number
  anchor_y: number
  visibility: BattleMapMonsterPlacementVisibility
}

export function newPlacementClientId(): string {
  return crypto.randomUUID()
}

export const CUSTOM_TEMPLATE_REF_PREFIX = 'custom:'

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Library ref for a saved placement: custom id → `custom:<uuid>`, else the content key. */
export function templateRefForPlacement(
  placement: Pick<BattleMapMonsterPlacement, 'template_key' | 'custom_template_id'>,
): string {
  if (placement.custom_template_id) return `${CUSTOM_TEMPLATE_REF_PREFIX}${placement.custom_template_id}`
  return placement.template_key ?? ''
}

/** Split a library ref back into the exactly-one source the server requires. */
export function placementSourceForRef(ref: string): {
  template_key: string | null
  custom_template_id: string | null
} {
  if (ref.startsWith(CUSTOM_TEMPLATE_REF_PREFIX)) {
    return { template_key: null, custom_template_id: ref.slice(CUSTOM_TEMPLATE_REF_PREFIX.length) || null }
  }
  return { template_key: ref, custom_template_id: null }
}

export function monsterPlacementsFromMap(
  placements: BattleMapMonsterPlacement[],
): WorkingMonsterPlacement[] {
  return [...placements]
    .sort((a, b) => a.sort_order - b.sort_order)
    .map((p) => ({
      clientId: p.id,
      templateRef: templateRefForPlacement(p),
      anchor_x: p.anchor_x,
      anchor_y: p.anchor_y,
      visibility: p.visibility,
    }))
}

/**
 * Full-set replace body for PUT .../monster-placements. `sort_order` follows
 * the working list order; editor-added placements (non-UUID client ids) are
 * sent with a null id so the server assigns one.
 */
export function toMonsterPlacementsPayload(
  placements: WorkingMonsterPlacement[],
): MonsterPlacementInput[] {
  return placements.map((p, index) => {
    const source = placementSourceForRef(p.templateRef)
    return {
      id: p.clientId && UUID_PATTERN.test(p.clientId) ? p.clientId : null,
      template_key: source.template_key,
      custom_template_id: source.custom_template_id,
      anchor_x: p.anchor_x,
      anchor_y: p.anchor_y,
      visibility: p.visibility,
      sort_order: index,
    }
  })
}

export function buildMonsterPlacementsBody(
  expectedRevision: number,
  placements: WorkingMonsterPlacement[],
): MonsterPlacementsReplaceInput {
  return {
    expected_revision: expectedRevision,
    placements: toMonsterPlacementsPayload(placements),
  }
}

export function addMonsterPlacement(
  placements: WorkingMonsterPlacement[],
  placement: Omit<WorkingMonsterPlacement, 'clientId'> & { clientId?: string },
): WorkingMonsterPlacement[] {
  return [...placements, { ...placement, clientId: placement.clientId ?? '' }]
}

export function moveMonsterPlacement(
  placements: WorkingMonsterPlacement[],
  clientId: string,
  anchor_x: number,
  anchor_y: number,
): WorkingMonsterPlacement[] {
  return placements.map((p) =>
    p.clientId === clientId ? { ...p, anchor_x, anchor_y } : p,
  )
}

/**
 * M07-D D6d: double-click-safe creation. Two clicks that both take the
 * "empty cell" branch (e.g. a rapid double-click before React re-renders,
 * so both closures see the same placements array) must not append two
 * rows. The check runs inside the functional state updater, which always
 * sees the latest array, so the second create is a no-op returning the
 * identical reference (no re-render, no second row).
 */
export function createPlacementIfFree(
  placements: WorkingMonsterPlacement[],
  draft: Omit<WorkingMonsterPlacement, 'clientId'>,
  footprintOf: (templateRef: string) => MonsterFootprint,
): { placements: WorkingMonsterPlacement[]; created: WorkingMonsterPlacement | null } {
  const covered = placements.some((p) => {
    const footprint = footprintOf(p.templateRef)
    return (
      draft.anchor_x >= p.anchor_x &&
      draft.anchor_x < p.anchor_x + footprint.width &&
      draft.anchor_y >= p.anchor_y &&
      draft.anchor_y < p.anchor_y + footprint.height
    )
  })
  if (covered) return { placements, created: null }
  const created: WorkingMonsterPlacement = { ...draft, clientId: newPlacementClientId() }
  return { placements: [...placements, created], created }
}

export type PlacementCreateStamp = { clientX: number; clientY: number; time: number }

/** Window in which a second create click counts as a double-click repeat. */
export const PLACEMENT_DOUBLE_CLICK_WINDOW_MS = 500

/** Screen distance below which two create clicks are the same double-click. */
export const PLACEMENT_DOUBLE_CLICK_DISTANCE_PX = 12

/**
 * M07-D D6d: the second half of a double-click must not place a second
 * monster. Both halves land within a few screen pixels (even when human
 * jitter drifts onto the neighbouring cell), while two deliberate
 * placements in adjacent cells are a full cell (40px at zoom 1) apart —
 * so the guard compares screen pixels, not cells. Deliberate placements
 * are also seconds apart, outside the window.
 */
export function isRapidPlacementRepeat(
  last: PlacementCreateStamp | null,
  point: { clientX: number; clientY: number },
  now: number,
  windowMs: number = PLACEMENT_DOUBLE_CLICK_WINDOW_MS,
  distancePx: number = PLACEMENT_DOUBLE_CLICK_DISTANCE_PX,
): boolean {
  if (!last) return false
  if (now - last.time < 0 || now - last.time >= windowMs) return false
  return Math.hypot(point.clientX - last.clientX, point.clientY - last.clientY) <= distancePx
}

export function removeMonsterPlacement(
  placements: WorkingMonsterPlacement[],
  clientId: string,
): WorkingMonsterPlacement[] {
  return placements.filter((p) => p.clientId !== clientId)
}

export function toggleMonsterPlacementVisibility(
  placements: WorkingMonsterPlacement[],
  clientId: string,
): WorkingMonsterPlacement[] {
  return placements.map((p) =>
    p.clientId === clientId
      ? { ...p, visibility: p.visibility === 'hidden' ? 'public' : 'hidden' }
      : p,
  )
}

/**
 * M07-D D6e: content equality for placement arrays. The editor's placement
 * updater pushes history only on a real change; helpers like
 * `moveMonsterPlacement` always build a new array, so reference inequality
 * alone cannot tell a no-op (same cell, unknown id) from an edit.
 */
export function sameMonsterPlacements(
  a: WorkingMonsterPlacement[],
  b: WorkingMonsterPlacement[],
): boolean {
  return (
    a.length === b.length &&
    a.every((p, index) => {
      const q = b[index]
      return (
        p.clientId === q.clientId &&
        p.templateRef === q.templateRef &&
        p.anchor_x === q.anchor_x &&
        p.anchor_y === q.anchor_y &&
        p.visibility === q.visibility
      )
    })
  )
}

/** Cap for the M07-D D6e placement undo stack (mirrors the geometry history). */
export const PLACEMENT_HISTORY_LIMIT = 50

/**
 * M07-D D6e: push the pre-edit placements array onto the undo stack, dropping
 * the oldest entry past the cap. Pure helper so the push/cap/undo contract is
 * unit-testable without React.
 *
 * A consecutive push of the identical reference is a no-op. The editor pushes
 * from inside its state updater (so two clicks before a re-render still see
 * each other's rows, per the D6d double-click design), and StrictMode
 * double-invokes updaters in dev/E2E: both invocations push the same pre-edit
 * array, which must yield one undo step, not two. Genuine consecutive edits
 * always carry distinct arrays (every edit builds a new one), so the collapse
 * can only merge a double-invoked push.
 */
export function pushPlacementHistory(
  history: WorkingMonsterPlacement[][],
  prev: WorkingMonsterPlacement[],
  limit: number = PLACEMENT_HISTORY_LIMIT,
): WorkingMonsterPlacement[][] {
  if (history.length > 0 && history[history.length - 1] === prev) return history
  return [...history.slice(-(limit - 1)), prev]
}

/**
 * M07-D D6e: pop one placement undo step. Returns null when the stack is
 * empty so the Undo button and Ctrl/Cmd+Z can stay disabled/no-op.
 */
export function popPlacementHistory(
  history: WorkingMonsterPlacement[][],
): { placements: WorkingMonsterPlacement[]; history: WorkingMonsterPlacement[][] } | null {
  if (history.length === 0) return null
  return { placements: history[history.length - 1], history: history.slice(0, -1) }
}

export type MonsterFootprint = { width: number; height: number }

/**
 * Editor preview footprint for a template size name. Mirrors the server table
 * (Tiny/Small/Medium 1×1, Large 2×2, Huge 3×3, Gargantuan 4×4); a missing or
 * blank size previews as Medium. An unparseable size also previews as 1×1 —
 * the server rejects it with `invalid_size` on save, surfaced as a problem.
 */
export function footprintForSizeName(size: string | null | undefined): MonsterFootprint {
  const normalized = (size ?? '').trim().toLowerCase()
  switch (normalized) {
    case 'large':
      return { width: 2, height: 2 }
    case 'huge':
      return { width: 3, height: 3 }
    case 'gargantuan':
      return { width: 4, height: 4 }
    default:
      return { width: 1, height: 1 }
  }
}

/** Templates offered in the add picker: archived templates are never offered. */
export function availableMonsterTemplates(
  summaries: MonsterLibrarySummaryView[],
): MonsterLibrarySummaryView[] {
  return summaries.filter((s) => s.archived_at == null)
}

/** Resolve a saved placement's ref against the loaded library list (may be archived or gone). */
export function resolvePlacementTemplate(
  ref: string,
  summaries: MonsterLibrarySummaryView[],
): MonsterLibrarySummaryView | undefined {
  return summaries.find((s) => s.ref === ref)
}

/**
 * Summary view for a template resolved outside the menu page (e.g. a saved
 * placement whose ref is not in the current search page). Carries the rules
 * fields the editor needs (size for footprints, names for labels) including
 * archived custom templates, which the add picker never offers.
 */
export function monsterSummaryFromDetail(detail: MonsterLibraryDetailView): MonsterLibrarySummaryView {
  return {
    ref: detail.ref,
    name: detail.name,
    names: detail.names,
    name_is_custom: detail.name_is_custom,
    source_kind: detail.source_kind,
    source_key: detail.source_key ?? null,
    size: detail.rules.size,
    type: detail.rules.type,
    alignment: detail.rules.alignment,
    armor_class: detail.rules.armor_class,
    max_hp: detail.rules.max_hp,
    challenge_rating: detail.rules.challenge_rating ?? null,
    archived_at: detail.archived_at ?? null,
    revision: detail.revision ?? null,
  }
}

/**
 * DM-only problems from a 409 `map_monster_placement_invalid` response.
 * Returns [] for any other error (revision conflicts and reference/source
 * errors are messaged through their own machine codes).
 */
export function extractPlacementProblems(error: unknown): MonsterPlacementProblem[] {
  if (!(error instanceof SessionApiError)) return []
  if (error.code !== 'map_monster_placement_invalid') return []
  const problems = error.params?.problems
  if (!Array.isArray(problems)) return []
  return problems.filter(
    (p): p is MonsterPlacementProblem =>
      typeof p === 'object' &&
      p !== null &&
      typeof (p as { placement_id?: unknown }).placement_id === 'string' &&
      typeof (p as { code?: unknown }).code === 'string',
  )
}
