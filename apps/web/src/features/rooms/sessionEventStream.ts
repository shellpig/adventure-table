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
  const cursor = initialPage?.session_id === sessionId
    ? initialPage.cursor
    : runtime.last_event_seq
  return {
    sessionId,
    cursor,
    currentSeq: Math.max(runtime.last_event_seq, initialPage?.current_seq ?? 0),
    events: initialPage?.session_id === sessionId ? mergeEvents([], initialPage.events) : [],
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
