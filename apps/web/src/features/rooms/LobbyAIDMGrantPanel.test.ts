import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import type { CampaignSeat } from '../../api/seats'
import { LobbyAIDMGrantPanel } from './LobbyAIDMGrantPanel'
import { lobbyCopy } from './lobbyCopy'

const seat: CampaignSeat = {
  id: '40000000-0000-4000-8000-000000000001',
  campaign_id: '20000000-0000-4000-8000-000000000001',
  role: 'dm',
  label: 'DM',
  controller_kind: 'none',
  controller_access_session_id: null,
  controller_display_name: null,
  controller_authority: null,
  presence: 'not_applicable',
  selected_character_id: null,
  archived_at: null,
  created_at: '2026-09-10T00:00:00Z',
  updated_at: '2026-09-10T00:00:00Z',
}

describe('Lobby AI DM grant panel', () => {
  it('explains finite pre-session scope in both locales', () => {
    for (const locale of ['zh-TW', 'en'] as const) {
      const copy = lobbyCopy(locale)
      const html = renderToStaticMarkup(createElement(LobbyAIDMGrantPanel, {
        roomId: '10000000-0000-4000-8000-000000000001',
        campaignId: seat.campaign_id,
        seat,
        roomToken: 'room-token',
        copy,
        onChanged: async () => undefined,
      }))
      expect(html).toContain(copy.aiDmTitle)
      expect(html).toContain(copy.aiDmFiniteHint)
      expect(html).toContain(copy.aiDmCreate)
    }
  })

  it('keeps plaintext tokens ephemeral and renders returned expiry', () => {
    const source = readFileSync(new URL('./LobbyAIDMGrantPanel.tsx', import.meta.url), 'utf8')
    expect(source).toContain('setIssued(next)')
    expect(source).toContain('navigator.clipboard.writeText(issued.token)')
    expect(source).toContain('data-ai-dm-token-once="true"')
    expect(source).toContain('issued.expires_at')
    expect(source).toContain('setExpired(true)')
    expect(source).not.toContain('localStorage')
    expect(source).not.toContain('sessionStorage')
    expect(source).not.toContain('setItem(')
  })

  it('builds the DM Join Kit from the issued token and current browser origin', () => {
    const source = readFileSync(new URL('./LobbyAIDMGrantPanel.tsx', import.meta.url), 'utf8')
    expect(source).toContain('<AIJoinKit')
    expect(source).toContain('origin={window.location.origin}')
    expect(source).toContain('token={issued.token}')
    expect(source).toContain('role="dm"')
    expect(source).toContain('locale={copy.locale}')
  })

  it('uses explicit rotate and revoke endpoints for configured AI DM seats', () => {
    const source = readFileSync(new URL('./LobbyAIDMGrantPanel.tsx', import.meta.url), 'utf8')
    expect(source).toContain('configurePreSessionAiDm(')
    expect(source).toContain('revokePreSessionAiDm(roomId, campaignId, seat.id, roomToken)')
    expect(source).toContain("const configured = seat.controller_kind === 'ai'")
  })
})
