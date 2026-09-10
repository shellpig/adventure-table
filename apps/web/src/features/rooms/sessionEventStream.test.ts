import { describe, expect, it } from 'vitest'

import type { SessionResume, TableEvent, TableEventPage } from '../../api/sessions'
import {
  applySessionEventPage,
  eventStreamFromResume,
  mergeResumeStream,
} from './sessionEventStream'

const SESSION_ID = '30000000-0000-4000-8000-000000000001'

function event(seq: number, id = `event-${seq}`): TableEvent {
  return {
    id,
    session_id: SESSION_ID,
    seq,
    kind: 'diagnostic.test',
    acting_seat_id: null,
    subject_seat_id: null,
    subject_character_id: null,
    execution_mode: null,
    visibility: 'public',
    recipient_seat_ids: [],
    payload_version: 1,
    payload: { seq },
    created_at: '2026-09-08T00:00:00Z',
  }
}

function resume(): SessionResume {
  return {
    room_id: '10000000-0000-4000-8000-000000000001',
    campaign_id: '20000000-0000-4000-8000-000000000001',
    room: {} as SessionResume['room'],
    campaign: {} as SessionResume['campaign'],
    active_session: { id: SESSION_ID } as SessionResume['active_session'],
    participants: [],
    seats: [],
    active_characters: [],
    caller_access_session_id: null,
    table_runtime: {
      session_id: SESSION_ID,
      revision: 2,
      last_event_seq: 2,
    },
    recent_events: {
      session_id: SESSION_ID,
      after_seq: 0,
      cursor: 2,
      current_seq: 2,
      has_more: false,
      events: [event(1), event(2)],
    },
  }
}

describe('P3 Session event cursor reducer', () => {
  it('paints a complete Resume window and continues from its server-issued cursor', () => {
    const state = eventStreamFromResume(resume())
    expect(state).not.toBeNull()
    expect(state?.cursor).toBe(2)
    expect(state?.currentSeq).toBe(2)
    expect(state?.events.map((item) => item.seq)).toEqual([1, 2])
  })

  it('applies incremental pages and makes duplicate delivery idempotent', () => {
    const initial = eventStreamFromResume(resume())
    expect(initial).not.toBeNull()
    const page: TableEventPage = {
      session_id: SESSION_ID,
      after_seq: 2,
      cursor: 4,
      current_seq: 4,
      has_more: false,
      events: [event(3), event(4)],
    }
    const once = applySessionEventPage(initial!, page)
    const twice = applySessionEventPage(once, page)

    expect(once.cursor).toBe(4)
    expect(twice.events.map((item) => item.seq)).toEqual([1, 2, 3, 4])
    expect(twice.events).toHaveLength(4)
  })

  it('backfills caller-visible events before a bounded Resume window, including hidden raw gaps', () => {
    const longResume = resume()
    longResume.table_runtime!.last_event_seq = 120
    longResume.recent_events = {
      session_id: SESSION_ID,
      after_seq: 70,
      cursor: 120,
      current_seq: 120,
      has_more: false,
      events: [event(119), event(120)],
    }
    const initial = eventStreamFromResume(longResume)!

    const first = applySessionEventPage(initial, {
      session_id: SESSION_ID,
      after_seq: 0,
      cursor: 100,
      current_seq: 120,
      has_more: true,
      // The raw page may contain many private events for other seats. Only an
      // older caller-visible event survives server audience projection.
      events: [event(12)],
    })
    const second = applySessionEventPage(first, {
      session_id: SESSION_ID,
      after_seq: 100,
      cursor: 120,
      current_seq: 120,
      has_more: false,
      events: [event(119), event(120)],
    })

    expect(initial.cursor).toBe(0)
    expect(first.cursor).toBe(100)
    expect(second.cursor).toBe(120)
    expect(second.events.map((item) => item.seq)).toEqual([12, 119, 120])
  })

  it('ignores stale or wrong-Session pages instead of moving the cursor backward', () => {
    const initial = eventStreamFromResume(resume())!
    const advanced = applySessionEventPage(initial, {
      session_id: SESSION_ID,
      after_seq: 2,
      cursor: 5,
      current_seq: 5,
      has_more: false,
      events: [event(5)],
    })
    const stale = applySessionEventPage(advanced, {
      session_id: SESSION_ID,
      after_seq: 0,
      cursor: 2,
      current_seq: 2,
      has_more: true,
      events: [event(1, 'contradictory-id')],
    })
    const wrongSession = applySessionEventPage(advanced, {
      session_id: '30000000-0000-4000-8000-000000000099',
      after_seq: 5,
      cursor: 6,
      current_seq: 6,
      has_more: false,
      events: [],
    })

    expect(stale).toEqual(advanced)
    expect(wrongSession).toEqual(advanced)
    expect(advanced.cursor).toBe(5)
  })

  it('falls back to durable replay when a recent projection is absent', () => {
    const withoutRecent = resume()
    withoutRecent.table_runtime!.last_event_seq = 9
    withoutRecent.recent_events = null
    const state = eventStreamFromResume(withoutRecent)
    expect(state?.cursor).toBe(0)
    expect(state?.currentSeq).toBe(9)
    expect(state?.events).toEqual([])
  })

  it('falls back to durable replay when Resume cannot prove its recent page reached the runtime head', () => {
    const incompleteRecent = resume()
    incompleteRecent.table_runtime!.last_event_seq = 9
    incompleteRecent.recent_events = {
      session_id: SESSION_ID,
      after_seq: 0,
      cursor: 8,
      current_seq: 9,
      has_more: false,
      events: [event(8)],
    }
    const state = eventStreamFromResume(incompleteRecent)
    expect(state?.cursor).toBe(0)
    expect(state?.events.map((item) => item.seq)).toEqual([8])
  })

  it('does not invent an incremental stream for callers without P3 projection', () => {
    const noProjection = resume()
    noProjection.table_runtime = null
    noProjection.recent_events = null
    expect(eventStreamFromResume(noProjection)).toBeNull()
  })
})

describe('Resume merged into a live stream', () => {
  it('keeps poll-delivered events when a Resume resolves after them', () => {
    const live = applySessionEventPage(eventStreamFromResume(resume())!, {
      session_id: SESSION_ID,
      after_seq: 2,
      cursor: 3,
      current_seq: 3,
      has_more: false,
      events: [event(3)],
    })
    const staleResume = resume()

    const merged = mergeResumeStream(live, eventStreamFromResume(staleResume))

    expect(merged?.events.map((item) => item.seq)).toEqual([1, 2, 3])
    expect(merged?.cursor).toBe(3)
    expect(merged?.currentSeq).toBe(3)
  })

  it('replaces the stream for a different Session or a caller without projection', () => {
    const live = eventStreamFromResume(resume())!
    const otherSession = { ...live, sessionId: '30000000-0000-4000-8000-000000000002' }

    expect(mergeResumeStream(live, otherSession)).toEqual(otherSession)
    expect(mergeResumeStream(live, null)).toBeNull()
    expect(mergeResumeStream(null, live)).toEqual(live)
  })
})
