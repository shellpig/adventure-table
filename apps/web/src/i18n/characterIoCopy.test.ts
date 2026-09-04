import { describe, expect, it } from 'vitest'

import { CHARACTER_IO_COPY } from './useCharacterIoCopy'

describe('M03-B character I/O copy', () => {
  it('keeps en and zh-TW keys in parity', () => {
    expect(Object.keys(CHARACTER_IO_COPY.en).sort()).toEqual(
      Object.keys(CHARACTER_IO_COPY['zh-TW']).sort(),
    )
  })

  it.each(['en', 'zh-TW'] as const)('%s copy contains no empty values', (locale) => {
    expect(Object.values(CHARACTER_IO_COPY[locale]).every((value) => value.trim().length > 0)).toBe(true)
  })
})
