import { type BuilderGrantSummary } from '../../api/characterBuilder'

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
