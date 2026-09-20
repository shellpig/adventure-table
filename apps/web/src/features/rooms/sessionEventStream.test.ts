import { describe, expect, it } from 'vitest'

import type {
  SessionHistoryLink,
  SessionResume,
  SessionSnapshot,
  TableEvent,
  TableEventPage,
} from '../../api/sessions'
import {
  applyOlderSessionPage,
  applySessionEventPage,
  applySessionHistoryPage,
  emptyHistoryChain,
  eventStreamFromResume,
  hasOlderHistory,
  mergeResumeStream,
  nextHistoryRequest,
  pushOlderSession,
  type OlderSessionHistory,
  type SessionEventStreamState,
  type SessionHistoryChain,
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
    expect(state?.historyFloorSeq).toBe(0)
    expect(state?.events.map((item) => item.seq)).toEqual([1, 2])
  })

  it('reports no older history when Resume has after_seq === 0', () => {
    const state = eventStreamFromResume(resume())
    expect(state).not.toBeNull()
    expect(state?.historyFloorSeq).toBe(0)
    expect(hasOlderHistory(state!, { older: [], exhausted: true })).toBe(false)
  })

  it('continues from cursor and reports older history when Resume has after_seq > 0', () => {
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
    const state = eventStreamFromResume(longResume)
    expect(state).not.toBeNull()
    expect(state?.cursor).toBe(120)
    expect(state?.currentSeq).toBe(120)
    expect(state?.historyFloorSeq).toBe(70)
    expect(hasOlderHistory(state!, { older: [], exhausted: true })).toBe(true)
    expect(state?.events.map((item) => item.seq)).toEqual([119, 120])
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
    expect(once.historyFloorSeq).toBe(0)
    expect(twice.events.map((item) => item.seq)).toEqual([1, 2, 3, 4])
    expect(twice.events).toHaveLength(4)
  })

  it('prepends older events, keeps ascending order, dedupes, lowers historyFloorSeq, and ignores wrong-Session pages in applySessionHistoryPage', () => {
    const initial = eventStreamFromResume(resume())!
    const advanced: SessionEventStreamState = {
      ...initial,
      cursor: 100,
      currentSeq: 100,
      historyFloorSeq: 50,
      events: [event(60), event(100)],
    }
    const historyPage: TableEventPage = {
      session_id: SESSION_ID,
      after_seq: 20,
      cursor: 49,
      current_seq: 100,
      has_more: true,
      events: [event(30), event(60)],
    }
    const updated = applySessionHistoryPage(advanced, historyPage)

    expect(updated.historyFloorSeq).toBe(20)
    expect(hasOlderHistory(updated, { older: [], exhausted: true })).toBe(true)
    expect(updated.events.map((e) => e.seq)).toEqual([30, 60, 100])
    expect(updated.cursor).toBe(100)
    expect(updated.currentSeq).toBe(100)

    const wrongSessionPage: TableEventPage = {
      session_id: '30000000-0000-4000-8000-000000000099',
      after_seq: 0,
      cursor: 19,
      current_seq: 100,
      has_more: false,
      events: [event(10)],
    }
    const ignored = applySessionHistoryPage(updated, wrongSessionPage)
    expect(ignored).toBe(updated)
  })

  it('keeps both history and poll ranges after an incremental poll page with no 200 cap', () => {
    const initial: SessionEventStreamState = {
      sessionId: SESSION_ID,
      cursor: 100,
      currentSeq: 100,
      historyFloorSeq: 50,
      events: [event(60), event(100)],
    }
    const historyPage: TableEventPage = {
      session_id: SESSION_ID,
      after_seq: 0,
      cursor: 49,
      current_seq: 100,
      has_more: false,
      events: Array.from({ length: 150 }, (_, i) => event(i + 1)),
    }
    const withHistory = applySessionHistoryPage(initial, historyPage)

    const pollPage: TableEventPage = {
      session_id: SESSION_ID,
      after_seq: 100,
      cursor: 220,
      current_seq: 220,
      has_more: false,
      events: Array.from({ length: 120 }, (_, i) => event(101 + i)),
    }
    const withPoll = applySessionEventPage(withHistory, pollPage)

    expect(withPoll.events).toHaveLength(220)
    expect(withPoll.events[0].seq).toBe(1)
    expect(withPoll.events[withPoll.events.length - 1].seq).toBe(220)
    expect(withPoll.historyFloorSeq).toBe(0)
    expect(hasOlderHistory(withPoll, { older: [], exhausted: true })).toBe(false)
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
    expect(state?.historyFloorSeq).toBe(0)
    expect(state?.events).toEqual([])
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
    expect(merged?.historyFloorSeq).toBe(0)
  })

  it('replaces the stream for a different Session or a caller without projection', () => {
    const live = eventStreamFromResume(resume())!
    const otherSession = { ...live, sessionId: '30000000-0000-4000-8000-000000000002' }

    expect(mergeResumeStream(live, otherSession)).toEqual(otherSession)
    expect(mergeResumeStream(live, null)).toBeNull()
    expect(mergeResumeStream(null, live)).toEqual(live)
  })
})

