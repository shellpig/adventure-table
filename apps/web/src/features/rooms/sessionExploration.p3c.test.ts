import { describe, expect, it } from 'vitest'

import { parseExplorationComposer } from './sessionExploration'


const MIRA_SEAT = '40000000-0000-4000-8000-000000000002'


describe('/check composer ownership handoff', () => {
  it('parses /check into typed intent instead of a normal Exploration request', () => {
    expect(parseExplorationComposer('/check search the old door', 'dialogue', MIRA_SEAT)).toEqual({
      type: 'check_intent',
      text: 'search the old door',
      subject_seat_id: MIRA_SEAT,
    })
  })

  it('requires both a subject and meaningful check intent text', () => {
    expect(parseExplorationComposer('/check inspect the rune', 'dialogue', null)).toEqual({
      type: 'invalid',
      reason: 'missing_subject',
    })
    expect(parseExplorationComposer('/check   ', 'dialogue', MIRA_SEAT)).toEqual({
      type: 'invalid',
      reason: 'empty',
    })
  })

  it('keeps /search as a normal action shortcut rather than a formal check', () => {
    expect(parseExplorationComposer('/search the desk', 'dialogue', MIRA_SEAT)).toEqual({
      type: 'request',
      request: {
        kind: 'action',
        text: 'the desk',
        subject_seat_id: MIRA_SEAT,
        source_command: 'search',
      },
    })
  })
})
