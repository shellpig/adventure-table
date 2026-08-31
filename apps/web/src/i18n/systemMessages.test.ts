import { describe, expect, it } from 'vitest'

import {
  createLocalizedRequestError,
  installDynamicLocalizedBuilderPayload,
  localizedBuilderIssueMessage,
  localizedDisabledReason,
} from './systemMessages'

describe('M02-G system-owned messages', () => {
  it('keeps the machine validation code stable while the visible message changes locale', () => {
    const issue = installDynamicLocalizedBuilderPayload({
      code: 'missing_race',
      severity: 'blocking_error',
      path: 'draft_payload.race_selection',
      message: 'Race selection is required before Confirm.',
      related_refs: [],
    })

    document.documentElement.lang = 'zh-TW'
    expect(issue.code).toBe('missing_race')
    expect(issue.path).toBe('draft_payload.race_selection')
    expect(issue.message).toBe('確認角色前必須選擇種族。')

    document.documentElement.lang = 'en'
    expect(issue.code).toBe('missing_race')
    expect(issue.path).toBe('draft_payload.race_selection')
    expect(issue.message).toBe('Race selection is required before Confirm.')
  })

  it('localizes server-owned disabled reasons without changing option identity', () => {
    const option = installDynamicLocalizedBuilderPayload({
      option_id: 'srd5.1:class:wizard',
      disabled_reason: 'Prerequisite not met.',
    })

    document.documentElement.lang = 'zh-TW'
    expect(option.option_id).toBe('srd5.1:class:wizard')
    expect(option.disabled_reason).toBe('此選項目前無法選擇。')

    document.documentElement.lang = 'en'
    expect(option.disabled_reason).toBe('Prerequisite not met.')
  })

  it('localizes request failures at read time so cached errors follow locale switches', () => {
    const error = createLocalizedRequestError('not_found', 404, 'Draft not found')

    document.documentElement.lang = 'zh-TW'
    expect(error.message).toContain('找不到')

    document.documentElement.lang = 'en'
    expect(error.message).toContain('could not be found')
  })

  it('has a safe localized fallback for unknown validation codes', () => {
    expect(localizedBuilderIssueMessage('future_code', 'Future warning', 'zh-TW')).not.toBe('Future warning')
    expect(localizedBuilderIssueMessage('future_code', 'Future warning', 'en')).toBe('Future warning')
    expect(localizedDisabledReason('Unavailable', 'zh-TW')).toBe('此選項目前無法選擇。')
  })
})
