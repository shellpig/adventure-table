import { describe, expect, it } from 'vitest'

import { checkIntentDisposition } from './sessionCheckIntent'

const MIRA_SEAT = '40000000-0000-4000-8000-000000000002'
const intent = {
  type: 'check_intent' as const,
  text: 'inspect the rune',
  subject_seat_id: MIRA_SEAT,
}

describe('/check ownership disposition', () => {
  it('turns a Player /check into PendingAction intent without a RollRequest', () => {
    expect(checkIntentDisposition(false, intent)).toEqual({
      type: 'player_pending_action',
      input: {
        subject_seat_id: MIRA_SEAT,
        text: 'inspect the rune',
        intent_payload: {
          kind: 'check',
          source_command: 'check',
        },
      },
    })
  })

  it('hands a DM /check to Request Check UX without submitting a roll', () => {
    expect(checkIntentDisposition(true, intent)).toEqual({
      type: 'dm_request_check',
      draft: intent,
    })
  })
})
