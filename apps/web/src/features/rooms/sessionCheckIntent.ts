import type { PendingActionCreateInput } from '../../api/p3c'
import type { ComposerParseResult } from './sessionExploration'

export type CheckIntent = Extract<ComposerParseResult, { type: 'check_intent' }>

export type CheckIntentDisposition =
  | { type: 'player_pending_action'; input: PendingActionCreateInput }
  | { type: 'dm_request_check'; draft: CheckIntent }

export function checkIntentDisposition(
  isCurrentDm: boolean,
  intent: CheckIntent,
): CheckIntentDisposition {
  if (isCurrentDm) {
    return { type: 'dm_request_check', draft: intent }
  }
  return {
    type: 'player_pending_action',
    input: {
      subject_seat_id: intent.subject_seat_id,
      text: intent.text,
      intent_payload: {
        kind: 'check',
        source_command: 'check',
      },
    },
  }
}
