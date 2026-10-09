import { readFileSync } from 'node:fs'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { LocaleProvider } from '../../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type LocaleStorage } from '../../i18n/locale'
import {
  battleMapLibraryCopy,
} from './battleMapLibraryCopy'
import {
  libraryPermissions,
  RoomBattleMapLibraryPage,
  roomBattleMapLibraryRouteFromPath,
} from './RoomBattleMapLibraryPage'
import * as roomStorage from './roomStorage'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'

function testStorage(locale: 'en' | 'zh-TW'): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? locale : null),
    setItem: () => undefined,
  }
}

describe('Room Battle Map Library routing and permissions', () => {
  it('parses Room-scoped battle map library path and rejects other paths', () => {
    expect(roomBattleMapLibraryRouteFromPath(`/rooms/${ROOM_ID}/battle-maps`)).toEqual({
      roomId: ROOM_ID,
    })
    expect(roomBattleMapLibraryRouteFromPath(`/rooms/${ROOM_ID}/battle-maps/`)).toEqual({
      roomId: ROOM_ID,
    })
    expect(roomBattleMapLibraryRouteFromPath(`/rooms/${ROOM_ID}/monster-library`)).toBeNull()
    expect(roomBattleMapLibraryRouteFromPath(`/rooms/${ROOM_ID}/campaigns`)).toBeNull()
    expect(roomBattleMapLibraryRouteFromPath(`/rooms/${ROOM_ID}/characters`)).toBeNull()
    expect(
      roomBattleMapLibraryRouteFromPath(`/rooms/${ROOM_ID}/battle-maps/extra`),
    ).toBeNull()
  })

  it('allows library management only for owner or dm, never member', () => {
    expect(libraryPermissions('owner')).toEqual({ canManage: true })
    expect(libraryPermissions('dm')).toEqual({ canManage: true })
    expect(libraryPermissions('member')).toEqual({ canManage: false })
    expect(libraryPermissions(null)).toEqual({ canManage: false })
    expect(libraryPermissions(undefined)).toEqual({ canManage: false })
  })
})

describe('RoomBattleMapLibraryPage permissions & member rendering', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders missing access when no recent room token is found', () => {
    vi.spyOn(roomStorage, 'recentRoomForId').mockReturnValue(null)
    const copy = battleMapLibraryCopy('en')

    const html = renderToStaticMarkup(
      <LocaleProvider storage={testStorage('en')} documentTarget={null}>
        <RoomBattleMapLibraryPage roomId={ROOM_ID} />
      </LocaleProvider>,
    )

    expect(html).toContain(copy.missingAccess)
    expect(html).toContain(copy.backRoom)
    expect(html).not.toContain(copy.createBlankAction)
  })

  it('renders forbidden message and NO manage controls when accessed as member', () => {
    vi.spyOn(roomStorage, 'recentRoomForId').mockReturnValue({
      roomId: ROOM_ID,
      code: 'ROOM01',
      name: 'Test Room',
      accessToken: 'member-token',
      authority: 'member',
    })
    const copy = battleMapLibraryCopy('en')

    const html = renderToStaticMarkup(
      <LocaleProvider storage={testStorage('en')} documentTarget={null}>
        <RoomBattleMapLibraryPage roomId={ROOM_ID} />
      </LocaleProvider>,
    )

    expect(html).toContain(copy.forbidden)
    expect(html).toContain(copy.backRoom)
    expect(html).not.toContain(copy.createBlankAction)
    expect(html).not.toContain(copy.createImageAction)
    expect(html).not.toContain(copy.showArchived)
    expect(html).not.toContain('battle-map-library__grid')
  })

  it('renders battle map library workspace shell when accessed as owner or dm', () => {
    vi.spyOn(roomStorage, 'recentRoomForId').mockReturnValue({
      roomId: ROOM_ID,
      code: 'ROOM01',
      name: 'Test Room',
      accessToken: 'owner-token',
      authority: 'owner',
    })
    const copy = battleMapLibraryCopy('en')

    const html = renderToStaticMarkup(
      <LocaleProvider storage={testStorage('en')} documentTarget={null}>
        <RoomBattleMapLibraryPage roomId={ROOM_ID} />
      </LocaleProvider>,
    )

    expect(html).toContain(copy.title)
    expect(html).toContain(copy.createBlankAction)
    expect(html).toContain(copy.createImageAction)
    expect(html).toContain(copy.showArchived)
    expect(html).toContain(copy.refreshAction)
    expect(html).toContain('data-testid="show-archived-toggle"')
  })
})

describe('RoomBattleMapLibraryPage contract and source assertions', () => {
  const source = readFileSync(new URL('./RoomBattleMapLibraryPage.tsx', import.meta.url), 'utf8')

  it('closes map modals on Escape only when no action is pending', () => {
    expect(source).toContain("event.key !== 'Escape' || pendingAction !== null")
    expect(source.match(/<div className="modal-backdrop" role="dialog" aria-modal="true">/g)).toHaveLength(3)
  })

  it('contains expected_revision on copy, archive, and delete operations', () => {
    expect(source).toContain('expected_revision: copyTargetMap.revision')
    expect(source).toContain('expected_revision: map.revision')
    expect(source).toContain('deleteBattleMap(roomId, map.id, map.revision, token)')
  })

  it('disables create and copy buttons while request is pending', () => {
    expect(source).toContain("disabled={pendingAction === 'create'")
    expect(source).toContain("disabled={pendingAction === 'copy'")
  })

  it('re-reads list on error / 409 and never auto-resends', () => {
    expect(source).toContain('setListError(battleMapLibraryErrorMessage(cause, copy))')
    expect(source).toContain('await loadMaps()')
  })

  it('supports archived filter toggle passing includeArchived to listBattleMaps', () => {
    expect(source).toContain('includeArchived: showArchived')
  })
})
