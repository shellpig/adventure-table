import { describe, expect, it } from 'vitest'

import {
  P2A_ROOM_REQUEST_CODES,
  ROOM_REQUEST_CODE_MESSAGES,
  localizedRoomRequestMessage,
} from './roomMessages'

describe('Room request messages', () => {
  for (const locale of ['en', 'zh-TW'] as const) {
    it(`covers every P2-A stable Room error code in ${locale}`, () => {
      const messages = P2A_ROOM_REQUEST_CODES.map(
        (code) => ROOM_REQUEST_CODE_MESSAGES[code][locale],
      )

      expect(new Set(messages).size).toBe(P2A_ROOM_REQUEST_CODES.length)
      for (const [index, code] of P2A_ROOM_REQUEST_CODES.entries()) {
        expect(messages[index]).not.toContain(code)
      }
    })
  }

  it('falls back without exposing an unknown raw code', () => {
    expect(localizedRoomRequestMessage('room_future_error', 500, 'server detail', 'en')).toBe(
      'server detail',
    )
    expect(localizedRoomRequestMessage('room_future_error', 500, 'server detail', 'zh-TW')).toBe(
      'Room 請求失敗（HTTP 500），請稍後再試。',
    )
  })
})
