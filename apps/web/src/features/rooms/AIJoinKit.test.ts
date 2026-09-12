import { describe, expect, it } from 'vitest'

import { aiJoinKitFilename, buildAIJoinKit, isLoopbackOrigin } from './AIJoinKit'

describe('M04-C AI Join Kit', () => {
  it('builds a complete English DM kit from the browser origin', () => {
    const kit = buildAIJoinKit({
      origin: 'https://table.example.test/',
      token: 'at_ai_example_secret',
      role: 'dm',
      locale: 'en',
      expiresAt: '2026-09-12T10:00:00Z',
    })

    expect(kit).toContain('Role: dm')
    expect(kit).toContain('MCP URL: https://table.example.test/mcp')
    expect(kit).toContain('Guide: https://table.example.test/mcp/guide?locale=en')
    expect(kit).toContain('AI Join Token: at_ai_example_secret')
    expect(kit).toContain('Expires: 2026-09-12T10:00:00Z')
    expect(kit).toContain('First step: after connecting, call get_session_context.')
    expect(kit).toContain('do not forward it')
    expect(kit).toContain('revoke it when finished')
    expect(kit).toContain('Refresh/rescan the connector')
    expect(kit).toContain('ChatGPT Web: add the Adventure Table connector')
    expect(kit).toContain('MCP client: connect')
    expect(kit).toContain('Raw HTTP: only for an AI with shell or outbound-network code execution')
  })

  it('builds a Traditional Chinese Player kit and warns for loopback', () => {
    const kit = buildAIJoinKit({
      origin: 'http://127.0.0.1:8000',
      token: 'at_ai_player_secret',
      role: 'player',
      locale: 'zh-TW',
    })

    expect(kit).toContain('Role: player')
    expect(kit).toContain('http://127.0.0.1:8000/mcp')
    expect(kit).toContain('/mcp/guide?locale=zh-TW')
    expect(kit).toContain('Expires: session/grant lifetime')
    expect(kit).toContain('第一步：連線後先呼叫 get_session_context')
    expect(kit).toContain('不要轉傳')
    expect(kit).toContain('Refresh／重新掃描 connector')
    expect(kit).toContain('ChatGPT Web')
    expect(kit).toContain('OAuth 要求憑證時貼上此 token')
    expect(kit).toContain('loopback')
    expect(isLoopbackOrigin('http://localhost:5173')).toBe(true)
    expect(isLoopbackOrigin('http://[::1]:5173')).toBe(true)
    expect(isLoopbackOrigin('https://table.example.test')).toBe(false)
  })

  it('uses contract filename and does not leak the token', () => {
    const filename = aiJoinKitFilename('player', new Date('2026-09-12T03:04:05Z'))

    expect(filename).toBe('adventure-table-ai-player-20260912.txt')
    expect(filename).not.toContain('token')
    expect(filename).not.toContain('secret')
  })
})
