import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const joinKitCopyFragments = [
  'ChatGPT Web:',
  'MCP client:',
  'Raw HTTP:',
  'Copy Join Kit',
  'Download .txt',
  '複製 Join Kit',
  '下載 .txt',
]

describe('M04-C Join Kit copy ownership', () => {
  it('keeps integration copy in the shared AIJoinKit instead of the Lobby or Session panels', () => {
    const shared = readFileSync(new URL('./AIJoinKit.tsx', import.meta.url), 'utf8')
    const lobby = readFileSync(new URL('./LobbyAIDMGrantPanel.tsx', import.meta.url), 'utf8')
    const player = readFileSync(new URL('./PlayerAIControlPanel.tsx', import.meta.url), 'utf8')

    expect(lobby).toContain('<AIJoinKit')
    expect(player).toContain('<AIJoinKit')

    for (const fragment of joinKitCopyFragments) {
      expect(shared).toContain(fragment)
      expect(lobby).not.toContain(fragment)
      expect(player).not.toContain(fragment)
    }
  })
})
