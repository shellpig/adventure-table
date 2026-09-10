import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { sessionCopy } from './sessionCopy'
import {
  buildQuickRollInput,
  SessionQuickDicePanel,
} from './SessionQuickDicePanel'

const SEAT = '40000000-0000-4000-8000-000000000001'

describe('Quick Dice panel', () => {
  it('builds convenience dice input independently of formal RollRequest identity', () => {
    expect(buildQuickRollInput({
      subjectSeatId: SEAT,
      diceCount: '2',
      dieSides: '6',
      flatAdjustment: '1',
      visibility: 'public',
    })).toEqual({
      subject_seat_id: SEAT,
      dice_count: 2,
      die_sides: 6,
      flat_adjustment: 1,
      visibility: 'public',
    })
  })

  it('rejects invalid convenience dice bounds', () => {
    expect(buildQuickRollInput({
      subjectSeatId: SEAT,
      diceCount: '0',
      dieSides: '6',
      flatAdjustment: '0',
      visibility: 'public',
    })).toBeNull()
    expect(buildQuickRollInput({
      subjectSeatId: SEAT,
      diceCount: '1',
      dieSides: '1',
      flatAdjustment: '0',
      visibility: 'public',
    })).toBeNull()
  })

  it('renders only when at least one genuinely controlled Player Seat is supplied', () => {
    const copy = sessionCopy('en')
    expect(renderToStaticMarkup(createElement(SessionQuickDicePanel, {
      roomId: 'room',
      campaignId: 'campaign',
      sessionId: 'session',
      token: 'token',
      targets: [],
      copy,
      onError: () => undefined,
    }))).toBe('')

    const html = renderToStaticMarkup(createElement(SessionQuickDicePanel, {
      roomId: 'room',
      campaignId: 'campaign',
      sessionId: 'session',
      token: 'token',
      targets: [{ seatId: SEAT, label: 'Mira' }],
      copy,
      onError: () => undefined,
    }))
    expect(html).toContain(copy.quickDiceTitle)
    expect(html).toContain('Mira')
    expect(html).toContain(copy.quickRoll)
  })
})
