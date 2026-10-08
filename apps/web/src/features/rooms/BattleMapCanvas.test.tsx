import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { BattleMapCanvas } from './BattleMapCanvas'
import { doorStateLabel, sessionCopy } from './sessionCopy'

const camera = { x: 0, y: 0, zoom: 1 }

describe('BattleMapCanvas hidden rendering', () => {
  it('does not render hidden walls for Player (projection has no visibility)', () => {
    // Player projection: walls without visibility field (server omits it).
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        doorStateLabel={(state) => state}
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
        doorStateLabel={(state) => state}
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
        doorStateLabel={(state) => state}
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
        doorStateLabel={(state) => state}
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
        doorStateLabel={(state) => state}
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
        doorStateLabel={(state) => state}
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
        doorStateLabel={(state) => state}
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
        doorStateLabel={(state) => state}
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

  it('renders selected wall with battle-map__wall--selected class and data-selected attribute', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        doorStateLabel={(state) => state}
        widthCells={10}
        heightCells={10}
        walls={[{ id: 'w1', x1: 0, y1: 0, x2: 2, y2: 0, visibility: 'public' }]}
        doors={[]}
        terrain={[]}
        tokens={[]}
        camera={camera}
        isDm={true}
        selectedObjectId="w1"
      />,
    )
    expect(html).toContain('battle-map__wall--selected')
    expect(html).toContain('data-selected="true"')
  })

  it('renders selected door with battle-map__door--selected class and data-selected attribute', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        doorStateLabel={(state) => state}
        widthCells={10}
        heightCells={10}
        walls={[]}
        doors={[
          {
            door_id: 'd1',
            x1: 1,
            y1: 1,
            x2: 2,
            y2: 1,
            state: 'closed',
            revealed: true,
          },
        ]}
        terrain={[]}
        tokens={[]}
        camera={camera}
        isDm={true}
        selectedObjectId="d1"
      />,
    )
    expect(html).toContain('battle-map__door--selected')
    expect(html).toContain('data-selected="true"')
  })

  it('renders freehand drawings as SVG polylines with cell-scaled coordinates', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        doorStateLabel={(state) => state}
        widthCells={10}
        heightCells={10}
        walls={[]}
        doors={[]}
        terrain={[]}
        drawings={[
          {
            id: 'dr1',
            payload: {
              kind: 'freehand',
              points: [
                [1, 2],
                [3, 4],
              ],
            },
          },
        ]}
        tokens={[]}
        camera={camera}
        isDm={false}
      />,
    )
    expect(html).toContain('data-testid="battle-map-drawing"')
    expect(html).toContain('data-drawing-id="dr1"')
    expect(html).toContain('points="40,80 120,160"')
    expect(html).toContain('battle-map__drawing')
  })

  it('renders selected drawing with battle-map__drawing--selected class', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        doorStateLabel={(state) => state}
        widthCells={10}
        heightCells={10}
        walls={[]}
        doors={[]}
        terrain={[]}
        drawings={[
          {
            id: 'dr1',
            payload: {
              kind: 'freehand',
              points: [
                [1, 2],
                [3, 4],
              ],
            },
          },
        ]}
        tokens={[]}
        camera={camera}
        isDm={true}
        selectedObjectId="dr1"
      />,
    )
    expect(html).toContain('battle-map__drawing--selected')
    expect(html).toContain('data-selected="true"')
  })

  it('draws each freehand stroke in its own colour and width; older drawings get the defaults', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        doorStateLabel={(state) => state}
        widthCells={10}
        heightCells={10}
        walls={[]}
        doors={[]}
        terrain={[]}
        drawings={[
          { id: 'dr-red', payload: { kind: 'freehand', points: [[1, 1], [2, 2]], color: '#e05252', width: 8 } },
          { id: 'dr-old', payload: { kind: 'freehand', points: [[3, 3], [4, 4]] } },
          { id: 'dr-bad', payload: { kind: 'freehand', points: [[5, 5], [6, 6]], color: 'url(x)', width: 99 } },
        ]}
        tokens={[]}
        camera={camera}
        isDm={false}
      />,
    )
    expect(html).toMatch(/data-drawing-id="dr-red"[^>]*stroke="#e05252" stroke-width="8"/)
    expect(html).toMatch(/data-drawing-id="dr-old"[^>]*stroke="#f2efe8" stroke-width="3"/)
    expect(html).toMatch(/data-drawing-id="dr-bad"[^>]*stroke="#f2efe8" stroke-width="12"/)
  })

  it('selecting a drawing adds a gold halo without changing its colour or width', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        doorStateLabel={(state) => state}
        widthCells={10}
        heightCells={10}
        walls={[]}
        doors={[]}
        terrain={[]}
        drawings={[
          { id: 'dr1', payload: { kind: 'freehand', points: [[1, 1], [2, 2]], color: '#4a90e2', width: 5 } },
        ]}
        tokens={[]}
        camera={camera}
        isDm={true}
        selectedObjectId="dr1"
      />,
    )
    expect(html).toMatch(/class="battle-map__drawing-halo" stroke-width="11"/)
    expect(html).toMatch(/data-drawing-id="dr1"[^>]*stroke="#4a90e2" stroke-width="5"/)
  })

  it('previews the stroke being drawn in the current pen colour and width', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        doorStateLabel={(state) => state}
        widthCells={10}
        heightCells={10}
        walls={[]}
        doors={[]}
        terrain={[]}
        tokens={[]}
        camera={camera}
        isDm={true}
        previewDrawingPoints={[[1, 1], [2, 2]]}
        previewDrawingStroke={{ color: '#5cc26a', width: 10 }}
      />,
    )
    expect(html).toMatch(/data-testid="battle-map-preview-drawing"[^>]*stroke="#5cc26a" stroke-width="10"/)
  })

  it('skips drawings with unknown payload kind without error', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        doorStateLabel={(state) => state}
        widthCells={10}
        heightCells={10}
        walls={[]}
        doors={[]}
        terrain={[]}
        drawings={[
          {
            id: 'dr-custom',
            payload: {
              kind: 'polygon',
              sides: 6,
            },
          },
        ]}
        tokens={[]}
        camera={camera}
        isDm={false}
      />,
    )
    expect(html).not.toContain('dr-custom')
    expect(html).not.toContain('data-testid="battle-map-drawing"')
    expect(html).not.toContain('battle-map__drawing')
  })

  it('paints Normal terrain green and draws the grid above terrain fills', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        doorStateLabel={(state) => state}
        widthCells={4}
        heightCells={4}
        walls={[]}
        doors={[]}
        terrain={[{ x: 1, y: 1, terrain_kind: 'normal' }]}
        tokens={[]}
        camera={camera}
        isDm={true}
      />,
    )
    expect(html).toMatch(/data-terrain-kind="normal"[^>]*fill="#5fa35a"/)
    expect(html.indexOf('data-testid="battle-map-grid"')).toBeGreaterThan(
      html.indexOf('data-testid="battle-map-terrain"'),
    )
  })
})

