import { describe, expect, it } from 'vitest'

import {
  createLocalizedRequestError,
  installDynamicLocalizedBuilderPayload,
  localizedBuilderIssueMessage,
  localizedDisabledReason,
  localizedRequestErrorMessage,
} from './systemMessages'

describe('M02-G system-owned messages', () => {
  it('keeps machine validation identity stable while presentation is localized explicitly', () => {
    const issue = installDynamicLocalizedBuilderPayload({
      code: 'missing_race',
      severity: 'blocking_error',
      path: 'draft_payload.race_selection',
      message: 'Race selection is required before Confirm.',
      related_refs: [],
    })

    expect(issue.code).toBe('missing_race')
    expect(issue.path).toBe('draft_payload.race_selection')
    expect(
      localizedBuilderIssueMessage(issue.code, 'Race selection is required before Confirm.', 'zh-TW'),
    ).toBe('確認角色前必須選擇種族。')
    expect(
      localizedBuilderIssueMessage(issue.code, 'Race selection is required before Confirm.', 'en'),
    ).toBe('Race selection is required before Confirm.')
  })

  it('covers common blocking issue codes that previously leaked canonical English', () => {
    const cases = [
      ['multiclass_prerequisite_not_met', 'Wizard: Requires INT 13+ to multiclass.'],
      ['subclass_selected_too_early', 'Subclass selected too early.'],
      ['missing_subclass_at_timing', 'Subclass selection is required.'],
      ['duplicate_choice_option', 'Duplicate choice option.'],
      ['stale_build_version', 'Build version is stale.'],
      ['invalid_manual_hp_roll', 'Manual HP roll is invalid.'],
    ] as const

    for (const [code, original] of cases) {
      const localized = localizedBuilderIssueMessage(code, original, 'zh-TW')
      expect(localized).not.toContain(original)
      expect(localized).not.toMatch(/Wizard|Subclass|Duplicate|Build version|Manual HP/)
    }
  })

  it('supports code + params for disabled reasons without parsing English prose', () => {
    expect(
      localizedDisabledReason(
        'Wizard: Requires INT 13+ to multiclass.',
        'zh-TW',
        'multiclass_prerequisite_not_met',
        { requirements: 'INT 13+' },
      ),
    ).toBe('兼職需要符合：INT 13+。')

    expect(
      localizedDisabledReason(
        'Complete ability scores before multiclassing.',
        'zh-TW',
        'multiclass_ability_scores_incomplete',
      ),
    ).toBe('兼職前請先完成能力值。')
  })

  it('never leaks untranslated disabled reason prose into zh-TW fallback', () => {
    const original = 'Prerequisite not met.'
    const localized = localizedDisabledReason(original, 'zh-TW')
    expect(localized).toBe('此選項目前無法選擇；請先完成相關條件。')
    expect(localized).not.toContain(original)
    expect(localizedDisabledReason(original, 'en')).toBe(original)
  })

  it('localizes request failures without requiring a browser document', () => {
    const zhError = createLocalizedRequestError('not_found', 404, 'Draft not found', 'zh-TW')
    const enError = createLocalizedRequestError('not_found', 404, 'Draft not found', 'en')

    expect(zhError.message).toContain('找不到')
    expect(enError.message).toContain('could not be found')
    expect(localizedRequestErrorMessage(undefined, 500, 'Database unavailable', 'zh-TW')).toBe(
      '要求失敗（HTTP 500），請稍後再試。',
    )
  })

  it('uses a Chinese-only safe fallback for unknown validation codes', () => {
    expect(localizedBuilderIssueMessage('future_code', 'Future warning', 'zh-TW')).toBe(
      '目前的角色資料有一項需要修正的規則問題。',
    )
    expect(localizedBuilderIssueMessage('future_code', 'Future warning', 'en')).toBe('Future warning')
  })
})
