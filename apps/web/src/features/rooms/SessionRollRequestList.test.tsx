import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { RollRequestView } from '../../api/p3c'
import type { TableEvent } from '../../api/sessions'
import { sessionCopy } from './sessionCopy'
import {
  SessionRollRequestList,
  visibleRollResultTotal,
} from './SessionRollRequestList'

const REQUEST_ID = '50000000-0000-4000-8000-000000000001'
const SEAT_ID = '40000000-0000-4000-8000-000000000001'

const pendingRequest: RollRequestView = {
  id: REQUEST_ID,
  session_id: 'session',
  roll_group_id: 'group',
  target_seat_id: SEAT_ID,
  target_character_id: 'character',
  request_type: 'skill',
  ability_ref: null,
  skill_ref: 'srd5.1:skill:perception',
  dc: null,
  modifier_mode: 'normal',
  flat_adjustment: 0,
  visibility: 'roller_and_dm',
  status: 'pending',
  requested_by_seat_id: 'dm-seat',
  version: 1,
}

function resolvedEvent(total: number): TableEvent {
  return {
    id: '60000000-0000-4000-8000-000000000001',
    session_id: 'session',
    seq: 9,
    kind: 'roll.resolved',
    acting_seat_id: SEAT_ID,
    subject_seat_id: SEAT_ID,
    subject_character_id: 'character',
    execution_mode: 'self',
    visibility: 'actor_and_dm',
    recipient_seat_ids: [SEAT_ID],
    payload_version: 1,
    payload: { roll_request_id: REQUEST_ID, total },
    created_at: '2026-09-09T00:00:00Z',
  }
}

describe('formal RollRequest list', () => {
  it('reads only server-filtered roll.resolved events for visible totals', () => {
    expect(visibleRollResultTotal(REQUEST_ID, [resolvedEvent(17)])).toBe(17)
    expect(visibleRollResultTotal('other-request', [resolvedEvent(17)])).toBeNull()
  })

  it('renders a server-roll action for a controlled pending Seat', () => {
    const copy = sessionCopy('en')
    const html = renderToStaticMarkup(createElement(SessionRollRequestList, {
      roomId: 'room',
      campaignId: 'campaign',
      sessionId: 'session',
      token: 'token',
      isCurrentDm: false,
      controlledSeatIds: [SEAT_ID],
      events: [],
      copy,
      onError: () => undefined,
      initialRequests: [pendingRequest],
    }))
    expect(html).toContain(copy.rollRequestsTitle)
    expect(html).toContain(copy.rollButton)
    expect(html).not.toContain('DC ')
  })

  it('shows a visible resolved total from the durable event projection', () => {
    const copy = sessionCopy('zh-TW')
    const html = renderToStaticMarkup(createElement(SessionRollRequestList, {
      roomId: 'room',
      campaignId: 'campaign',
      sessionId: 'session',
      token: 'token',
      isCurrentDm: true,
      controlledSeatIds: [],
      events: [resolvedEvent(19)],
      copy,
      onError: () => undefined,
      initialRequests: [{ ...pendingRequest, status: 'resolved', dc: 14 }],
    }))
    expect(html).toContain(`${copy.rollTotal}: 19`)
    expect(html).toContain('DC 14')
    expect(html).not.toContain(copy.rollButton)
  })
})
