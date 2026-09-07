import { describe, expect, it } from 'vitest'

import { SeatApiError } from '../api/seats'
import { localizedSeatRequestMessage } from './seatMessages'

describe('P2-E Seat request messages', () => {
  it('localizes Session-history deletion conflicts in both locales', () => {
    expect(localizedSeatRequestMessage(
      'seat_history_referenced',
      409,
      'Seat is referenced by Session history',
      'zh-TW',
    )).toContain('Session 歷史紀錄')
    expect(localizedSeatRequestMessage(
      'seat_history_referenced',
      409,
      'Seat is referenced by Session history',
      'en',
    )).toContain('Session history')
  })

  it('keeps zh-TW Lobby errors from leaking the raw server message', () => {
    const error = new SeatApiError(
      409,
      'seat_history_referenced',
      'Seat is referenced by Session history and cannot be hard deleted',
    )
    expect(error.message).toContain('封存')
    expect(error.message).not.toContain('hard deleted')
  })
})
