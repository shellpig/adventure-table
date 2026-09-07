import { describe, expect, it } from 'vitest'

import { localizedRequestErrorMessage } from './systemMessages'

describe('P2-E live Character request messages', () => {
  it('explains active Session control instead of falling back to revision-conflict retry copy', () => {
    const zh = localizedRequestErrorMessage(
      'character_in_active_session',
      409,
      'Character is controlled by another participant in an active Session',
      'zh-TW',
    )
    const en = localizedRequestErrorMessage(
      'character_in_active_session',
      409,
      'Character is controlled by another participant in an active Session',
      'en',
    )

    expect(zh).toContain('Session')
    expect(zh).toContain('Player Seat')
    expect(zh).not.toContain('重新載入')
    expect(en).toContain('active Session')
    expect(en).not.toContain('Reload')
  })
})