describe('BattleMapCanvas camera geometry', () => {
  it('sits at the wrap top-left at its natural map size so camera math holds', () => {
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        doorStateLabel={(state) => state}
        widthCells={10}
        heightCells={8}
        walls={[]}
        doors={[]}
        terrain={[]}
        tokens={[]}
        camera={camera}
        isDm={true}
      />,
    )
    // 10x40=400 by 8x40=320: the camera translate/scale with origin 0 0
    // assumes exactly this box at the wrap's top-left (no flex centring).
    expect(html).toMatch(
      /<svg[^>]*style="[^"]*position:absolute[^"]*left:0[^"]*top:0[^"]*width:400px[^"]*height:320px[^"]*"/,
    )
  })
})

describe('BattleMapCanvas door labels', () => {
  const door = { door_id: 'd1', x1: 1, y1: 1, x2: 2, y2: 1, state: 'closed', revealed: true }

  it.each([
    ['zh-TW', '關閉'],
    ['en', 'Closed'],
  ] as const)('shows the %s door state label instead of the raw state', (locale, label) => {
    const copy = sessionCopy(locale)
    const html = renderToStaticMarkup(
      <BattleMapCanvas
        doorStateLabel={(state) => doorStateLabel(copy, state)}
        widthCells={4}
        heightCells={4}
        walls={[]}
        doors={[door]}
        terrain={[]}
        tokens={[]}
        camera={camera}
        isDm
      />,
    )
    expect(html).toContain(`>${label}</text>`)
    expect(html).not.toContain('>closed</text>')
  })

  it('maps every door state to both locales', () => {
    for (const locale of ['zh-TW', 'en'] as const) {
      const copy = sessionCopy(locale)
      for (const state of ['open', 'closed', 'locked', 'broken']) {
        expect(doorStateLabel(copy, state)).not.toBe(state)
      }
    }
  })
})
