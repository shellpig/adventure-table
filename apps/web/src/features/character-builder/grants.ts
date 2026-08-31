import { type BuilderGrantSummary } from '../../api/characterBuilder'
import type {
  ContentFieldResolver,
  ContentNameResolver,
} from '../../i18n/useContentPresentations'

const KIND_ORDER = ['language', 'feature', 'background_feature', 'trait', 'proficiency']

function kindRank(kind: string, extraKinds: string[]) {
  const known = KIND_ORDER.indexOf(kind)
  if (known >= 0) return known
  return KIND_ORDER.length + extraKinds.indexOf(kind)
}

export function sortGrantsByKind<T extends BuilderGrantSummary>(grants: readonly T[]): T[] {
  const extraKinds: string[] = []
  for (const grant of grants) {
    if (!KIND_ORDER.includes(grant.kind) && !extraKinds.includes(grant.kind)) {
      extraKinds.push(grant.kind)
    }
  }
  return grants
    .map((grant, index) => ({ grant, index }))
    .sort((a, b) =>
      kindRank(a.grant.kind, extraKinds) - kindRank(b.grant.kind, extraKinds) || a.index - b.index,
    )
    .map((entry) => entry.grant)
}

/**
 * References and field paths a grant list needs before its names can be shown
 * in the active locale.
 *
 * A grant that points at a standalone content entry resolves through its own
 * StableKey. A grant that is an inline field of its source entry has no
 * StableKey, so it resolves through the source entry plus a field path.
 */
export function grantPresentationReferences(
  grants: readonly BuilderGrantSummary[],
): string[] {
  return grants.flatMap((grant) =>
    grant.presentation_field ? [grant.source_ref] : grant.reference_id ? [grant.reference_id] : [],
  )
}

export function grantPresentationFields(
  grants: readonly BuilderGrantSummary[],
): Record<string, string[]> {
  const fields: Record<string, string[]> = {}
  for (const grant of grants) {
    if (!grant.presentation_field) continue
    const existing = fields[grant.source_ref] ?? []
    if (!existing.includes(grant.presentation_field)) {
      fields[grant.source_ref] = [...existing, grant.presentation_field]
    }
  }
  return fields
}

export function grantDisplayName(
  grant: BuilderGrantSummary,
  fallback: string,
  nameFor: ContentNameResolver,
  fieldFor: ContentFieldResolver,
): string {
  if (grant.presentation_field) {
    return fieldFor(grant.source_ref, grant.presentation_field, fallback)
  }
  return nameFor(grant.reference_id, fallback)
}
