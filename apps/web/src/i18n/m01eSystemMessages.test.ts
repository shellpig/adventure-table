import { describe, expect, it } from 'vitest'

import { localizedBuilderIssueMessage } from './systemMessages'

describe('M01-E ancestry builder messages', () => {
  it('localizes race-variant mismatch in both supported locales', () => {
    expect(
      localizedBuilderIssueMessage(
        'race_variant_race_mismatch',
        'fallback',
        'zh-TW',
      ),
    ).toBe('目前選擇的血統變體不屬於所選種族。')
    expect(
      localizedBuilderIssueMessage(
        'race_variant_race_mismatch',
        'fallback',
        'en',
      ),
    ).toBe('The selected ancestry variant does not belong to the selected race.')
  })

  it('makes the Level Up origin lock explicitly ancestry-aware', () => {
    expect(
      localizedBuilderIssueMessage('level_up_origin_changed', 'fallback', 'zh-TW'),
    ).toContain('血統／亞種')
    expect(
      localizedBuilderIssueMessage('level_up_origin_changed', 'fallback', 'en'),
    ).toContain('ancestry/subrace')
  })
})
