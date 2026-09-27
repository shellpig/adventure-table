import { useCallback, useRef, useState } from 'react'

import {
  confirmMovement,
  previewMovement,
  type ConfirmMovementView,
  type MovementAnchor,
  type PreviewMovementView,
} from '../../api/tacticalCombat'

export type MovementDraftState = {
  /** Client-only draft anchors (first = current position). */
  anchors: MovementAnchor[]
  /** Latest server preview for the draft path. */
  preview: PreviewMovementView | null
  /** Whether a preview/confirm request is in flight. */
  busy: boolean
  /** Whether the draft was started by a drag (vs click-to-add). */
  isDragging: boolean
}

const INITIAL: MovementDraftState = {
  anchors: [],
  preview: null,
  busy: false,
  isDragging: false,
}

type UseMovementDraftOptions = {
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  onError: (cause: unknown) => void
}

/**
 * Client-only movement draft: the path is accumulated locally and only
 * previewed (never committed) until the user hits Confirm. The server is the
 * authority on legality / used / remaining feet; the client never computes
 * movement cost itself.
 */
export function useMovementDraft(options: UseMovementDraftOptions) {
  const { roomId, campaignId, sessionId, token, onError } = options
  const [state, setState] = useState<MovementDraftState>(INITIAL)
  const stateRef = useRef(state)
  stateRef.current = state
  const entryIdRef = useRef<string | null>(null)
  const dragEntryIdRef = useRef<string | null>(null)
  const previewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const runPreview = useCallback(
    async (entryId: string, anchors: MovementAnchor[], dragEntryId: string | null) => {
      if (anchors.length < 2) {
        setState((s) => ({ ...s, preview: null }))
        return
      }
      setState((s) => ({ ...s, busy: true }))
      try {
        const view = await previewMovement(
          roomId,
          campaignId,
          sessionId,
          { entry_id: entryId, path: anchors, drag_entry_id: dragEntryId },
          token,
        )
        // Only apply if the draft hasn't moved on.
        if (entryIdRef.current === entryId) {
          setState((s) => ({ ...s, preview: view, busy: false }))
        }
      } catch (cause) {
        setState((s) => ({ ...s, busy: false }))
        onError(cause)
      }
    },
    [roomId, campaignId, sessionId, token, onError],
  )

  const schedulePreview = useCallback(
    (entryId: string, anchors: MovementAnchor[], dragEntryId: string | null) => {
      if (previewTimerRef.current) clearTimeout(previewTimerRef.current)
      previewTimerRef.current = setTimeout(() => {
        void runPreview(entryId, anchors, dragEntryId)
      }, 150)
    },
    [runPreview],
  )

  /** Start a new draft from the token's current position. */
  const startDraft = useCallback(
    (entryId: string, startX: number, startY: number, dragEntryId: string | null, isDragging: boolean) => {
      entryIdRef.current = entryId
      dragEntryIdRef.current = dragEntryId
      const anchors = [{ x: startX, y: startY }]
      setState({ anchors, preview: null, busy: false, isDragging })
    },
    [],
  )

  /** Append an anchor (dedup consecutive duplicates). */
  const addAnchor = useCallback(
    (x: number, y: number) => {
      const entryId = entryIdRef.current
      if (!entryId) return
      setState((s) => {
        const last = s.anchors[s.anchors.length - 1]
        if (last && last.x === x && last.y === y) return s
        const anchors = [...s.anchors, { x, y }]
        schedulePreview(entryId, anchors, dragEntryIdRef.current)
        return { ...s, anchors }
      })
    },
    [schedulePreview],
  )

  const clearDraft = useCallback(() => {
    entryIdRef.current = null
    dragEntryIdRef.current = null
    if (previewTimerRef.current) clearTimeout(previewTimerRef.current)
    setState(INITIAL)
  }, [])

  /** Confirm the draft path with the server. Returns the outcome view. */
  const confirmDraft = useCallback(
    async (expectedPositionRevision: number, expectedBoardRevision: number, idempotencyKey: string): Promise<ConfirmMovementView | null> => {
      const entryId = entryIdRef.current
      const { anchors, preview } = stateRef.current
      if (!entryId || anchors.length < 2 || !preview) return null
      setState((s) => ({ ...s, busy: true }))
      try {
        const view = await confirmMovement(
          roomId,
          campaignId,
          sessionId,
          {
            entry_id: entryId,
            path: anchors,
            expected_position_revision: expectedPositionRevision,
            expected_board_revision: expectedBoardRevision,
            idempotency_key: idempotencyKey,
            drag_entry_id: dragEntryIdRef.current,
          },
          token,
        )
        clearDraft()
        return view
      } catch (cause) {
        setState((s) => ({ ...s, busy: false }))
        onError(cause)
        return null
      }
    },
    [roomId, campaignId, sessionId, token, onError, clearDraft],
  )

  return {
    draft: state,
    draftEntryId: entryIdRef.current,
    startDraft,
    addAnchor,
    clearDraft,
    confirmDraft,
  }
}
