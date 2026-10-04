import type {
  BattleMapMonsterPlacement,
  BattleMapMonsterPlacementVisibility,
  MonsterPlacementInput,
  MonsterPlacementProblem,
  MonsterPlacementsReplaceInput,
} from '../../api/battleMaps'
import { SessionApiError } from '../../api/sessions'
import type { MonsterLibrarySummaryView } from '../../api/monsterLibrary'

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
