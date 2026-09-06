import { describe, expect, it } from 'vitest'

import { ROOM_ERROR_CODES, roomCopy, roomErrorMessage } from './copy'

describe('Room error message SSOT', () => {
  for (const locale of ['en', 'zh-TW'] as const) {
    it(`covers every P2-A stable Room error code in ${locale}`, () => {
      const fallback = roomCopy(locale).requestError
      const messages = ROOM_ERROR_CODES.map((code) => roomErrorMessage(locale, code))

      expect(new Set(messages).size).toBe(ROOM_ERROR_CODES.length)
      for (const [index, code] of ROOM_ERROR_CODES.entries()) {
        expect(messages[index]).not.toBe(fallback)
        expect(messages[index]).not.toContain(code)
      }
    })
  }

  it('uses the localized generic fallback for unknown codes', () => {
    expect(roomErrorMessage('en', 'room_future_error')).toBe(roomCopy('en').requestError)
    expect(roomErrorMessage('zh-TW', 'room_future_error')).toBe(roomCopy('zh-TW').requestError)
  })
})
