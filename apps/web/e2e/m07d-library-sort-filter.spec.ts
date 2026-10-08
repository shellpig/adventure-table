import { expect, test, type APIRequestContext, type Page } from './support/roomTest'
import { json } from './support/quickCombat'

test.setTimeout(180_000)

type MonsterSummary = {
  ref: string
  name: string
  type?: string | null
  challenge_rating?: number | null
  armor_class?: number | null
  max_hp?: number | null
  walk_speed?: number | null
}

type CardData = { name: string; meta: string }

async function createCustom(
  request: APIRequestContext,
  roomId: string,
  payload: Record<string, unknown>,
): Promise<MonsterSummary> {
  return json<MonsterSummary>(
    await request.post(`/api/rooms/${roomId}/monster-library/custom`, { data: payload }),
  )
}

async function readCards(page: Page): Promise<CardData[]> {
  return page.locator('.monster-library__item').evaluateAll((items) =>
    items.map((item) => ({
      name: item.querySelector('.monster-library__item-name')?.textContent?.trim() ?? '',
      meta: item.querySelector('.monster-library__item-meta')?.textContent?.trim() ?? '',
    })),
  )
}

function metaHp(meta: string): number | null {
  const match = /HP (\d+)/.exec(meta)
  return match ? Number(match[1]) : null
}

function metaCr(meta: string): number | null {
  const match = /CR ([\d.]+)/.exec(meta)
  return match ? Number(match[1]) : null
}

test('M07-D D.4 Room Monster Library sorts by HP descending across load-more', async ({
  page,
  request,
  roomContext,
}) => {
  const { roomId } = roomContext
  await createCustom(request, roomId, {
    name: 'E2E D4 Tortoise',
    armor_class: 12,
    max_hp: 10,
    size: 'Medium',
    type: 'beast',
    challenge_rating: 0.5,
  })
  await createCustom(request, roomId, {
    name: 'E2E D4 Ogre Brute',
    armor_class: 11,
    max_hp: 60,
    size: 'Large',
    type: 'giant',
    challenge_rating: 2,
  })
  await createCustom(request, roomId, {
    name: 'E2E D4 Dragon Whelp',
    armor_class: 14,
    max_hp: 40,
    size: 'Medium',
    type: 'dragon',
    challenge_rating: 12,
  })

  await page.goto(`/rooms/${roomId}/monster-library`)
  await expect(page.getByRole('heading', { name: 'Monster Library', level: 1 })).toBeVisible()
  await expect(page.locator('.monster-library__item').first()).toBeVisible()

  await page.locator('.monster-library__filters').getByLabel('Sort by').selectOption('max_hp')
  await page.locator('.monster-library__filters').getByLabel('Order').selectOption('desc')

  // Wait until the HP-desc order reaches the list (first card is the
  // highest-HP built-in, the Tarrasque at 676 HP).
  await expect
    .poll(async () => metaHp((await readCards(page))[0]?.meta ?? ''), { timeout: 15_000 })
    .toBe(676)

  // HP 60 sits below ~144 built-ins, HP 10 near the end of the 300+ entry
  // library: keep loading until the deepest custom is visible.
  for (let round = 0; round < 8; round += 1) {
    const cards = await readCards(page)
    if (cards.some((card) => card.name === 'E2E D4 Tortoise')) break
    await page.getByRole('button', { name: 'Load more' }).click()
  }
  await expect
    .poll(
      async () =>
        (await readCards(page)).some((card) => card.name === 'E2E D4 Tortoise'),
      { timeout: 15_000 },
    )
    .toBe(true)

  const cards = await readCards(page)
  const hpValues = cards.map((card) => metaHp(card.meta))
  expect(hpValues.every((hp) => hp !== null)).toBe(true)
  const ordered = [...(hpValues as number[])]
  expect(ordered).toEqual([...ordered].sort((a, b) => b - a))

  const names = cards.map((card) => card.name)
  expect(names.indexOf('E2E D4 Ogre Brute')).toBeLessThan(names.indexOf('E2E D4 Dragon Whelp'))
  expect(names.indexOf('E2E D4 Dragon Whelp')).toBeLessThan(names.indexOf('E2E D4 Tortoise'))
})

