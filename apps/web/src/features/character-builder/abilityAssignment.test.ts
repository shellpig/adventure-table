import { describe, expect, it } from 'vitest'

import type { BuilderAbilityScores } from '../../api/characterBuilder'
import { assignStandardArrayScore } from './abilityAssignment'

const assigned: BuilderAbilityScores = {
  strength: 15,
  dexterity: 14,
  constitution: 13,
  intelligence: 12,
  wisdom: 10,
  charisma: 8,
}

describe('assignStandardArrayScore', () => {
  it('clears the ability that previously held the value', () => {
    expect(assignStandardArrayScore(assigned, 'charisma', 15)).toEqual({
      ...assigned,
      charisma: 15,
      strength: 0,
    })
  })

  it('keeps other abilities untouched when the value is unassigned', () => {
    const partial: BuilderAbilityScores = { ...assigned, strength: 0 }
    expect(assignStandardArrayScore(partial, 'strength', 15)).toEqual(assigned)
  })

  it('is a no-op when re-selecting the ability own value', () => {
    expect(assignStandardArrayScore(assigned, 'strength', 15)).toEqual(assigned)
  })
})
