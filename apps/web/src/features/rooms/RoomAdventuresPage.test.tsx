import { readFileSync } from 'node:fs'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { AdventureApiError, type AdventureDefinition } from '../../api/adventures'
import { RoomAssetApiError } from '../../api/roomAssets'
import { LocaleProvider } from '../../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type LocaleStorage } from '../../i18n/locale'
import { adventureErrorMessage, adventuresCopy } from './adventuresCopy'
import {
  AdventureList,
  adventureActions,
  adventurePermissions,
  roomAdventuresRouteFromPath,
} from './RoomAdventuresPage'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const ADVENTURE_ID = '20000000-0000-4000-8000-000000000001'

function testStorage(locale: 'en' | 'zh-TW'): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? locale : null),
    setItem: () => undefined,
  }
}

describe('Room Adventures routing and permissions', () => {
  it('parses Room-scoped Adventure list and detail paths and rejects campaigns path', () => {
    expect(roomAdventuresRouteFromPath(`/rooms/${ROOM_ID}/adventures`)).toEqual({
      roomId: ROOM_ID,
      adventureId: null,
    })
    expect(
      roomAdventuresRouteFromPath(`/rooms/${ROOM_ID}/adventures/${ADVENTURE_ID}`),
    ).toEqual({
      roomId: ROOM_ID,
      adventureId: ADVENTURE_ID,
    })
    expect(roomAdventuresRouteFromPath(`/rooms/${ROOM_ID}/campaigns`)).toBeNull()
    expect(
      roomAdventuresRouteFromPath(`/rooms/${ROOM_ID}/campaigns/${ADVENTURE_ID}`),
    ).toBeNull()
    expect(roomAdventuresRouteFromPath(`/rooms/${ROOM_ID}/characters`)).toBeNull()
    expect(
      roomAdventuresRouteFromPath(`/rooms/${ROOM_ID}/adventures/${ADVENTURE_ID}/extra`),
    ).toBeNull()
  })

  it('allows authoring only for owner or dm', () => {
    expect(adventurePermissions('owner')).toEqual({ canAuthor: true })
    expect(adventurePermissions('dm')).toEqual({ canAuthor: true })
    expect(adventurePermissions('member')).toEqual({ canAuthor: false })
    expect(adventurePermissions(null)).toEqual({ canAuthor: false })
    expect(adventurePermissions(undefined)).toEqual({ canAuthor: false })
  })

  it('provides correct actions per status', () => {
    expect(adventureActions('draft')).toEqual({
      finalize: true,
      archive: true,
      delete: true,
    })
    expect(adventureActions('finalized')).toEqual({
      finalize: false,
      archive: true,
      delete: true,
    })
    expect(adventureActions('archived')).toEqual({
      finalize: false,
      archive: false,
      delete: true,
    })
  })
})

describe('Adventures copy and error mapping', () => {
  it('maintains key parity between en and zh-TW without P6 references', () => {
    const en = adventuresCopy('en')
    const zhTw = adventuresCopy('zh-TW')

    const enKeys = Object.keys(en).sort()
    const zhTwKeys = Object.keys(zhTw).sort()

    expect(enKeys).toEqual(zhTwKeys)

    for (const key of enKeys) {
      expect(en[key as keyof typeof en]).toBeTruthy()
      expect(zhTw[key as keyof typeof zhTw]).toBeTruthy()
      expect(en[key as keyof typeof en]).not.toContain('P6')
      expect(zhTw[key as keyof typeof zhTw]).not.toContain('P6')
    }
  })

  it('maps each known error code in both locales and falls back to requestFailed', () => {
    const codes = [
      'adventure_not_found',
      'adventure_archived',
      'adventure_status_conflict',
      'adventure_attached_use_archive',
      'adventure_not_finalized',
      'adventure_already_attached',
      'asset_visibility_not_allowed',
      'asset_in_use',
      'asset_media_type_not_supported',
      'asset_too_large',
    ]

    for (const locale of ['en', 'zh-TW'] as const) {
      const copy = adventuresCopy(locale)

      for (const code of codes) {
        const error = new AdventureApiError(400, code, 'Test error')
        const message = adventureErrorMessage(error, copy)
        expect(message).not.toBe(copy.requestFailed)
        expect(message.length).toBeGreaterThan(0)
      }

      const assetError = new RoomAssetApiError(400, 'asset_too_large', 'File too large')
      expect(adventureErrorMessage(assetError, copy)).toBe(copy.errAssetTooLarge)

      expect(adventureErrorMessage(new Error('unknown'), copy)).toBe(copy.requestFailed)
      expect(adventureErrorMessage(null, copy)).toBe(copy.requestFailed)
    }
  })
})

