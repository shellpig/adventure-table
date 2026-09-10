import type { SessionResume, TableEvent, TableEventPage } from '../../api/sessions'

export type SessionEventStreamState = {
  sessionId: string
  cursor: number
  currentSeq: number
  events: TableEvent[]
}

const MAX_BUFFERED_EVENTS = 200

function mergeEvents(current: TableEvent[], incoming: TableEvent[]): TableEvent[] {
  const bySeq = new Map<number, TableEvent>()
  for (const event of current) bySeq.set(event.seq, event)
  for (const event of incoming) {
    // Durable (session_id, seq) is unique. A duplicate page is idempotent; if a
    // contradictory event somehow arrives for an existing seq, keep the first
    // committed projection rather than mutating already-rendered history.
    if (!bySeq.has(event.seq)) bySeq.set(event.seq, event)
  }
  return [...bySeq.values()]
    .sort((left, right) => left.seq - right.seq)
    .slice(-MAX_BUFFERED_EVENTS)
}

export function eventStreamFromResume(resume: SessionResume): SessionEventStreamState | null {
  const sessionId = resume.active_session?.id
  const runtime = resume.table_runtime ?? null
  if (!sessionId || !runtime || runtime.session_id !== sessionId) return null

  const initialPage = resume.recent_events ?? null
  const matchingRecentPage = initialPage?.session_id === sessionId ? initialPage : null
  const resumeHistoryIsComplete = matchingRecentPage !== null
    && matchingRecentPage.after_seq === 0
    && matchingRecentPage.has_more === false
    && matchingRecentPage.cursor >= runtime.last_event_seq

  return {
    sessionId,
    // Resume paints a bounded recent projection immediately. We may continue
    // directly from its cursor only when that projection proves it covered the
    // durable history from seq 0 through the current runtime head. Otherwise a
    // fresh browser must replay from zero so older caller-visible events cannot
    // disappear merely because private/raw traffic pushed them outside the
    // bounded Resume window. The reducer remains idempotent, so recent events
    // already painted by Resume are harmlessly de-duplicated during backfill.
    cursor: resumeHistoryIsComplete ? matchingRecentPage.cursor : 0,
    currentSeq: Math.max(runtime.last_event_seq, matchingRecentPage?.current_seq ?? 0),
    events: matchingRecentPage ? mergeEvents([], matchingRecentPage.events) : [],
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
    events: mergeEvents(state.events, page.events),
  }
}

export { MAX_BUFFERED_EVENTS }
