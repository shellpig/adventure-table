import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  getActiveCombatDetail,
  type CombatDetailView,
  type CombatEntryView,
  type CombatantDetailView,
} from '../../api/combat'
import type { TableEvent } from '../../api/sessions'

export function isCombatEvent(event: TableEvent): boolean {
  return event.kind.startsWith('combat.')
}

export function latestCombatEventSeq(events: TableEvent[]): number {
  let latest = 0
  for (const event of events) {
    if (isCombatEvent(event) && event.seq > latest) {
      latest = event.seq
    }
  }
  return latest
}

export function orderedEntries(
  detail: CombatDetailView | null | undefined,
): CombatEntryView[] {
  if (!detail?.entries) return []
  const withTurnOrder: CombatEntryView[] = []
  const withoutTurnOrder: CombatEntryView[] = []
  for (const entry of detail.entries) {
    if (typeof entry.turn_order === 'number') {
      withTurnOrder.push(entry)
    } else {
      withoutTurnOrder.push(entry)
    }
  }
  withTurnOrder.sort((a, b) => (a.turn_order ?? 0) - (b.turn_order ?? 0))
  return [...withTurnOrder, ...withoutTurnOrder]
}

export function myEntryIds(
  detail: CombatDetailView | null | undefined,
  ownCharacterIds: string[],
): string[] {
  if (!detail?.entries || ownCharacterIds.length === 0) return []
  const ownSet = new Set(ownCharacterIds)
  return detail.entries
    .filter((entry) => entry.character_id !== null && ownSet.has(entry.character_id))
    .map((entry) => entry.id)
}

export function combatantFor(
  detail: CombatDetailView | null | undefined,
  entryId: string,
): CombatantDetailView | undefined {
  return detail?.combatants?.find((c) => c.entry_id === entryId)
}

export type UseActiveCombatOptions = {
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  events: TableEvent[]
  onError?: (error: unknown) => void
}

export function useActiveCombat({
  roomId,
  campaignId,
  sessionId,
  token,
  events,
  onError,
}: UseActiveCombatOptions): {
  combat: CombatDetailView | null
  refresh: () => void
} {
  const [combat, setCombat] = useState<CombatDetailView | null>(null)
  const [refreshCounter, setRefreshCounter] = useState(0)
  const latestSeq = useMemo(() => latestCombatEventSeq(events), [events])
  const onErrorRef = useRef(onError)

  useEffect(() => {
    onErrorRef.current = onError
  }, [onError])

  const refresh = useCallback(() => {
    setRefreshCounter((prev) => prev + 1)
  }, [])

  useEffect(() => {
    let active = true

    const run = async () => {
      try {
        const detail = await getActiveCombatDetail(roomId, campaignId, sessionId, token)
        if (active) {
          setCombat(detail)
        }
      } catch (err) {
        if (active) {
          onErrorRef.current?.(err)
        }
      }
    }

    void run()

    return () => {
      active = false
    }
  }, [roomId, campaignId, sessionId, token, latestSeq, refreshCounter])

  return { combat, refresh }
}
