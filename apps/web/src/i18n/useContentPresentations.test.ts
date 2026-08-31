import { describe, expect, it } from 'vitest'

import { localizedContentLabel } from './useContentPresentations'

describe('localizedContentLabel', () => {
  it('preserves counted-reference bonuses', () => {
    expect(localizedContentLabel('力量', 'STR +2')).toBe('力量 +2')
  })

  it('keeps source disambiguation without reintroducing English source prose', () => {
    expect(
      localizedContentLabel(
        '火焰箭',
        'Fire Bolt · System Reference Document 5.1',
      ),
    ).toBe('火焰箭 · SRD 5.1')
  })

  it('does not duplicate an existing mechanics suffix', () => {
    expect(localizedContentLabel('力量 +1', 'STR +1')).toBe('力量 +1')
  })

  it('preserves trailing multiplication counts', () => {
    expect(localizedContentLabel('治療藥水', 'Potion of Healing ×2')).toBe('治療藥水 ×2')
  })

  it('preserves the counted-reference prefix emitted by structural choices', () => {
    expect(
      localizedContentLabel(
        '標槍',
        '2 × Javelin · System Reference Document 5.1',
      ),
    ).toBe('2 × 標槍 · SRD 5.1')
  })
})
