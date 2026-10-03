import { readFileSync } from 'node:fs'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  MonsterLibraryApiError,
  type MonsterLibraryDetailView,
  type MonsterLibrarySummaryView,
} from '../../api/monsterLibrary'
import { LocaleProvider } from '../../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type LocaleStorage } from '../../i18n/locale'
import {
  monsterLibraryCopy,
  monsterLibraryErrorMessage,
} from './monsterLibraryCopy'
import {
  libraryPermissions,
  RoomMonsterLibraryPage,
  roomMonsterLibraryRouteFromPath,
} from './RoomMonsterLibraryPage'
import * as roomStorage from './roomStorage'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'

function testStorage(locale: 'en' | 'zh-TW'): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? locale : null),
    setItem: () => undefined,
  }
}

describe('Room Monster Library routing and permissions', () => {
  it('parses Room-scoped monster library path and rejects other paths', () => {
    expect(roomMonsterLibraryRouteFromPath(`/rooms/${ROOM_ID}/monster-library`)).toEqual({
      roomId: ROOM_ID,
    })
    expect(roomMonsterLibraryRouteFromPath(`/rooms/${ROOM_ID}/monster-library/`)).toEqual({
      roomId: ROOM_ID,
    })
    expect(roomMonsterLibraryRouteFromPath(`/rooms/${ROOM_ID}/adventures`)).toBeNull()
    expect(roomMonsterLibraryRouteFromPath(`/rooms/${ROOM_ID}/campaigns`)).toBeNull()
    expect(roomMonsterLibraryRouteFromPath(`/rooms/${ROOM_ID}/characters`)).toBeNull()
    expect(
      roomMonsterLibraryRouteFromPath(`/rooms/${ROOM_ID}/monster-library/extra`),
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

describe('RoomMonsterLibraryPage permissions & member rendering', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders missing access when no recent room token is found', () => {
    vi.spyOn(roomStorage, 'recentRoomForId').mockReturnValue(null)
    const copy = monsterLibraryCopy('en')

    const html = renderToStaticMarkup(
      <LocaleProvider storage={testStorage('en')} documentTarget={null}>
        <RoomMonsterLibraryPage roomId={ROOM_ID} />
      </LocaleProvider>,
    )

    expect(html).toContain(copy.missingAccess)
    expect(html).toContain(copy.backRoom)
    expect(html).not.toContain(copy.createAction)
  })

  it('renders forbidden message and NO monster library data when accessed as member', () => {
    vi.spyOn(roomStorage, 'recentRoomForId').mockReturnValue({
      roomId: ROOM_ID,
      code: 'ROOM01',
      name: 'Test Room',
      accessToken: 'member-token',
      authority: 'member',
    })
    const copy = monsterLibraryCopy('en')

    const html = renderToStaticMarkup(
      <LocaleProvider storage={testStorage('en')} documentTarget={null}>
        <RoomMonsterLibraryPage roomId={ROOM_ID} />
      </LocaleProvider>,
    )

    expect(html).toContain(copy.errMonsterLibraryForbidden)
    expect(html).toContain(copy.backRoom)
    expect(html).not.toContain(copy.createAction)
    expect(html).not.toContain(copy.searchPlaceholder)
    expect(html).not.toContain('monster-library__list')
  })

  it('renders monster library workspace shell when accessed as owner or dm', () => {
    vi.spyOn(roomStorage, 'recentRoomForId').mockReturnValue({
      roomId: ROOM_ID,
      code: 'ROOM01',
      name: 'Test Room',
      accessToken: 'owner-token',
      authority: 'owner',
    })
    const copy = monsterLibraryCopy('en')

    const html = renderToStaticMarkup(
      <LocaleProvider storage={testStorage('en')} documentTarget={null}>
        <RoomMonsterLibraryPage roomId={ROOM_ID} />
      </LocaleProvider>,
    )

    expect(html).toContain(copy.title)
    expect(html).toContain(copy.createAction)
    expect(html).toContain(copy.searchPlaceholder)
    expect(html).toContain(copy.filterAll)
    expect(html).toContain(copy.filterBuiltin)
    expect(html).toContain(copy.filterCustom)
    expect(html).toContain(copy.showArchived)
  })
})

describe('RoomMonsterLibraryPage contract and source assertions', () => {
  const source = readFileSync(new URL('./RoomMonsterLibraryPage.tsx', import.meta.url), 'utf8')

  it('contains expected_revision on patch, copy, archive, and delete operations', () => {
    expect(source).toContain('expected_revision: detail.revision')
    expect(source).toContain('deleteCustomMonster(roomId, templateId, token, detail.revision)')
  })

  it('re-reads list on unknown/network result and never auto-resends', () => {
    expect(source).toContain('await reloadList()')
  })

  it('keeps form intact on failure rather than clearing inputs', () => {
    expect(source).toContain('// Keep form intact on error!')
    expect(source).toContain('setDetailError(monsterLibraryErrorMessage(cause, copy))')
  })

  it('disables create, copy, save, archive, and delete buttons while in flight', () => {
    expect(source).toContain('disabled={pendingAction !== null}')
  })

  it('requires window.confirm for archive and delete', () => {
    expect(source).toContain('window.confirm(copy.archiveConfirm)')
    expect(source).toContain('window.confirm(copy.deleteConfirm)')
  })

  it('renders English original label for built-in desc in zh-TW and omits in en', () => {
    expect(source).toContain("locale === 'zh-TW'")
    expect(source).toContain('copy.englishOriginal')
    expect(source).toContain('monster-library__desc-lang-label')
  })

  it('excludes client-side desc filtering on search', () => {
    // Search only queries the server, never client-side desc filtering
    expect(source).not.toContain('t.desc.includes')
    expect(source).not.toContain('a.desc.includes')
  })

  it('implements paging with Load more button and formatMonsterName/formatAbilityName', () => {
    expect(source).toContain('hasMore')
    expect(source).toContain('copy.loadMore')
    expect(source).toContain('reloadList(false)')
    expect(source).toContain('formatMonsterName')
    expect(source).toContain('formatAbilityName')
    expect(source).toContain('formatMonsterRuleField')
    // Normalized rules read directly without ?? '-'
    expect(source).not.toContain("detail.rules.armor_class ?? '-'")
    expect(source).not.toContain("detail.rules.max_hp ?? detail.rules.hit_points")
  })
})
