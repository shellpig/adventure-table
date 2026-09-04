import { describe, expect, it } from 'vitest'

import { capabilityCopy } from './copy'


describe('M03-E capability presentation copy', () => {
  it('keeps English and Traditional Chinese key parity', () => {
    expect(Object.keys(capabilityCopy('en')).sort()).toEqual(
      Object.keys(capabilityCopy('zh-TW')).sort(),
    )
  })

  it('includes the standalone database migration hint in both supported locales', () => {
    expect(capabilityCopy('en').dataPathHint.length).toBeGreaterThan(10)
    expect(capabilityCopy('zh-TW').dataPathHint.length).toBeGreaterThan(10)
  })
})
