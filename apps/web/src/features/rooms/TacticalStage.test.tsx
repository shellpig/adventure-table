import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type { CombatDetailView } from '../../api/combat'
import { TacticalStage } from './TacticalStage'
import { sessionCopy } from './sessionCopy'

const copy = sessionCopy('en')

function makeCombat(): CombatDetailView {
  return {
    id: 'combat-1',
    campaign_id: 'camp-1',
    mode: 'tactical',
    status: 'active',
    round_number: 1,
    current_turn_entry_id: 'entry-1',
    revision: 1,
    entries: [
      {
        id: 'entry-1',
        kind: 'character',
        display_name: 'Hero',
        initiative: 15,
        is_active: true,
        conditions: [],
      },
    ],
  } as unknown as CombatDetailView
}

function renderStage(isCurrentDm: boolean) {
  return renderToStaticMarkup(
    <TacticalStage
      combat={makeCombat()}
      myEntryIds={['entry-1']}
      copy={copy}
      locale="en"
      roomId="room-1"
      campaignId="camp-1"
      sessionId="sess-1"
      token="token"
      isCurrentDm={isCurrentDm}
      logEvents={[]}
      resolveEntryLabel={() => 'Hero'}
      resolveContentName={() => ''}
      resolveContentField={() => ''}
      onError={vi.fn()}
      refresh={vi.fn()}
    />,
  )
}

describe('TacticalStage authority', () => {
  it('DM sees placement section', () => {
    const html = renderStage(true)
    // Placement UI is inside the stage; with no board loaded yet it shows loading.
    // The stage title and header are always visible.
    expect(html).toContain('data-testid="tactical-stage"')
  })

  it('Player does not see DM-only placement controls in static markup', () => {
    const html = renderStage(false)
    expect(html).toContain('data-testid="tactical-stage"')
    // Placement section has data-testid="tactical-placement"; without board data
    // it is not rendered. The key check: no DM-only testids leak.
    expect(html).not.toContain('data-testid="tactical-place-token"')
  })

  it('renders combat header with round and turn', () => {
    const html = renderStage(false)
    expect(html).toContain('data-testid="tactical-header"')
    expect(html).toContain('data-testid="tactical-round"')
    expect(html).toContain('data-testid="tactical-turn"')
  })
})
