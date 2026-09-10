import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import type { CampaignSeat } from '../../api/seats'
import { PlayerAIControlPanel } from './PlayerAIControlPanel'
import { sessionCopy } from './sessionCopy'

const seat: CampaignSeat = {
  id: '40000000-0000-4000-8000-000000000001',
  campaign_id: '20000000-0000-4000-8000-000000000001',
  role: 'player',
  label: 'Mira',
  controller_kind: 'human',
  controller_access_session_id: '50000000-0000-4000-8000-000000000001',
  controller_display_name: 'Player',
  controller_authority: 'member',
  presence: 'connected',
  selected_character_id: '60000000-0000-4000-8000-000000000001',
  archived_at: null,
  created_at: '2026-09-10T00:00:00Z',
  updated_at: '2026-09-10T00:00:00Z',
}

function render(inputSeat: CampaignSeat, canSelfTakeBack: boolean) {
  return renderToStaticMarkup(createElement(PlayerAIControlPanel, {
    roomId: '10000000-0000-4000-8000-000000000001',
    campaignId: inputSeat.campaign_id,
    sessionId: '30000000-0000-4000-8000-000000000001',
    seat: inputSeat,
    roomToken: 'room-token',
    callerAccessSessionId: seat.controller_access_session_id,
    canSelfTakeBack,
    canManage: false,
    controllers: [],
    copy: sessionCopy('en'),
    onChanged: async () => undefined,
  }))
}

describe('Player AI control panel', () => {
  it('renders self handoff copy in both locales', () => {
    for (const locale of ['zh-TW', 'en'] as const) {
      const copy = sessionCopy(locale)
      const html = renderToStaticMarkup(createElement(PlayerAIControlPanel, {
        roomId: '10000000-0000-4000-8000-000000000001',
        campaignId: seat.campaign_id,
        sessionId: '30000000-0000-4000-8000-000000000001',
        seat,
        roomToken: 'room-token',
        callerAccessSessionId: seat.controller_access_session_id,
        canSelfTakeBack: false,
        canManage: false,
        controllers: [],
        copy,
        onChanged: async () => undefined,
      }))
      expect(html).toContain(copy.letAiControl)
      expect(html).toContain(copy.aiHandoffInstruction)
    }
  })

  it('shows self-service Take Back only for the server-derived exact origin scope', () => {
    const aiSeat = { ...seat, controller_kind: 'ai' as const, controller_access_session_id: null }
    const exact = render(aiSeat, true)
    expect(exact).toContain(sessionCopy('en').takeBackControl)
    expect(exact).toContain(sessionCopy('en').takeBackExactOriginHint)

    const otherSession = render(aiSeat, false)
    expect(otherSession).not.toContain(`>${sessionCopy('en').takeBackControl}<`)
    expect(otherSession).toContain(sessionCopy('en').aiTakeBackFailedRecovery)
  })

  it('keeps one-time controller tokens out of browser storage', () => {
    const source = readFileSync(new URL('./PlayerAIControlPanel.tsx', import.meta.url), 'utf8')
    expect(source).toContain('setIssued(next)')
    expect(source).toContain('navigator.clipboard.writeText(issued.token)')
    expect(source).toContain('data-ai-token-once="true"')
    expect(source).not.toContain('localStorage')
    expect(source).not.toContain('sessionStorage')
    expect(source).not.toContain('setItem(')
  })

  it('uses exact Take Back and explicit administrative recovery', () => {
    const source = readFileSync(new URL('./PlayerAIControlPanel.tsx', import.meta.url), 'utf8')
    expect(source).toContain('takeBackPlayer(roomId, campaignId, sessionId, seat.id, roomToken)')
    expect(source).toContain('administrativelyReassignPlayer(')
    expect(source).toContain('canSelfTakeBack ? copy.takeBackExactOriginHint')
    expect(source).toContain('copy.aiRecoveryHint')
  })
})
