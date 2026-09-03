import { describe, expect, it } from 'vitest'

import { formatSignedBonus } from './abilityPresentation'

describe('formatSignedBonus', () => {
  it('renders positive, negative, and zero modifiers without a double sign', () => {
    expect(formatSignedBonus(2)).toBe('+2')
    expect(formatSignedBonus(-2)).toBe('-2')
    expect(formatSignedBonus(0)).toBe('')
  })
})
