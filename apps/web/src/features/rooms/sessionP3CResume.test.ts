import { describe, expect, it } from 'vitest'

import type { PendingActionView, RollRequestView } from '../../api/p3c'
import type { SessionResume } from '../../api/sessions'
import { EMPTY_SESSION_P3C_RESUME, p3cResumeTruthForSession } from './sessionP3CResume'

const SESSION_ID = '10000000-0000-4000-8000-000000000001'

function resume(overrides: Partial<SessionResume>): SessionResume {
  return {
    room_id: '20000000-0000-4000-8000-000000000001',
    campaign_id: '30000000-0000-4000-8000-000000000001',
    room: {} as SessionResume['room'],
    campaign: {} as SessionResume['campaign'],
    active_session: { id: SESSION_ID } as SessionResume['active_session'],
    participants: [],
    seats: [],
    active_characters: [],
    caller_access_session_id: null,
    ...overrides,
  }
}

describe('P3-C Session Resume truth', () => {
  it('projects canonical roll and pending truth only for the requested active Session', () => {
    const rollRequest = { id: 'roll-request' } as RollRequestView
    const pendingAction = { id: 'pending-action' } as PendingActionView
    const truth = p3cResumeTruthForSession(resume({
      roll_requests: [rollRequest],
      pending_actions: [pendingAction],
    }), SESSION_ID)

    expect(truth.rollRequests).toEqual([rollRequest])
    expect(truth.pendingActions).toEqual([pendingAction])
  })

  it('fails closed for another or absent active Session', () => {
    expect(p3cResumeTruthForSession(resume({
      active_session: { id: 'another-session' } as SessionResume['active_session'],
    }), SESSION_ID)).toBe(EMPTY_SESSION_P3C_RESUME)
    expect(p3cResumeTruthForSession(resume({ active_session: null }), SESSION_ID)).toBe(
      EMPTY_SESSION_P3C_RESUME,
    )
  })
})