describe('AdventureList rendering and source assertions', () => {
  const sampleAdventures: AdventureDefinition[] = [
    {
      id: '11111111-1111-4111-8111-111111111111',
      room_id: ROOM_ID,
      name: 'Sunless Citadel',
      summary: 'A goblin-infested fortress.',
      ruleset: 'dnd5e-2014',
      status: 'draft',
      created_at: '2026-09-20T00:00:00Z',
      updated_at: '2026-09-20T01:00:00Z',
    },
    {
      id: '22222222-2222-4222-8222-222222222222',
      room_id: ROOM_ID,
      name: 'Forge of Fury',
      summary: 'A dwarven stronghold.',
      ruleset: 'dnd5e-2014',
      status: 'finalized',
      created_at: '2026-09-20T00:00:00Z',
      updated_at: '2026-09-20T02:00:00Z',
    },
    {
      id: '33333333-3333-4333-8333-333333333333',
      room_id: ROOM_ID,
      name: 'White Plume Mountain',
      summary: null,
      ruleset: 'dnd5e-2014',
      status: 'archived',
      created_at: '2026-09-20T00:00:00Z',
      updated_at: '2026-09-20T03:00:00Z',
    },
  ]

  it('renders names, status labels, open links, and only allowed action buttons per status', () => {
    const copy = adventuresCopy('en')
    const html = renderToStaticMarkup(
      <LocaleProvider storage={testStorage('en')} documentTarget={null}>
        <AdventureList
          adventures={sampleAdventures}
          copy={copy}
          roomId={ROOM_ID}
          onFinalize={vi.fn()}
          onArchive={vi.fn()}
          onDelete={vi.fn()}
        />
      </LocaleProvider>,
    )

    // Check names
    expect(html).toContain('Sunless Citadel')
    expect(html).toContain('Forge of Fury')
    expect(html).toContain('White Plume Mountain')

    // Check status labels
    expect(html).toContain('Draft')
    expect(html).toContain('Finalized')
    expect(html).toContain('Archived')

    // Check open links
    expect(html).toContain(`/rooms/${ROOM_ID}/adventures/11111111-1111-4111-8111-111111111111`)
    expect(html).toContain(`/rooms/${ROOM_ID}/adventures/22222222-2222-4222-8222-222222222222`)
    expect(html).toContain(`/rooms/${ROOM_ID}/adventures/33333333-3333-4333-8333-333333333333`)

    // Action buttons:
    // Draft has Finalize, Archive, Delete
    // Finalized has Archive, Delete (no Finalize)
    // Archived has Delete only (no Finalize, no Archive)
    // Counting button occurrences in rendered HTML:
    // Finalize: only 1
    const finalizeMatches = html.match(new RegExp(`>${copy.finalize}<`, 'g'))
    expect(finalizeMatches).toHaveLength(1)

    // Archive: 2 (Draft + Finalized)
    const archiveMatches = html.match(new RegExp(`>${copy.archive}<`, 'g'))
    expect(archiveMatches).toHaveLength(2)

    // Delete: 3 (Draft + Finalized + Archived)
    const deleteMatches = html.match(new RegExp(`>${copy.delete}<`, 'g'))
    expect(deleteMatches).toHaveLength(3)
  })

  it('requires confirmation before delete and archive, and guards loading with canAuthor', () => {
    const source = readFileSync(new URL('./RoomAdventuresPage.tsx', import.meta.url), 'utf8')

    expect(source).toContain('window.confirm(copy.deleteConfirm)')
    expect(source).toContain('window.confirm(copy.archiveConfirm)')
    expect(source).toContain('if (!recent || !canAuthor) return')
  })
})
