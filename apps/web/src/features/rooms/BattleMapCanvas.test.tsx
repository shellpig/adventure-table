import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { BattleMapCanvas } from './BattleMapCanvas'

const camera = { x: 0, y: 0, zoom: 1 }

describe('BattleMapCanvas hidden rendering', () => {
  it('does not render hidden walls for Player (projection has no visibility)', () => {
    // Player projection: walls without visibility field (server omits it).
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        widthCells={10}
        heightCells={10}
        walls={[{ x1: 1, y1: 1, x2: 5, y2: 1 }]}
        doors={[]}
        terrain={[]}
        tokens={[]}
        camera={camera}
        isDm={false}
      />,
    )
    expect(html).toContain('data-testid="battle-map-wall"')
    expect(html).not.toContain('data-hidden="true"')
    expect(html).not.toContain('battle-map__wall--hidden')
  })

  it('marks hidden walls for DM when visibility is hidden', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        widthCells={10}
        heightCells={10}
        walls={[
          { x1: 1, y1: 1, x2: 5, y2: 1, visibility: 'hidden' },
          { x1: 2, y1: 2, x2: 6, y2: 2, visibility: 'public' },
        ]}
        doors={[]}
        terrain={[]}
        tokens={[]}
        camera={camera}
        isDm={true}
      />,
    )
    const hiddenCount = (html.match(/data-hidden="true"/g) || []).length
    expect(hiddenCount).toBe(1)
    expect(html).toContain('battle-map__wall--hidden')
  })

  it('does not mark public walls as hidden for DM', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        widthCells={10}
        heightCells={10}
        walls={[{ x1: 1, y1: 1, x2: 5, y2: 1, visibility: 'public' }]}
        doors={[]}
        terrain={[]}
        tokens={[]}
        camera={camera}
        isDm={true}
      />,
    )
    expect(html).not.toContain('data-hidden="true"')
  })

  it('marks hidden doors for DM via isHidden flag', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        widthCells={10}
        heightCells={10}
        walls={[]}
        doors={[
          {
            door_id: 'door-1',
            x1: 3,
            y1: 3,
            x2: 4,
            y2: 3,
            state: 'closed',
            revealed: false,
            isHidden: true,
          },
        ]}
        terrain={[]}
        tokens={[]}
        camera={camera}
        isDm={true}
      />,
    )
    expect(html).toContain('data-testid="battle-map-door"')
    expect(html).toContain('data-hidden="true"')
    expect(html).toContain('battle-map__door--hidden')
  })

  it('does not leak hidden door markers to Player view', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        widthCells={10}
        heightCells={10}
        walls={[]}
        doors={[
          {
            door_id: null,
            x1: 3,
            y1: 3,
            x2: 4,
            y2: 3,
            state: 'closed',
            revealed: false,
            isHidden: false,
          },
        ]}
        terrain={[]}
        tokens={[]}
        camera={camera}
        isDm={false}
      />,
    )
    expect(html).toContain('data-testid="battle-map-door"')
    expect(html).not.toContain('data-hidden="true"')
  })

  it('renders tokens with data-entry-id for selection', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        widthCells={10}
        heightCells={10}
        walls={[]}
        doors={[]}
        terrain={[]}
        tokens={[
          {
            entry_id: 'entry-1',
            name: 'Goblin',
            anchor_x: 2,
            anchor_y: 3,
            footprint_width: 1,
            footprint_height: 1,
          },
        ]}
        camera={camera}
        isDm={false}
        selectedEntryId="entry-1"
      />,
    )
    expect(html).toContain('data-testid="battle-map-token"')
    expect(html).toContain('data-entry-id="entry-1"')
    expect(html).toContain('data-selected="true"')
  })

  it('sets pointer-events: none on battle-map-tokens when tokensInteractive is false', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        widthCells={10}
        heightCells={10}
        walls={[]}
        doors={[]}
        terrain={[]}
        tokens={[
          {
            entry_id: 'entry-1',
            name: 'Goblin',
            anchor_x: 2,
            anchor_y: 3,
            footprint_width: 1,
            footprint_height: 1,
          },
        ]}
        camera={camera}
        isDm={false}
        tokensInteractive={false}
      />,
    )
    expect(html).toContain('data-testid="battle-map-tokens"')
    expect(html).toContain('pointer-events:none')
  })

  it('keeps pointer-events enabled on battle-map-tokens by default', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        widthCells={10}
        heightCells={10}
        walls={[]}
        doors={[]}
        terrain={[]}
        tokens={[
          {
            entry_id: 'entry-1',
            name: 'Goblin',
            anchor_x: 2,
            anchor_y: 3,
            footprint_width: 1,
            footprint_height: 1,
          },
        ]}
        camera={camera}
        isDm={false}
      />,
    )
    expect(html).toContain('data-testid="battle-map-tokens"')
    expect(html).not.toContain('pointer-events:none')
  })
})

