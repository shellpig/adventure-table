import { describe, expect, it } from 'vitest'

import { aiJoinKitFilename, buildAIJoinKit } from './AIJoinKit'

describe('M04-C AI Join Kit', () => {
  it('builds a complete English DM kit with local and remote URLs', () => {
    const kit = buildAIJoinKit({
      origin: 'http://127.0.0.1:5173/',
      remoteOrigin: 'https://table.example.ts.net/',
      token: 'at_ai_example_secret',
      role: 'dm',
      locale: 'en',
      expiresAt: '2026-09-12T10:00:00Z',
    })

    expect(kit).toContain('Adventure Table — AI Join Kit')
    expect(kit).toContain('Role: DM')
    expect(kit).toContain('URL (local): http://127.0.0.1:5173/mcp')
    expect(kit).toContain('URL (remote): https://table.example.ts.net/mcp')
    expect(kit).toContain('Guide (local): http://127.0.0.1:5173/mcp/guide?locale=en')
    expect(kit).toContain('Guide (remote): https://table.example.ts.net/mcp/guide?locale=en')
    expect(kit).toContain('Token: at_ai_example_secret')
    expect(kit).toContain('Expires: 2026-09-12T10:00:00Z')
    expect(kit).toContain('you are already connected over MCP')
    expect(kit).toContain('actually CALL the get_session_context tool')
    expect(kit).toContain('Connection setup (for the operator')
    expect(kit).toContain('uses the local URL; web chat and any AI outside this machine use the remote URL')
    expect(kit).toContain('do not forward it')
    expect(kit).toContain('revoke it when finished')
    expect(kit).toContain('Refresh/rescan the connector')
    expect(kit).toContain('ChatGPT Web: the user adds the Adventure Table connector')
    expect(kit).toContain('Authorization: Bearer at_ai_example_secret')
    expect(kit).toContain('shell / outbound-network code execution')
    expect(kit).not.toContain('No public entry point')
  })

  it('builds a Traditional Chinese Player kit and explains the missing remote URL', () => {
    const kit = buildAIJoinKit({
      origin: 'http://127.0.0.1:8000',
      remoteOrigin: null,
      token: 'at_ai_player_secret',
      role: 'player',
      locale: 'zh-TW',
    })

    expect(kit).toContain('Role: Player')
    expect(kit).toContain('URL（本機）: http://127.0.0.1:8000/mcp')
    expect(kit).toContain('Guide（本機）: http://127.0.0.1:8000/mcp/guide?locale=zh-TW')
    expect(kit).not.toContain('URL（公網）')
    expect(kit).not.toContain('Guide（公網）')
    expect(kit).toContain('尚未設定公網入口（ADVENTURE_TABLE_MCP_PUBLIC_ORIGIN）')
    expect(kit).toContain('Expires: 直到 Session 結束或被撤銷')
    expect(kit).toContain('你已透過 MCP 連上這張桌')
    expect(kit).toContain('實際呼叫」get_session_context')
    expect(kit).toContain('接入設定（給架設者')
    expect(kit).toContain('在這台機器上跑的 AI 用「本機」URL')
    expect(kit).toContain('勿轉傳')
    expect(kit).toContain('Refresh／重新掃描 connector')
    expect(kit).toContain('ChatGPT Web：由使用者在 ChatGPT 新增 Adventure Table connector')
    expect(kit).toContain('OAuth 頁貼上此 token')
  })

  it('renders both locales with the same line structure', () => {
    const input = {
      origin: 'http://127.0.0.1:5173',
      remoteOrigin: 'https://table.example.ts.net',
      token: 'at_ai_parity',
      role: 'dm' as const,
      expiresAt: null,
    }
    const en = buildAIJoinKit({ ...input, locale: 'en' }).split('\n')
    const zh = buildAIJoinKit({ ...input, locale: 'zh-TW' }).split('\n')

    expect(zh).toHaveLength(en.length)
    for (const line of [
      'https://table.example.ts.net/mcp',
      'http://127.0.0.1:5173/mcp',
      'Token: at_ai_parity',
      'Role: DM',
      'Bearer at_ai_parity',
    ]) {
      expect(en.some((item) => item.includes(line))).toBe(true)
      expect(zh.some((item) => item.includes(line))).toBe(true)
    }
  })

  it('uses contract filename and does not leak the token', () => {
    const filename = aiJoinKitFilename('player', new Date('2026-09-12T03:04:05Z'))

    expect(filename).toBe('adventure-table-ai-player-20260912.txt')
    expect(filename).not.toContain('token')
    expect(filename).not.toContain('secret')
  })
})
