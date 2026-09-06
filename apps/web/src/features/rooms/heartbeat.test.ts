import { describe, expect, it, vi } from 'vitest'

import {
  ROOM_HEARTBEAT_INTERVAL_MS,
  startRoomHeartbeat,
  type IntervalScheduler,
} from './heartbeat'

describe('P2-A Room heartbeat lifecycle', () => {
  it('starts immediately, repeats every 30 seconds, and stops on cleanup', () => {
    const callbacks = new Map<number, () => void>()
    let nextHandle = 1
    const scheduler: IntervalScheduler = {
      setInterval: (callback, delay) => {
        expect(delay).toBe(ROOM_HEARTBEAT_INTERVAL_MS)
        const numericHandle = nextHandle++
        callbacks.set(numericHandle, callback)
        return numericHandle as unknown as ReturnType<typeof setInterval>
      },
      clearInterval: (handle) => {
        callbacks.delete(Number(handle))
      },
    }
    const heartbeat = vi.fn()

    const stop = startRoomHeartbeat(heartbeat, scheduler)
    expect(heartbeat).toHaveBeenCalledTimes(1)
    expect(callbacks.size).toBe(1)

    callbacks.values().next().value?.()
    expect(heartbeat).toHaveBeenCalledTimes(2)

    stop()
    expect(callbacks.size).toBe(0)
  })
})
