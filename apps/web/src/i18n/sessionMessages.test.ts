import { describe, expect, it } from 'vitest'

import {
  P2E_SESSION_REQUEST_CODES,
  SESSION_REQUEST_CODE_MESSAGES,
  localizedSessionRequestMessage,
} from './sessionMessages'

describe('Session request message SSOT', () => {
  for (const locale of ['en', 'zh-TW'] as const) {
    it(`covers every P2-E stable Session error code in ${locale}`, () => {
      const messages = P2E_SESSION_REQUEST_CODES.map(
        (code) => SESSION_REQUEST_CODE_MESSAGES[code][locale],
      )

      expect(new Set(messages).size).toBe(P2E_SESSION_REQUEST_CODES.length)
      for (const [index, code] of P2E_SESSION_REQUEST_CODES.entries()) {
        expect(messages[index]).not.toContain(code)
      }
    })
  }

  it('falls back without exposing an unknown raw code', () => {
    expect(localizedSessionRequestMessage('session_future_error', 500, 'server detail', 'en')).toBe(
      'server detail',
    )
    expect(localizedSessionRequestMessage('session_future_error', 500, 'server detail', 'zh-TW')).toBe(
      'Session 請求失敗（HTTP 500），請稍後再試。',
    )
  })
})
