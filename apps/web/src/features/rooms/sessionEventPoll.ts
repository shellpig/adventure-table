import { SessionApiError, type TableEventPage } from '../../api/sessions'

export const SESSION_EVENT_RETRY_INITIAL_MS = 1_000
export const SESSION_EVENT_RETRY_MAX_MS = 30_000

export type SessionEventConnectionStatus = 'connected' | 'reconnecting' | 'fatal'

type SessionEventPollOptions = {
  initialCursor: number
  signal: AbortSignal
  wait: (cursor: number, signal: AbortSignal) => Promise<TableEventPage>
  onPage: (page: TableEventPage) => void
  onStatus: (status: SessionEventConnectionStatus) => void
  onFatal: (error: unknown) => void
  sleep?: (delayMs: number, signal: AbortSignal) => Promise<void>
}

function abortError(): Error {
  const error = new Error('Aborted')
  error.name = 'AbortError'
  return error
}

export function isAbortError(error: unknown): boolean {
  return (error as { name?: string } | null)?.name === 'AbortError'
}

export function isFatalSessionEventError(error: unknown): boolean {
  return error instanceof SessionApiError && (error.status === 403 || error.status === 404)
}

export function abortableDelay(delayMs: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(abortError())

  return new Promise((resolve, reject) => {
    const timer = globalThis.setTimeout(() => {
      signal.removeEventListener('abort', handleAbort)
      resolve()
    }, delayMs)
    const handleAbort = () => {
      globalThis.clearTimeout(timer)
      signal.removeEventListener('abort', handleAbort)
      reject(abortError())
    }
    signal.addEventListener('abort', handleAbort, { once: true })
  })
}

export async function runSessionEventPoll({
  initialCursor,
  signal,
  wait,
  onPage,
  onStatus,
  onFatal,
  sleep = abortableDelay,
}: SessionEventPollOptions): Promise<void> {
  let cursor = initialCursor
  let retryDelayMs = SESSION_EVENT_RETRY_INITIAL_MS

  while (!signal.aborted) {
    try {
      const page = await wait(cursor, signal)
      if (signal.aborted) return
      cursor = Math.max(cursor, page.cursor)
      retryDelayMs = SESSION_EVENT_RETRY_INITIAL_MS
      onStatus('connected')
      onPage(page)
    } catch (error) {
      if (signal.aborted || isAbortError(error)) return
      if (isFatalSessionEventError(error)) {
        onStatus('fatal')
        onFatal(error)
        return
      }

      onStatus('reconnecting')
      try {
        await sleep(retryDelayMs, signal)
      } catch (sleepError) {
        if (signal.aborted || isAbortError(sleepError)) return
        throw sleepError
      }
      retryDelayMs = Math.min(retryDelayMs * 2, SESSION_EVENT_RETRY_MAX_MS)
    }
  }
}
