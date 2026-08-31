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

  it('localizes disabled reasons without discarding the concrete reason', () => {
    expect(localizedDisabledReason('Complete ability scores before multiclassing.', 'zh-TW')).toBe(
      '兼職前請先完成能力值。',
    )
    expect(localizedDisabledReason('Wizard: Requires INT 13+ to multiclass.', 'zh-TW')).toBe(
      'Wizard：兼職需要 INT 13+。',
    )
    expect(localizedDisabledReason('Prerequisite not met.', 'zh-TW')).toContain('Prerequisite not met.')
    expect(localizedDisabledReason('Prerequisite not met.', 'en')).toBe('Prerequisite not met.')
  })

  it('localizes request failures without requiring a browser document', () => {
    const zhError = createLocalizedRequestError('not_found', 404, 'Draft not found', 'zh-TW')
    const enError = createLocalizedRequestError('not_found', 404, 'Draft not found', 'en')

    expect(zhError.message).toContain('找不到')
    expect(enError.message).toContain('could not be found')
    expect(localizedRequestErrorMessage(undefined, 500, 'Database unavailable', 'zh-TW')).toContain(
      'Database unavailable',
    )
  })

  it('preserves details for unknown validation codes instead of collapsing to a generic sentence', () => {
    expect(localizedBuilderIssueMessage('future_code', 'Future warning', 'zh-TW')).toContain(
      'Future warning',
    )
    expect(localizedBuilderIssueMessage('future_code', 'Future warning', 'en')).toBe('Future warning')
  })
})