function sessionSnapshot(id: string): SessionSnapshot {
  return {
    id,
    campaign_id: '20000000-0000-4000-8000-000000000001',
    status: 'ended',
    dm_seat_id: '40000000-0000-4000-8000-000000000001',
    dm_controller_access_session_id: null,
    started_at: '2026-09-01T00:00:00Z',
    ended_at: '2026-09-01T02:00:00Z',
    participants: [],
  }
}

function streamState(historyFloorSeq: number, sessionId = SESSION_ID): SessionEventStreamState {
  return {
    sessionId,
    cursor: 10,
    currentSeq: 10,
    historyFloorSeq,
    events: [],
  }
}

describe('Session history chain & cross-session paging', () => {
  describe('hasOlderHistory', () => {
    it('(a) returns true when current floor > 0 regardless of chain', () => {
      const state = streamState(5)
      expect(hasOlderHistory(state, { older: [], exhausted: true })).toBe(true)
      expect(hasOlderHistory(state, { older: [], exhausted: false })).toBe(true)
      expect(
        hasOlderHistory(state, {
          older: [
            {
              session: sessionSnapshot('prev-1'),
              lastEventSeq: 10,
              historyFloorSeq: 0,
              events: [],
            },
          ],
          exhausted: true,
        }),
      ).toBe(true)
    })

    it('(b) returns true when floor is 0, chain is empty, and exhausted is false', () => {
      const state = streamState(0)
      expect(hasOlderHistory(state, emptyHistoryChain())).toBe(true)
      expect(hasOlderHistory(state, { older: [], exhausted: false })).toBe(true)
    })

    it('(c) returns true when floor is 0 and older[last].historyFloorSeq > 0', () => {
      const state = streamState(0)
      const chain: SessionHistoryChain = {
        older: [
          {
            session: sessionSnapshot('prev-1'),
            lastEventSeq: 20,
            historyFloorSeq: 0,
            events: [],
          },
          {
            session: sessionSnapshot('prev-2'),
            lastEventSeq: 15,
            historyFloorSeq: 8,
            events: [],
          },
        ],
        exhausted: true,
      }
      expect(hasOlderHistory(state, chain)).toBe(true)
    })

    it('(d) returns false when floor is 0, exhausted is true, and all older floors are 0', () => {
      const state = streamState(0)
      expect(hasOlderHistory(state, { older: [], exhausted: true })).toBe(false)

      const chain: SessionHistoryChain = {
        older: [
          {
            session: sessionSnapshot('prev-1'),
            lastEventSeq: 10,
            historyFloorSeq: 0,
            events: [],
          },
          {
            session: sessionSnapshot('prev-2'),
            lastEventSeq: 5,
            historyFloorSeq: 0,
            events: [],
          },
        ],
        exhausted: true,
      }
      expect(hasOlderHistory(state, chain)).toBe(false)
    })
  })

  describe('pushOlderSession', () => {
    it('sets exhausted true and leaves older unchanged when previous is null', () => {
      const initial: SessionHistoryChain = {
        older: [
          {
            session: sessionSnapshot('prev-1'),
            lastEventSeq: 10,
            historyFloorSeq: 0,
            events: [],
          },
        ],
        exhausted: false,
      }
      const link: SessionHistoryLink = {
        session_id: 'prev-1',
        previous_session: null,
        previous_last_event_seq: 0,
      }
      const result = pushOlderSession(initial, link, null)
      expect(result.exhausted).toBe(true)
      expect(result.older).toEqual(initial.older)
    })

    it('appends entry with lastEventSeq, historyFloorSeq, and events when previous and page match', () => {
      const initial = emptyHistoryChain()
      const prevSession = sessionSnapshot('prev-1')
      const link: SessionHistoryLink = {
        session_id: SESSION_ID,
        previous_session: prevSession,
        previous_last_event_seq: 50,
      }
      const page: TableEventPage = {
        session_id: 'prev-1',
        after_seq: 20,
        cursor: 50,
        current_seq: 50,
        has_more: true,
        events: [
          { ...event(30), session_id: 'prev-1' },
          { ...event(25), session_id: 'prev-1' },
        ],
      }
      const result = pushOlderSession(initial, link, page)
      expect(result.exhausted).toBe(false)
      expect(result.older).toHaveLength(1)
      expect(result.older[0]).toEqual({
        session: prevSession,
        lastEventSeq: 50,
        historyFloorSeq: 20,
        events: [
          { ...event(25), session_id: 'prev-1' },
          { ...event(30), session_id: 'prev-1' },
        ],
      })
    })

    it('appends entry with empty events and floor 0 when page is for a different session_id', () => {
      const initial = emptyHistoryChain()
      const prevSession = sessionSnapshot('prev-1')
      const link: SessionHistoryLink = {
        session_id: SESSION_ID,
        previous_session: prevSession,
        previous_last_event_seq: 50,
      }
      const wrongPage: TableEventPage = {
        session_id: 'other-session-id',
        after_seq: 20,
        cursor: 50,
        current_seq: 50,
        has_more: true,
        events: [event(30)],
      }
      const result = pushOlderSession(initial, link, wrongPage)
      expect(result.older).toHaveLength(1)
      expect(result.older[0]).toEqual({
        session: prevSession,
        lastEventSeq: 50,
        historyFloorSeq: 0,
        events: [],
      })
    })

    it('appends entry with empty events and leaves exhausted false for previous_last_event_seq 0 with empty page', () => {
      const initial = emptyHistoryChain()
      const prevSession = sessionSnapshot('prev-empty')
      const link: SessionHistoryLink = {
        session_id: SESSION_ID,
        previous_session: prevSession,
        previous_last_event_seq: 0,
      }
      const emptyPage: TableEventPage = {
        session_id: 'prev-empty',
        after_seq: 0,
        cursor: 0,
        current_seq: 0,
        has_more: false,
        events: [],
      }
      const result = pushOlderSession(initial, link, emptyPage)
      expect(result.exhausted).toBe(false)
      expect(result.older).toHaveLength(1)
      expect(result.older[0]).toEqual({
        session: prevSession,
        lastEventSeq: 0,
        historyFloorSeq: 0,
        events: [],
      })
    })
  })

  describe('applyOlderSessionPage', () => {
    it('merges into the matching Session only, dedupes seq, takes min historyFloorSeq', () => {
      const prev1 = sessionSnapshot('prev-1')
      const prev2 = sessionSnapshot('prev-2')
      const chain: SessionHistoryChain = {
        older: [
          {
            session: prev1,
            lastEventSeq: 100,
            historyFloorSeq: 60,
            events: [{ ...event(70), session_id: 'prev-1' }],
          },
          {
            session: prev2,
            lastEventSeq: 50,
            historyFloorSeq: 30,
            events: [{ ...event(40), session_id: 'prev-2' }],
          },
        ],
        exhausted: false,
      }
      const page: TableEventPage = {
        session_id: 'prev-1',
        after_seq: 20,
        cursor: 69,
        current_seq: 100,
        has_more: true,
        events: [
          { ...event(30), session_id: 'prev-1' },
          { ...event(70), session_id: 'prev-1' },
        ],
      }
      const result = applyOlderSessionPage(chain, page)
      expect(result.older[0].historyFloorSeq).toBe(20)
      expect(result.older[0].events.map((e) => e.seq)).toEqual([30, 70])
      expect(result.older[1]).toEqual(chain.older[1])
    })

    it('returns the same object reference (toBe) when session_id is unknown', () => {
      const chain: SessionHistoryChain = {
        older: [
          {
            session: sessionSnapshot('prev-1'),
            lastEventSeq: 50,
            historyFloorSeq: 20,
            events: [],
          },
        ],
        exhausted: false,
      }
      const unknownPage: TableEventPage = {
        session_id: 'unknown-session-id',
        after_seq: 10,
        cursor: 19,
        current_seq: 50,
        has_more: false,
        events: [],
      }
      expect(applyOlderSessionPage(chain, unknownPage)).toBe(chain)
    })
  })

  describe('nextHistoryRequest', () => {
    it('returns the four outcomes in order', () => {
      // 1. Current stream floor > 0 -> 'current'
      expect(nextHistoryRequest(streamState(10), emptyHistoryChain())).toEqual({
        kind: 'current',
        beforeSeq: 11,
      })

      // 2. Current floor 0, older[last] floor > 0 -> 'older'
      const chainWithOlderFloor: SessionHistoryChain = {
        older: [
          {
            session: sessionSnapshot('prev-1'),
            lastEventSeq: 50,
            historyFloorSeq: 0,
            events: [],
          },
          {
            session: sessionSnapshot('prev-2'),
            lastEventSeq: 30,
            historyFloorSeq: 15,
            events: [],
          },
        ],
        exhausted: false,
      }
      expect(nextHistoryRequest(streamState(0), chainWithOlderFloor)).toEqual({
        kind: 'older',
        sessionId: 'prev-2',
        beforeSeq: 16,
      })

      // 3. Current floor 0, older[last] floor 0, not exhausted -> 'previous'
      const chainOlderFloorZero: SessionHistoryChain = {
        older: [
          {
            session: sessionSnapshot('prev-1'),
            lastEventSeq: 50,
            historyFloorSeq: 0,
            events: [],
          },
        ],
        exhausted: false,
      }
      expect(nextHistoryRequest(streamState(0), chainOlderFloorZero)).toEqual({
        kind: 'previous',
        baseSessionId: 'prev-1',
      })
      expect(nextHistoryRequest(streamState(0), emptyHistoryChain())).toEqual({
        kind: 'previous',
        baseSessionId: SESSION_ID,
      })

      // 4. Current floor 0, exhausted true -> null
      expect(nextHistoryRequest(streamState(0), { older: [], exhausted: true })).toBeNull()
      expect(
        nextHistoryRequest(streamState(0), {
          older: [
            {
              session: sessionSnapshot('prev-1'),
              lastEventSeq: 50,
              historyFloorSeq: 0,
              events: [],
            },
          ],
          exhausted: true,
        }),
      ).toBeNull()
    })

    it('returns previous with base = oldest id after two consecutive empty older Sessions', () => {
      let chain = emptyHistoryChain()

      const link1: SessionHistoryLink = {
        session_id: SESSION_ID,
        previous_session: sessionSnapshot('prev-1'),
        previous_last_event_seq: 0,
      }
      const page1: TableEventPage = {
        session_id: 'prev-1',
        after_seq: 0,
        cursor: 0,
        current_seq: 0,
        has_more: false,
        events: [],
      }
      chain = pushOlderSession(chain, link1, page1)

      const link2: SessionHistoryLink = {
        session_id: 'prev-1',
        previous_session: sessionSnapshot('prev-2'),
        previous_last_event_seq: 0,
      }
      const page2: TableEventPage = {
        session_id: 'prev-2',
        after_seq: 0,
        cursor: 0,
        current_seq: 0,
        has_more: false,
        events: [],
      }
      chain = pushOlderSession(chain, link2, page2)

      const next = nextHistoryRequest(streamState(0), chain)
      expect(next).toEqual({
        kind: 'previous',
        baseSessionId: 'prev-2',
      })
    })
  })
})
