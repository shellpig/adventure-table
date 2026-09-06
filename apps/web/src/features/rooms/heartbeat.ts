export const ROOM_HEARTBEAT_INTERVAL_MS = 30_000

export type IntervalScheduler = {
  setInterval: (callback: () => void, delay: number) => ReturnType<typeof setInterval>
  clearInterval: (handle: ReturnType<typeof setInterval>) => void
}

const browserScheduler: IntervalScheduler = {
  setInterval: (callback, delay) => setInterval(callback, delay),
  clearInterval: (handle) => clearInterval(handle),
}

export function startRoomHeartbeat(
  heartbeat: () => void | Promise<void>,
  scheduler: IntervalScheduler = browserScheduler,
): () => void {
  void heartbeat()
  const handle = scheduler.setInterval(() => {
    void heartbeat()
  }, ROOM_HEARTBEAT_INTERVAL_MS)
  return () => scheduler.clearInterval(handle)
}
