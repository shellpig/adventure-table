import { describe, expect, it } from 'vitest'

import type { StageState, TableEvent } from '../../api/sessions'
import { applyStageEvent, parseExplorationComposer } from './sessionExploration'

const SUBJECT = '40000000-0000-4000-8000-000000000001'

function stageEvent(revision: number, text: string | null): TableEvent {
  return {
    id: `50000000-0000-4000-8000-00000000000${revision}`,
    session_id: '30000000-0000-4000-8000-000000000001',
    seq: revision,
    kind: 'stage.updated',
    acting_seat_id: null,
    subject_seat_id: null,
    subject_character_id: null,
    execution_mode: 'self',
    visibility: 'public',
    recipient_seat_ids: [],
    payload_version: 1,
    payload: {
      stage_revision: revision,
      text,
      image_id: null,
      image_media_type: null,
      image_filename: null,
    },
    created_at: '2026-09-09T00:00:00Z',
  }
}

describe('P3-B exploration composer', () => {
  it('maps slash commands into the same typed input contract', () => {
    expect(parseExplorationComposer('/action open the door', 'dialogue', SUBJECT)).toMatchObject({
      type: 'request',
      request: { kind: 'action', text: 'open the door', subject_seat_id: SUBJECT },
    })
    expect(parseExplorationComposer('/search the desk', 'dialogue', SUBJECT)).toEqual({
      type: 'request',
      request: {
        kind: 'action',
        text: 'the desk',
        subject_seat_id: SUBJECT,
        source_command: 'search',
      },
    })
    expect(parseExplorationComposer('/whisper secret', 'dialogue', SUBJECT)).toMatchObject({
      type: 'request', request: { kind: 'whisper_dm', subject_seat_id: null },
    })
    expect(parseExplorationComposer('/ooc snack break', 'dialogue', SUBJECT)).toMatchObject({
      type: 'request', request: { kind: 'ooc', subject_seat_id: null },
    })
  })

  it('blocks check ownership and never manufactures a roll request', () => {
    expect(parseExplorationComposer('/check perception', 'action', SUBJECT)).toEqual({
      type: 'blocked_check',
    })
    expect(JSON.stringify(parseExplorationComposer('/search room', 'action', SUBJECT))).not.toContain('roll')
  })

  it('requires an explicit subject for character dialogue/action', () => {
    expect(parseExplorationComposer('Hello', 'dialogue', null)).toEqual({
      type: 'invalid', reason: 'missing_subject',
    })
    expect(parseExplorationComposer('table talk', 'ooc', null)).toMatchObject({
      type: 'request', request: { kind: 'ooc' },
    })
  })
})

describe('P3-B Stage event projection', () => {
  it('applies newer canonical Stage events and ignores stale ones', () => {
    const initial: StageState = {
      session_id: '30000000-0000-4000-8000-000000000001',
      revision: 2,
      text: 'Gate',
      image_id: null,
      image_media_type: null,
      image_filename: null,
    }
    const updated = applyStageEvent(initial, stageEvent(3, 'Bridge'))
    expect(updated?.revision).toBe(3)
    expect(updated?.text).toBe('Bridge')
    expect(applyStageEvent(updated, stageEvent(1, 'Old'))).toEqual(updated)
  })
})
