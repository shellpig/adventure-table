import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { TacticalSetupPanel } from './TacticalSetupPanel'
import { sessionCopy } from './sessionCopy'

vi.mock('../../api/battleMaps', () => ({
  createBattleMap: vi.fn(),
  getBattleMap: vi.fn(),
  listBattleMaps: vi.fn().mockResolvedValue([]),
}))

vi.mock('../../api/tacticalCombat', () => ({
  startTacticalCombat: vi.fn(),
}))

const defaultProps = {
  roomId: 'room-1',
  campaignId: 'camp-1',
  sessionId: 'sess-1',
  token: 'test-token',
  onError: vi.fn(),
  refresh: vi.fn(),
  onClose: vi.fn(),
}

describe('TacticalSetupPanel', () => {
  it('provides accessible aria-label on the close button', () => {
    for (const locale of ['zh-TW', 'en'] as const) {
      const copy = sessionCopy(locale)
      const html = renderToStaticMarkup(
        <TacticalSetupPanel
          {...defaultProps}
          copy={copy}
          locale={locale}
        />,
      )

      expect(html).toContain(`aria-label="${copy.close}"`)
    }
  })
})
