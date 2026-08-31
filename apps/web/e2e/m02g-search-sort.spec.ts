import { expect, test, type Locator, type Page } from '@playwright/test'

const COLLATOR_OPTIONS = { sensitivity: 'base', numeric: true } as const

async function expectDraftSaved(page: Page) {
  await expect(page.getByText(/Saved on server|已儲存至伺服器/)).toBeVisible()
}

async function startDraft(page: Page, name: string) {
  await page.goto('/characters')
  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)
  await page.getByLabel('Character name').fill(name)
  await page.getByLabel('Target character level').fill('1')
  await page.getByRole('button', { name: 'Save Basic Details' }).click()
  await expectDraftSaved(page)
}

async function openListbox(page: Page, input: Locator, query = '') {
  await expect(input).toBeEnabled()
  await input.focus()
  await input.fill(query)
  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error('Combobox has no aria-controls listbox')
  const listbox = page.locator(`[id="${listboxId}"]`)
  await expect(listbox).toBeVisible()
  return listbox
}

async function expectAliasMatch(listbox: Locator, expected: string) {
  await expect(async () => {
    const matched = await listbox.locator('.combobox-option.is-match > span').allInnerTexts()
    expect(matched.map((text) => text.trim())).toContain(expected)
  }).toPass()
}

async function optionOrder(listbox: Locator) {
  const texts = await listbox.locator('.combobox-option > span').allInnerTexts()
  return texts.map((text) => text.trim())
}

async function sortedInBrowser(page: Page, locale: string, values: string[]) {
  return page.evaluate(
    ({ locale: target, values: items, options }) =>
      [...items].sort(new Intl.Collator(target, options).compare),
    { locale, values, options: COLLATOR_OPTIONS },
  )
}

test('M02-G finds a zh-TW entry through its English alias without showing English', async ({ page }) => {
  await startDraft(page, `M02-G alias zh ${Date.now()}`)
  await page.getByRole('button', { name: /Origin/ }).click()
  await page.getByTestId('locale-option-zh-TW').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-TW')

  const race = page.getByRole('combobox', { name: '種族' })
  const aliasListbox = await openListbox(page, race, 'elf')
  await expectAliasMatch(aliasListbox, '精靈')
  await expect(aliasListbox.getByText('Elf', { exact: true })).toHaveCount(0)

  const nativeListbox = await openListbox(page, race, '精靈')
  await expectAliasMatch(nativeListbox, '精靈')
})

test('M02-G finds an English entry through its zh-TW alias without showing zh-TW', async ({ page }) => {
  await startDraft(page, `M02-G alias en ${Date.now()}`)
  await page.getByRole('button', { name: /Origin/ }).click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')

  const race = page.getByRole('combobox', { name: 'Race' })
  const aliasListbox = await openListbox(page, race, '精靈')
  await expectAliasMatch(aliasListbox, 'Elf')
  await expect(aliasListbox.getByText('精靈', { exact: true })).toHaveCount(0)
})

test('M02-G orders rules-content options by the active locale display name', async ({ page }) => {
  await startDraft(page, `M02-G sort ${Date.now()}`)
  await page.getByRole('button', { name: /Origin/ }).click()

  const englishOrder = await optionOrder(await openListbox(page, page.getByRole('combobox', { name: 'Race' })))
  expect(englishOrder.length).toBeGreaterThan(1)
  expect(englishOrder).toEqual(await sortedInBrowser(page, 'en', englishOrder))

  await page.keyboard.press('Escape')
  await page.getByTestId('locale-option-zh-TW').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-TW')

  const chineseOrder = await optionOrder(await openListbox(page, page.getByRole('combobox', { name: '種族' })))
  expect(chineseOrder).toHaveLength(englishOrder.length)
  expect(chineseOrder).toEqual(await sortedInBrowser(page, 'zh-TW', chineseOrder))
  expect(chineseOrder).not.toEqual(englishOrder)
})

test('M02-G keeps numeric Standard Array options in configured order in both locales', async ({ page }) => {
  await startDraft(page, `M02-G numeric ${Date.now()}`)
  await page.getByRole('button', { name: /Abilities/ }).click()
  await page.getByRole('tab', { name: 'Standard Array' }).click()

  const englishValues = await optionOrder(
    await openListbox(page, page.getByRole('combobox', { name: 'STR · Strength' })),
  )
  expect(englishValues).toEqual(['15', '14', '13', '12', '10', '8'])

  await page.keyboard.press('Escape')
  await page.getByTestId('locale-option-zh-TW').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-TW')

  const chineseValues = await optionOrder(
    await openListbox(page, page.getByRole('combobox', { name: 'STR · 力量' })),
  )
  expect(chineseValues).toEqual(englishValues)
})
