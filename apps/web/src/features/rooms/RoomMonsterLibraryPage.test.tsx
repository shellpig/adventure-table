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
import {
  clampListWidth,
  DEFAULT_LIST_WIDTH,
  LIST_KEYBOARD_STEP,
  MAX_LIST_WIDTH,
  MIN_LIST_WIDTH,
  MONSTER_LIST_WIDTH_STORAGE_KEY,
  readListWidth,
  resolveKeyboardListWidth,
  writeListWidth,
} from './monsterLibraryLayout'
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

  it('lays built-in core stats out as two explicit rows', () => {
    const start = source.indexOf('<div className="monster-library__stats-grid">')
    const block = source.slice(start, source.indexOf('{/* Ability Scores */}'))
    const rows = block.split('<div className="monster-library__stats-row">')
    expect(rows).toHaveLength(3)
    for (const field of ['fieldArmorClass', 'fieldMaxHp', 'fieldSpeed']) {
      expect(rows[1]).toContain(`copy.${field}`)
    }
    for (const field of ['fieldSize', 'fieldType', 'fieldAlignment']) {
      expect(rows[2]).toContain(`copy.${field}`)
    }
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

describe('Monster library list splitter', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it.each(['en', 'zh-TW'] as const)('renders an accessible vertical separator in %s', (locale) => {
    vi.spyOn(roomStorage, 'recentRoomForId').mockReturnValue({
      roomId: ROOM_ID,
      code: 'ROOM01',
      name: 'Test Room',
      accessToken: 'owner-token',
      authority: 'owner',
    })
    const copy = monsterLibraryCopy(locale)

    const html = renderToStaticMarkup(
      <LocaleProvider storage={testStorage(locale)} documentTarget={null}>
        <RoomMonsterLibraryPage roomId={ROOM_ID} />
      </LocaleProvider>,
    )

    expect(copy.resizeList).not.toBe('')
    expect(html).toContain('role="separator"')
    expect(html).toContain('aria-orientation="vertical"')
    expect(html).toContain(`aria-label="${copy.resizeList}"`)
    expect(html).toContain(`aria-valuenow="${DEFAULT_LIST_WIDTH}"`)
    expect(html).toContain(`aria-valuemin="${MIN_LIST_WIDTH}"`)
    expect(html).toContain(`aria-valuemax="${MAX_LIST_WIDTH}"`)
    expect(html).toContain('tabindex="0"')
  })

  it('has distinct labels per locale', () => {
    expect(monsterLibraryCopy('en').resizeList).not.toBe(monsterLibraryCopy('zh-TW').resizeList)
  })

  it('steps with ArrowRight / ArrowLeft and clamps to min and max', () => {
    expect(resolveKeyboardListWidth(480, 'ArrowRight')).toBe(480 + LIST_KEYBOARD_STEP)
    expect(resolveKeyboardListWidth(480, 'ArrowLeft')).toBe(480 - LIST_KEYBOARD_STEP)
    expect(resolveKeyboardListWidth(MIN_LIST_WIDTH, 'ArrowLeft')).toBe(MIN_LIST_WIDTH)
    expect(resolveKeyboardListWidth(MAX_LIST_WIDTH, 'ArrowRight')).toBe(MAX_LIST_WIDTH)
    expect(resolveKeyboardListWidth(480, 'a')).toBeNull()
  })

  it('keeps the detail panel usable by capping against the container width', () => {
    expect(clampListWidth(5000, 1000)).toBe(1000 - 12 - 360)
    expect(clampListWidth(10, 1000)).toBe(MIN_LIST_WIDTH)
    expect(clampListWidth(900)).toBe(900)
  })

  it('persists keyboard width and restores it from storage', () => {
    const values = new Map<string, string>()
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => void values.set(key, value),
    }
    const next = resolveKeyboardListWidth(readListWidth(storage), 'ArrowRight')
    expect(next).toBe(DEFAULT_LIST_WIDTH + LIST_KEYBOARD_STEP)
    writeListWidth(next as number, storage)
    expect(values.get(MONSTER_LIST_WIDTH_STORAGE_KEY)).toBe(String(next))
    expect(readListWidth(storage)).toBe(next)
  })

  it('falls back to the default for missing, invalid or out-of-range stored values', () => {
    const make = (raw: string | null) => ({ getItem: () => raw, setItem: () => undefined })
    expect(readListWidth(make(null))).toBe(DEFAULT_LIST_WIDTH)
    expect(readListWidth(make('abc'))).toBe(DEFAULT_LIST_WIDTH)
    expect(readListWidth(make('99999'))).toBe(MAX_LIST_WIDTH)
    expect(readListWidth(make('10'))).toBe(MIN_LIST_WIDTH)
  })

  it('works when storage is unavailable or throws', () => {
    const throwing = {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      },
    }
    expect(readListWidth(throwing)).toBe(DEFAULT_LIST_WIDTH)
    expect(() => writeListWidth(500, throwing)).not.toThrow()
    expect(readListWidth(null)).toBe(DEFAULT_LIST_WIDTH)
    expect(() => writeListWidth(500, null)).not.toThrow()
  })
})
