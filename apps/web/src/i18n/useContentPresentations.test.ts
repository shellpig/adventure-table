import { describe, expect, it } from 'vitest'

import { localizedContentLabel } from './useContentPresentations'

describe('localizedContentLabel', () => {
  it('preserves counted-reference bonuses', () => {
    expect(localizedContentLabel('力量', 'STR +2')).toBe('力量 +2')
  })

  it('preserves source-aware duplicate disambiguation', () => {
    expect(
      localizedContentLabel(
        '火焰箭',
        'Fire Bolt · System Reference Document 5.1',
      ),
    ).toBe('火焰箭 · System Reference Document 5.1')
  })

  it('does not duplicate an existing mechanics suffix', () => {
    expect(localizedContentLabel('力量 +1', 'STR +1')).toBe('力量 +1')
  })

  it('preserves multiplication counts', () => {
    expect(localizedContentLabel('治療藥水', 'Potion of Healing ×2')).toBe('治療藥水 ×2')
  })
})
