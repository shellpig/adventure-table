import type {
  MonsterLibraryDetailView,
  PatchCustomMonsterInput,
} from '../../api/monsterLibrary'

/**
 * M07-D D2 (F12): tolerant custom-monster form model.
 *
 * Templates saved from a Quick Enemy (`Save as Monster Template`) only carry
 * `{ size, armor_class, max_hp, speed, actions? }` — no `ability_scores`,
 * `type`, or `alignment`. The editor must load any such shape without
 * throwing, show missing fields as unset, and only PATCH fields the DM
 * actually changed so defaults are never written back over the stored rules.
 */
export const MONSTER_ABILITIES = [
  'strength',
  'dexterity',
  'constitution',
  'intelligence',
  'wisdom',
  'charisma',
] as const

export type MonsterAbilityKey = (typeof MONSTER_ABILITIES)[number]

/** Scalar editor state; `''` / `null` both mean "not set in the stored rules". */
export type CustomMonsterFormValues = {
  name: string
  armorClass: number
  maxHp: number
  challengeRating: number
  size: string
  type: string
  alignment: string
  speed: string
  abilities: Record<MonsterAbilityKey, number | null>
  description: string
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null
    ? (value as Record<string, unknown>)
    : {}
}

function asString(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

function asFiniteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function monsterSpeedString(speed: unknown): string {
  if (typeof speed === 'string') return speed
  if (typeof speed === 'object' && speed !== null) {
    const walk = (speed as Record<string, unknown>).walk
    if (typeof walk === 'string') return walk
  }
  return '30 ft.'
}

/**
 * Read the editor form state from a detail view. Never throws, whatever
 * shape `rules` has: unknown or missing groups fall back to unset/blank
 * rather than leaving a half-initialized form.
 */
export function customMonsterFormFromDetail(
  detail: MonsterLibraryDetailView,
): CustomMonsterFormValues {
  const rules = asRecord(detail.rules)
  const scores = asRecord(rules['ability_scores'])
  const abilities = {} as Record<MonsterAbilityKey, number | null>
  for (const ability of MONSTER_ABILITIES) {
    abilities[ability] = asFiniteNumber(scores[ability])
  }
  return {
    name: asString(detail.name) ?? '',
    armorClass: asFiniteNumber(rules['armor_class']) ?? 10,
    maxHp: asFiniteNumber(rules['max_hp']) ?? 10,
    challengeRating: asFiniteNumber(rules['challenge_rating']) ?? 0,
    size: asString(rules['size']) ?? '',
    type: asString(rules['type']) ?? '',
    alignment: asString(rules['alignment']) ?? '',
    speed: monsterSpeedString(rules['speed']),
    abilities,
    description: asString(rules['description']) ?? '',
  }
}

/**
 * Dirty-field PATCH for the scalar fields. A field is only sent when the DM
 * changed it away from what was loaded; values still unset (`''` / `null`)
 * are never sent, so stored rules are never polluted with editor defaults.
 * Speed/traits/actions keep their existing page-level diff and are merged
 * by the caller.
 */
export function customMonsterScalarPatch(
  baseline: CustomMonsterFormValues,
  current: CustomMonsterFormValues,
  expectedRevision: number,
): PatchCustomMonsterInput {
  const payload: PatchCustomMonsterInput = { expected_revision: expectedRevision }
  if (current.name.trim() !== baseline.name) {
    payload.name = current.name.trim()
  }
  if (current.armorClass !== baseline.armorClass) {
    payload.armor_class = current.armorClass
  }
  if (current.maxHp !== baseline.maxHp) {
    payload.max_hp = current.maxHp
  }
  if (current.challengeRating !== baseline.challengeRating) {
    payload.challenge_rating = current.challengeRating
  }
  if (current.size !== '' && current.size !== baseline.size) {
    payload.size = current.size
  }
  if (current.type !== '' && current.type !== baseline.type) {
    payload.type = current.type
  }
  if (current.alignment !== '' && current.alignment !== baseline.alignment) {
    payload.alignment = current.alignment
  }
  const scoreUpdates: Record<string, number> = {}
  for (const ability of MONSTER_ABILITIES) {
    const next = current.abilities[ability]
    if (next !== null && next !== baseline.abilities[ability]) {
      scoreUpdates[ability] = next
    }
  }
  if (Object.keys(scoreUpdates).length > 0) {
    payload.ability_scores = scoreUpdates
  }
  if (current.description !== baseline.description) {
    payload.description = current.description
  }
  return payload
}
