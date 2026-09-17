import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { listContent } from '../../api/character'
import {
  getActiveCombatDetail,
  listAdjudications,
  listPendingCombatRolls,
  type CombatAdjudicationView,
  type CombatDetailView,
  type CombatEntryView,
  type CombatPendingRollView,
  type CombatantDetailView,
} from '../../api/combat'
import type { TableEvent } from '../../api/sessions'
import type { SearchOption } from '../../components/SearchableSelect'
import { useContentPresentations } from '../../i18n/useContentPresentations'
import type { SessionCopy } from './sessionCopy'

const EMPTY_PENDING_COMBAT_ROLLS: CombatPendingRollView[] = []
const EMPTY_ADJUDICATIONS: CombatAdjudicationView[] = []

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

export function actingEntryId(
  combat: CombatDetailView,
  ownEntryIds: string[],
  isCurrentDm: boolean,
): string | null {
  if (combat.status !== 'running' || combat.current_turn_entry_id === null) return null
  if (isCurrentDm || ownEntryIds.includes(combat.current_turn_entry_id)) {
    return combat.current_turn_entry_id
  }
  return null
}

export function combatInjuryLabel(level: string, copy: SessionCopy): string {
  switch (level) {
    case 'healthy':
      return copy.combatInjuryHealthy
    case 'wounded':
      return copy.combatInjuryWounded
    case 'critical':
      return copy.combatInjuryCritical
    case 'down':
      return copy.combatInjuryDown
    default:
      return level
  }
}

export function adjudicationKindLabel(
  kind: CombatAdjudicationView['kind'],
  copy: SessionCopy,
): string {
  switch (kind) {
    case 'range':
      return copy.combatAdjudicationKindRange
    case 'reach':
      return copy.combatAdjudicationKindReach
    case 'affected_targets':
      return copy.combatAdjudicationKindAffectedTargets
    case 'opportunity_attack':
      return copy.combatAdjudicationKindOpportunityAttack
    case 'special':
      return copy.combatAdjudicationKindSpecial
  }
}

export async function runCombatMutation(
  setPending: (value: boolean) => void,
  mutation: () => Promise<void>,
  refresh: () => void,
  onError: (cause: unknown) => void,
): Promise<void> {
  setPending(true)
  try {
    await mutation()
    refresh()
  } catch (cause) {
    onError(cause)
  } finally {
    setPending(false)
  }
}

type CombatEventResourceOptions<T> = {
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  events: TableEvent[]
  onError?: (error: unknown) => void
  enabled: boolean
  load: (roomId: string, campaignId: string, sessionId: string, token: string) => Promise<T>
  initialValue: T
}

function useCombatEventResource<T>({
  roomId,
  campaignId,
  sessionId,
  token,
  events,
  onError,
  enabled,
  load,
  initialValue,
}: CombatEventResourceOptions<T>): { data: T; refresh: () => void } {
  const [data, setData] = useState<T>(initialValue)
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
    if (!enabled) {
      setData(initialValue)
      return
    }

    let active = true

    const run = async () => {
      try {
        const next = await load(roomId, campaignId, sessionId, token)
        if (active) {
          setData(next)
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
  }, [roomId, campaignId, sessionId, token, latestSeq, refreshCounter, enabled, load, initialValue])

  return { data, refresh }
}

export type UseActiveCombatOptions = {
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  events: TableEvent[]
  onError?: (error: unknown) => void
}

export function useActiveCombat(options: UseActiveCombatOptions): {
  combat: CombatDetailView | null
  refresh: () => void
} {
  const resource = useCombatEventResource({
    ...options,
    enabled: true,
    load: getActiveCombatDetail,
    initialValue: null,
  })
  return { combat: resource.data, refresh: resource.refresh }
}

export function usePendingCombatRolls(options: UseActiveCombatOptions): {
  rolls: CombatPendingRollView[]
  refresh: () => void
} {
  const resource = useCombatEventResource({
    ...options,
    enabled: true,
    load: listPendingCombatRolls,
    initialValue: EMPTY_PENDING_COMBAT_ROLLS,
  })
  return { rolls: resource.data, refresh: resource.refresh }
}

export type UsePendingAdjudicationsOptions = UseActiveCombatOptions & {
  enabled: boolean
}

export function usePendingAdjudications({
  enabled,
  ...options
}: UsePendingAdjudicationsOptions): {
  adjudications: CombatAdjudicationView[]
  refresh: () => void
} {
  const resource = useCombatEventResource({
    ...options,
    enabled,
    load: listAdjudications,
    initialValue: EMPTY_ADJUDICATIONS,
  })
  return { adjudications: resource.data, refresh: resource.refresh }
}

export function useMonsterOptions(enabled = true): SearchOption[] {
  const query = useQuery({
    queryKey: ['rules-content', 'monsters'],
    queryFn: () => listContent('monsters'),
    enabled,
  })

  const monsterKeys = useMemo(
    () => (query.data ?? []).map((entry) => entry.key),
    [query.data],
  )

  const { nameFor, searchAliasesFor } = useContentPresentations(
    monsterKeys,
    {},
    { includeSearchAliases: true },
  )

  return useMemo(
    () =>
      (query.data ?? []).map((entry) => {
        const cr = entry.data?.challenge_rating
        return {
          value: entry.key,
          label: nameFor(entry.key, entry.name),
          description: cr !== undefined && cr !== null ? `CR ${String(cr)}` : undefined,
          searchAliases: searchAliasesFor(entry.key, entry.name),
        }
      }),
    [query.data, nameFor, searchAliasesFor],
  )
}
