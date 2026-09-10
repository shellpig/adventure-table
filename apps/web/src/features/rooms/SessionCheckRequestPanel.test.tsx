import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { sessionCopy } from './sessionCopy'
import {
  buildRequestCheckInput,
  SessionCheckRequestPanel,
} from './SessionCheckRequestPanel'

const MIRA = '40000000-0000-4000-8000-000000000001'
const SERENA = '40000000-0000-4000-8000-000000000002'

describe('DM Request Check form', () => {
  it('builds a multi-target canonical skill request without inventing a roll', () => {
    expect(buildRequestCheckInput({
      targetSeatIds: [MIRA, SERENA],
      requestType: 'skill',
      abilityRef: '',
      skillRef: 'srd5.1:skill:perception',
      dc: '15',
      modifierMode: 'advantage',
      flatAdjustment: '-1',
      visibility: 'roller_and_dm',
      label: 'listen at the door',
    })).toEqual({
      target_seat_ids: [MIRA, SERENA],
      request_type: 'skill',
      ability_ref: null,
      skill_ref: 'srd5.1:skill:perception',
      dc: 15,
      modifier_mode: 'advantage',
      flat_adjustment: -1,
      visibility: 'roller_and_dm',
      label: 'listen at the door',
    })
  })

  it('refuses incomplete ability/skill request drafts', () => {
    expect(buildRequestCheckInput({
      targetSeatIds: [MIRA],
      requestType: 'ability',
      abilityRef: '',
      skillRef: '',
      dc: '',
      modifierMode: 'normal',
      flatAdjustment: '0',
      visibility: 'public',
      label: '',
    })).toBeNull()
    expect(buildRequestCheckInput({
      targetSeatIds: [],
      requestType: 'other',
      abilityRef: '',
      skillRef: '',
      dc: '',
      modifierMode: 'normal',
      flatAdjustment: '0',
      visibility: 'public',
      label: '',
    })).toBeNull()
  })

  it('renders the /check intent and target choices in both locales', () => {
    for (const locale of ['zh-TW', 'en'] as const) {
      const copy = sessionCopy(locale)
      const html = renderToStaticMarkup(createElement(SessionCheckRequestPanel, {
        roomId: 'room',
        campaignId: 'campaign',
        sessionId: 'session',
        token: 'token',
        targets: [
          { seatId: MIRA, label: 'Mira' },
          { seatId: SERENA, label: 'Serena' },
        ],
        intent: {
          type: 'check_intent',
          text: 'inspect the rune',
          subject_seat_id: MIRA,
        },
        copy,
        onError: () => undefined,
      }))
      expect(html).toContain(copy.checkRequestTitle)
      expect(html).toContain('inspect the rune')
      expect(html).toContain('Mira')
      expect(html).toContain('Serena')
      expect(html).toContain(copy.checkSubmit)
    }
  })
})
