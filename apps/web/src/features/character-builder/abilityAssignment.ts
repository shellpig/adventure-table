import type { BuilderAbilityScores } from '../../api/characterBuilder'

/**
 * Standard Array assignment: every value stays selectable. Taking a value that
 * another ability already holds clears that ability so the player re-picks it.
 */
export function assignStandardArrayScore(
  current: BuilderAbilityScores,
  ability: keyof BuilderAbilityScores,
  score: number,
): BuilderAbilityScores {
  const next: BuilderAbilityScores = { ...current, [ability]: score }
  for (const key of Object.keys(next) as (keyof BuilderAbilityScores)[]) {
    if (key !== ability && next[key] === score) {
      next[key] = 0
    }
  }
  return next
}
