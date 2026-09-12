import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import { lobbyCopy } from './lobbyCopy'
import { sessionCopy } from './sessionCopy'

const uiCopyKeys = [
  'aiJoinKitTitle',
  'aiJoinKitHint',
  'aiJoinKitCopy',
  'aiJoinKitCopied',
  'aiJoinKitDownload',
] as const

describe('M04-C Join Kit copy ownership', () => {
  it('keeps Join Kit UI copy in Lobby and Session copy stores', () => {
    const shared = readFileSync(new URL('./AIJoinKit.tsx', import.meta.url), 'utf8')

    for (const locale of ['en', 'zh-TW'] as const) {
      const lobby = lobbyCopy(locale)
      const session = sessionCopy(locale)
      for (const key of uiCopyKeys) {
        expect(lobby[key]).toBeTruthy()
        expect(session[key]).toBeTruthy()
      }
    }

    expect(shared).not.toContain("title: 'AI Join Kit'")
    expect(shared).not.toContain("copy: 'Copy Join Kit'")
    expect(shared).not.toContain("copy: '複製 Join Kit'")
  })
})