test('M07-D D.4 Room Monster Library filters type=dragon with CR range 10-15', async ({
  page,
  request,
  roomContext,
}) => {
  const { roomId } = roomContext
  await createCustom(request, roomId, {
    name: 'E2E D4 Range Drake',
    armor_class: 16,
    max_hp: 90,
    size: 'Large',
    type: 'dragon',
    challenge_rating: 12,
  })
  await createCustom(request, roomId, {
    name: 'E2E D4 Range Wyrmling',
    armor_class: 13,
    max_hp: 25,
    size: 'Small',
    type: 'dragon',
    challenge_rating: 3,
  })
  await createCustom(request, roomId, {
    name: 'E2E D4 Range Ooze',
    armor_class: 8,
    max_hp: 45,
    size: 'Medium',
    type: 'ooze',
    challenge_rating: 12,
  })

  await page.goto(`/rooms/${roomId}/monster-library`)
  await expect(page.getByRole('heading', { name: 'Monster Library', level: 1 })).toBeVisible()
  await expect(page.locator('.monster-library__item').first()).toBeVisible()

  const filters = page.locator('.monster-library__filters')
  await filters.getByLabel('Type').selectOption('dragon')
  await filters.getByLabel('Challenge Rating').selectOption('range')
  await filters.getByLabel('CR ≥').selectOption('10')
  await filters.getByLabel('CR ≤').selectOption('15')

  await expect
    .poll(
      async () =>
        (await readCards(page)).some((card) => card.name === 'E2E D4 Range Drake'),
      { timeout: 15_000 },
    )
    .toBe(true)

  // Load everything the filter matches, then verify every card.
  for (let round = 0; round < 10; round += 1) {
    const loadMore = page.getByRole('button', { name: 'Load more' })
    if ((await loadMore.count()) === 0) break
    await loadMore.click()
  }
  const cards = await readCards(page)
  expect(cards.length).toBeGreaterThan(0)
  for (const card of cards) {
    expect(card.meta).toContain('dragon')
    const cr = metaCr(card.meta)
    expect(cr).not.toBeNull()
    expect(cr as number).toBeGreaterThanOrEqual(10)
    expect(cr as number).toBeLessThanOrEqual(15)
  }
  const names = cards.map((card) => card.name)
  expect(names).toContain('E2E D4 Range Drake')
  expect(names).not.toContain('E2E D4 Range Wyrmling')
  expect(names).not.toContain('E2E D4 Range Ooze')

  // min > max is blocked inline in English without a server round trip.
  await filters.getByLabel('CR ≥').selectOption('15')
  await filters.getByLabel('CR ≤').selectOption('10')
  await expect(page.getByRole('alert')).toContainText(
    'CR minimum cannot be greater than the maximum.',
  )
})

test('M07-D D.4 Room Monster Library sort/filter controls are labelled in zh-TW', async ({
  page,
  roomContext,
}) => {
  const { roomId } = roomContext
  await page.goto('/')
  await page.evaluate(
    ({ room }) => {
      window.localStorage.setItem('adventure-table.recent-rooms.v1', JSON.stringify([room]))
      window.localStorage.setItem('adventure-table.locale', 'zh-TW')
      window.sessionStorage.setItem('adventure-table.active-room.v1', room.roomId)
    },
    {
      room: {
        roomId,
        code: roomContext.code,
        name: roomContext.name,
        accessToken: roomContext.accessToken,
        authority: roomContext.authority,
      },
    },
  )

  await page.goto(`/rooms/${roomId}/monster-library`)
  await expect(page.getByRole('heading', { name: '怪物庫', level: 1 })).toBeVisible()
  await expect(page.locator('.monster-library__item').first()).toBeVisible()

  for (const label of [
    '排序',
    '升冪',
    '降冪',
    '體型',
    '類型',
    '全部',
    '挑戰等級',
    '不限',
    '等於',
    '範圍',
  ]) {
    await expect(page.locator('.monster-library__filters')).toContainText(label)
  }

  // Card meta shows the walking speed with a Chinese label.
  const searchInput = page.getByPlaceholder('搜尋怪物名稱、類型或子類型…')
  await searchInput.fill('地精')
  await page.getByRole('button', { name: '重新整理' }).click()
  const goblinItem = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: /^地精$/ }),
  })
  await expect(goblinItem).toBeVisible()
  await expect(goblinItem.locator('.monster-library__item-meta')).toContainText('速度 30 ft.')

  // min > max is blocked inline in Chinese as well.
  await searchInput.fill('')
  await page.getByRole('button', { name: '重新整理' }).click()
  const zhFilters = page.locator('.monster-library__filters')
  await zhFilters.getByLabel('挑戰等級').selectOption('range')
  await zhFilters.getByLabel('CR ≥').selectOption('15')
  await zhFilters.getByLabel('CR ≤').selectOption('10')
  await expect(page.getByRole('alert')).toContainText('CR 下限不可大於上限。')
})
