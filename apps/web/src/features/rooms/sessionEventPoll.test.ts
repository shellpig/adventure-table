import { afterEach, describe, expect, it, vi } from 'vitest'

import { SessionApiError, type TableEvent, type TableEventPage } from '../../api/sessions'
import { applySessionEventPage, type SessionEventStreamState } from './sessionEventStream'
import {
  abortableDelay,
  runSessionEventPoll,
  SESSION_EVENT_RETRY_INITIAL_MS,
  SESSION_EVENT_RETRY_MAX_MS,
} from './sessionEventPoll'

const SESSION_ID = '30000000-0000-4000-8000-000000000001'

function event(seq: number): TableEvent {
  return {
    id: `40000000-0000-4000-8000-${String(seq).padStart(12, '0')}`,
    session_id: SESSION_ID,
    seq,
    kind: 'test.event',
    acting_seat_id: null,
    subject_seat_id: null,
    subject_character_id: null,
    execution_mode: 'system',
    visibility: 'public',
    recipient_seat_ids: [],
    payload_version: 1,
    payload: { seq },
    created_at: '2026-09-08T00:00:00Z',
  }
}

function page(cursor: number, events: TableEvent[] = []): TableEventPage {
  return {
    session_id: SESSION_ID,
    after_seq: 0,
    cursor,
    current_seq: cursor,
    has_more: false,
    events,
  }
}

afterEach(() => {
  vi.useRealTimers()
})

describe('Session event long-poll reconnect', () => {
  it('retries a transient failure with the same cursor and returns to connected after success', async () => {
    vi.useFakeTimers()
    const controller = new AbortController()
    const cursors: number[] = []
    const statuses: string[] = []
    let attempt = 0

    const done = runSessionEventPoll({
      initialCursor: 7,
      signal: controller.signal,
      wait: async (cursor) => {
        cursors.push(cursor)
        attempt += 1
        if (attempt === 1) throw new TypeError('temporary network failure')
        return page(9)
      },
      onPage: () => controller.abort(),
      onStatus: (status) => statuses.push(status),
      onFatal: () => undefined,
    })

    await Promise.resolve()
    expect(cursors).toEqual([7])
    expect(statuses).toEqual(['reconnecting'])
    await vi.advanceTimersByTimeAsync(SESSION_EVENT_RETRY_INITIAL_MS)
    await done

    expect(cursors).toEqual([7, 7])
    expect(statuses).toEqual(['reconnecting', 'connected'])
  })

  it('increases backoff and caps it at 30 seconds', async () => {
    const controller = new AbortController()
    const delays: number[] = []

    await runSessionEventPoll({
      initialCursor: 0,
      signal: controller.signal,
      wait: async () => {
        throw new TypeError('offline')
      },
      onPage: () => undefined,
      onStatus: () => undefined,
      onFatal: () => undefined,
      sleep: async (delayMs) => {
        delays.push(delayMs)
        if (delays.length === 7) controller.abort()
      },
    })

    expect(delays).toEqual([
      1_000,
      2_000,
      4_000,
      8_000,
      16_000,
      SESSION_EVENT_RETRY_MAX_MS,
      SESSION_EVENT_RETRY_MAX_MS,
    ])
  })

  it('resets backoff after success and keeps cursor/reducer idempotency across an overlapping reconnect page', async () => {
    const controller = new AbortController()
    const cursors: number[] = []
    const delays: number[] = []
    let attempt = 0
    let state: SessionEventStreamState = {
      sessionId: SESSION_ID,
      cursor: 2,
      currentSeq: 2,
      events: [event(1), event(2)],
    }

    await runSessionEventPoll({
      initialCursor: state.cursor,
      signal: controller.signal,
      wait: async (cursor) => {
        cursors.push(cursor)
        attempt += 1
        if (attempt === 1) throw new TypeError('brief outage')
        if (attempt === 2) return page(4, [event(2), event(3), event(4)])
        throw new TypeError('second brief outage')
      },
      onPage: (nextPage) => {
        state = applySessionEventPage(state, nextPage)
      },
      onStatus: () => undefined,
      onFatal: () => undefined,
      sleep: async (delayMs) => {
        delays.push(delayMs)
        if (delays.length === 2) controller.abort()
      },
    })

    expect(cursors).toEqual([2, 2, 4])
    expect(delays).toEqual([SESSION_EVENT_RETRY_INITIAL_MS, SESSION_EVENT_RETRY_INITIAL_MS])
    expect(state.cursor).toBe(4)
    expect(state.events.map((item) => item.seq)).toEqual([1, 2, 3, 4])
  })

  it('treats AbortError and cleanup aborts as normal termination without retry timers', async () => {
    const abortController = new AbortController()
    const onStatus = vi.fn()
    await runSessionEventPoll({
      initialCursor: 0,
      signal: abortController.signal,
      wait: async () => {
        const error = new Error('aborted')
        error.name = 'AbortError'
        throw error
      },
      onPage: () => undefined,
      onStatus,
      onFatal: () => undefined,
    })
    expect(onStatus).not.toHaveBeenCalled()

    vi.useFakeTimers()
    const cleanupController = new AbortController()
    const cleanupDone = runSessionEventPoll({
      initialCursor: 0,
      signal: cleanupController.signal,
      wait: async () => {
        throw new TypeError('temporary network failure')
      },
      onPage: () => undefined,
      onStatus: (status) => {
        if (status === 'reconnecting') cleanupController.abort()
      },
      onFatal: () => undefined,
    })
    await Promise.resolve()
    await cleanupDone
    expect(vi.getTimerCount()).toBe(0)
  })

  it.each([403, 404])('stops on fatal HTTP %s and reports the error', async (status) => {
    const onFatal = vi.fn()
    const onStatus = vi.fn()
    const wait = vi.fn(async () => {
      throw new SessionApiError(status, 'session_access_denied', 'fatal')
    })

    await runSessionEventPoll({
      initialCursor: 3,
      signal: new AbortController().signal,
      wait,
      onPage: () => undefined,
      onStatus,
      onFatal,
    })

    expect(wait).toHaveBeenCalledTimes(1)
    expect(onStatus).toHaveBeenLastCalledWith('fatal')
    expect(onFatal).toHaveBeenCalledTimes(1)
  })

  it('clears the default retry timer when the signal aborts during backoff', async () => {
    vi.useFakeTimers()
    const controller = new AbortController()
    const delay = abortableDelay(30_000, controller.signal)
    expect(vi.getTimerCount()).toBe(1)
    controller.abort()
    await expect(delay).rejects.toMatchObject({ name: 'AbortError' })
    expect(vi.getTimerCount()).toBe(0)
  })
})
