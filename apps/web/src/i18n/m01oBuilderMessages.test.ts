import { describe, expect, it } from 'vitest'

import { installM01KLocalizedBuilderPayload } from './m01kBuilderMessages'

// vitest runs without a DOM; currentSystemLocale() reads document.documentElement.lang.
function withLocale<T>(locale: 'zh-TW' | 'en', read: () => T): T {
  const scope = globalThis as { document?: unknown }
  const previous = scope.document
  scope.document = { documentElement: { lang: locale } }
  try {
    return read()
  } finally {
    if (previous === undefined) delete scope.document
    else scope.document = previous
  }
}

describe('M01-O builder message localization', () => {
  it('renders ancestry / size prerequisite atoms in both locales', () => {
    const option = installM01KLocalizedBuilderPayload({
      disabled_reason: 'Requires the feat prerequisites.',
      disabled_reason_code: 'feat_prerequisite_not_met',
      disabled_reason_params: {
        feat_ref: 'xge:feat:squat-nimbleness',
        requirements: [
          {
            type: 'any_of',
            options: [
              { type: 'ancestry', allowed_refs: ['srd5.1:race:dwarf'], actual_ref: 'srd5.1:race:human' },
              { type: 'size', allowed_sizes: ['small'], actual_size: 'medium' },
            ],
          },
        ],
      },
    })

    expect(withLocale('zh-TW', () => option.disabled_reason)).toBe('此專長需要符合：以下任一：特定種族 或 體型為小型。')
    expect(withLocale('en', () => option.disabled_reason)).toBe('Requires one of: a specific ancestry or Small size.')
  })

  it('localizes the pool-option and retraining codes', () => {
    const payload = installM01KLocalizedBuilderPayload({
      options: [
        { disabled_reason: 'x', disabled_reason_code: 'feat_fighting_style_already_known' },
        { disabled_reason: 'x', disabled_reason_code: 'feat_invocation_prerequisite_not_met', disabled_reason_params: {} },
      ],
      issues: [
        { code: 'feat_retraining_limit_exceeded', message: 'x', message_params: {} },
        { code: 'feat_retraining_requires_level_up', message: 'x', message_params: {} },
      ],
    })

    expect(withLocale('zh-TW', () => payload.options[0].disabled_reason)).toBe('已經擁有這個戰鬥風格。')
    expect(withLocale('en', () => payload.options[1].disabled_reason)).toBe(
      'This invocation has a prerequisite that only a qualifying Warlock can meet.',
    )
    expect(withLocale('zh-TW', () => payload.issues[0].message)).toBe('每次升級只能替換此專長的一個選項。')
    expect(withLocale('en', () => payload.issues[1].message)).toBe(
      'Feat-linked options can only be replaced through Level Up, not Build Edit.',
    )
  })
})
