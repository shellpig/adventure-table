import { describe, expect, it } from 'vitest'

import { parsePhysicalD20 } from './SessionRollRequestList'

describe('formal physical d20 input', () => {
  it('accepts exactly one raw d20 for normal rolls', () => {
    expect(parsePhysicalD20('normal', '14')).toEqual([14])
    expect(parsePhysicalD20('normal', '14, 18')).toBeNull()
  })

  it('requires exactly two raw d20 values for advantage/disadvantage', () => {
    expect(parsePhysicalD20('advantage', '3, 17')).toEqual([3, 17])
    expect(parsePhysicalD20('disadvantage', '20 1')).toEqual([20, 1])
    expect(parsePhysicalD20('advantage', '17')).toBeNull()
  })

  it('rejects out-of-range or non-integer dice and never accepts a final total shape', () => {
    expect(parsePhysicalD20('normal', '21')).toBeNull()
    expect(parsePhysicalD20('normal', '10.5')).toBeNull()
    expect(parsePhysicalD20('normal', '27 total')).toBeNull()
  })
})
