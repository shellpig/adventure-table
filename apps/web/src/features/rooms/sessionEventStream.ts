import type { SessionResume, TableEvent, TableEventPage } from '../../api/sessions'

export type SessionEventStreamState = {
  sessionId: string
  cursor: number
  currentSeq: number
  historyFloorSeq: number
  events: TableEvent[]
}

export function hasOlderHistory(state: SessionEventStreamState): boolean {
  return state.historyFloorSeq > 0
}

function mergeEvents(current: TableEvent[], incoming: TableEvent[]): TableEvent[] {
  const bySeq = new Map<number, TableEvent>()
  for (const event of current) bySeq.set(event.seq, event)
  for (const event of incoming) {
    // Durable (session_id, seq) is unique. A duplicate page is idempotent; if a
    // contradictory event somehow arrives for an existing seq, keep the first
    // committed projection rather than mutating already-rendered history.
    if (!bySeq.has(event.seq)) bySeq.set(event.seq, event)
  }
  return [...bySeq.values()].sort((left, right) => left.seq - right.seq)
}

export function mergeResumeStream(
  current: SessionEventStreamState | null,
  next: SessionEventStreamState | null,
): SessionEventStreamState | null {
  if (next === null || current === null || current.sessionId !== next.sessionId) return next
  // A Resume that resolves after the incremental poll already delivered events
  // must not erase them. The poll owns its own cursor and never re-sends a page
  // it has handed over, so a replaced buffer would lose those events until the
  // next full Resume.
  return {
    sessionId: next.sessionId,
    cursor: Math.max(current.cursor, next.cursor),
    currentSeq: Math.max(current.currentSeq, next.currentSeq),
    historyFloorSeq: Math.min(current.historyFloorSeq, next.historyFloorSeq),
    events: mergeEvents(current.events, next.events),
  }
}

export function eventStreamFromResume(resume: SessionResume): SessionEventStreamState | null {
  const sessionId = resume.active_session?.id
  const runtime = resume.table_runtime ?? null
  if (!sessionId || !runtime || runtime.session_id !== sessionId) return null

  const initialPage = resume.recent_events ?? null
  const matchingRecentPage = initialPage?.session_id === sessionId ? initialPage : null

  // Resume provides a recent page ending at the runtime head; older history before
  // after_seq is paged backward on demand. When absent, replay from seq 0.
  if (matchingRecentPage) {
    return {
      sessionId,
      cursor: matchingRecentPage.cursor,
      currentSeq: Math.max(runtime.last_event_seq, matchingRecentPage.current_seq),
      historyFloorSeq: matchingRecentPage.after_seq,
      events: mergeEvents([], matchingRecentPage.events),
    }
  }

  return {
    sessionId,
    cursor: 0,
    currentSeq: runtime.last_event_seq,
    historyFloorSeq: 0,
    events: [],
  }
}

export function applySessionEventPage(
  state: SessionEventStreamState,
  page: TableEventPage,
): SessionEventStreamState {
  if (page.session_id !== state.sessionId) return state
  if (page.cursor < state.cursor) return state

  return {
    sessionId: state.sessionId,
    cursor: Math.max(state.cursor, page.cursor),
    currentSeq: Math.max(state.currentSeq, page.current_seq),
    historyFloorSeq: state.historyFloorSeq,
    events: mergeEvents(state.events, page.events),
  }
}

export function applySessionHistoryPage(
  state: SessionEventStreamState,
  page: TableEventPage,
): SessionEventStreamState {
  if (page.session_id !== state.sessionId) return state

  return {
    sessionId: state.sessionId,
    cursor: Math.max(state.cursor, page.cursor),
    currentSeq: Math.max(state.currentSeq, page.current_seq),
    historyFloorSeq: Math.min(state.historyFloorSeq, page.after_seq),
    events: mergeEvents(state.events, page.events),
  }
}
