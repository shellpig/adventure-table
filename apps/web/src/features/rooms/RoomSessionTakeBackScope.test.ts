import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'


describe('Session Take Back scope integration', () => {
  it('uses the caller-specific Resume projection instead of guessing identity in the browser', () => {
    const page = readFileSync(new URL('./RoomSessionPage.tsx', import.meta.url), 'utf8')
    const panel = readFileSync(new URL('./PlayerAIControlPanel.tsx', import.meta.url), 'utf8')
    const api = readFileSync(new URL('../../api/sessions.ts', import.meta.url), 'utf8')

    expect(api).toContain('self_take_back_seat_ids?: string[]')
    expect(page).toContain('setSelfTakeBackSeatIds(new Set(nextResume.self_take_back_seat_ids ?? []))')
    expect(page).toContain('canSelfTakeBack={selfTakeBackSeatIds.has(currentSeat.id)}')
    expect(panel).toContain('canSelfTakeBack ? copy.takeBackExactOriginHint')
    expect(panel).toContain('{canSelfTakeBack ? (')
    expect(panel).not.toContain('display_name ===')
    expect(panel).not.toContain('controller_display_name ===')
  })
})
