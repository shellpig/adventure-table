import { expect, test, type Locator, type Page } from '@playwright/test'

async function expectDraftSaved(page: Page) {
  await expect(page.getByText(/Saved on server|已儲存至伺服器/)).toBeVisible()
}

async function currentDraftRevision(page: Page) {
  const text = (await page.locator('.builder-save-state span').innerText()).trim()
  const match = text.match(/(?:Draft revision|草稿修訂版)\s*(\d+)/)
  if (!match) throw new Error(`Cannot parse draft revision from: ${text}`)
  return Number(match[1])
}

async function waitForDraftRevision(page: Page, before: number) {
  await expect.poll(() => currentDraftRevision(page)).toBeGreaterThan(before)
  await expectDraftSaved(page)
}

async function chooseOption(page: Page, input: Locator, value: string, source?: string) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  await input.fill(value)
  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error(`Combobox for ${value} has no listbox`)
  let option = page.locator(`[id="${listboxId}"]`).getByRole('option').filter({
    has: page.getByText(value, { exact: true }),
  })
  if (source) option = option.filter({ has: page.getByText(source, { exact: true }) })
  await expect(option).toHaveCount(1)
  const before = await currentDraftRevision(page)
  await option.click()
  await waitForDraftRevision(page, before)
}

async function chooseSearchable(page: Page, label: string | RegExp, value: string, source?: string) {
  await chooseOption(page, page.getByRole('combobox', { name: label }), value, source)
}

async function chooseFirstEnabled(page: Page, input: Locator) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  await input.focus()
  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error('Combobox has no aria-controls listbox')
  const listbox = page.locator(`[id="${listboxId}"]`)
  await expect(listbox).toBeVisible()
  const option = listbox.locator('[role="option"]:not([disabled])').first()
  await expect(option).toBeVisible()
  const before = await currentDraftRevision(page)
  await option.click()
  await waitForDraftRevision(page, before)
}

async function fillEmptyComboboxes(page: Page, container: Locator) {
  for (let pass = 0; pass < 96; pass += 1) {
    const inputs = container.getByRole('combobox')
    let changed = false
    for (let index = 0; index < (await inputs.count()); index += 1) {
      const input = inputs.nth(index)
      if (!(await input.isVisible()) || !(await input.isEnabled())) continue
      if ((await input.inputValue()).trim()) continue
      await chooseFirstEnabled(page, input)
      changed = true
      break
    }
    if (!changed) return
  }
  throw new Error('Required combobox selections did not converge')
}

async function startDraft(page: Page, name: string) {
  await page.goto('/characters')
  await page.getByRole('button', { name: '+ Create Character' }).click()
  await page.getByLabel('Character name').fill(name)
  await page.getByLabel('Target character level').fill('1')
  const before = await currentDraftRevision(page)
  await page.getByRole('button', { name: 'Save Basic Details' }).click()
  await waitForDraftRevision(page, before)
}

test('M02-F presents PHB, SCAG inheritance, GoS flavor and source collisions by stable identity', async ({ request }) => {
  const get = async (key: string, locale: string) => {
    const response = await request.get(
      `/api/rules/presentation/${encodeURIComponent(key)}?locale=${encodeURIComponent(locale)}`,
    )
    expect(response.ok()).toBeTruthy()
    return response.json()
  }

  const variant = await get('phb2014:race:variant-human', 'zh-TW')
  expect(variant.key).toBe('phb2014:race:variant-human')
  expect(variant.fields[0].value).toBe('人類 (變體)')

  const soldier = await get('phb2014:background:soldier', 'zh-TW')
  const cityWatch = await get('scag:background:city-watch', 'zh-TW')
  expect(cityWatch.roleplay_suggestions.map((item: { text: string }) => item.text)).toEqual(
    soldier.roleplay_suggestions.map((item: { text: string }) => item.text),
  )
  expect(cityWatch.roleplay_suggestions[0].suggestion_id).toMatch(/^scag:background:city-watch:/)

  const fisherZh = await get('gos:background:fisher', 'zh-TW')
  const fisherEn = await get('gos:background:fisher', 'en')
  expect(fisherZh.optional_roleplay_tables[0].label).toBe('捕魚奇談')
  expect(fisherEn.optional_roleplay_tables[0].label).toBe('Fishing Tale')
  expect(fisherZh.optional_roleplay_tables[0].suggestions[0].suggestion_id).toBe(
    fisherEn.optional_roleplay_tables[0].suggestions[0].suggestion_id,
  )

  const srdAcolyte = await get('srd5.1:background:acolyte', 'zh-TW')
  const phbAcolyte = await get('phb2014:background:acolyte', 'zh-TW')
  expect(srdAcolyte.fields[0].value).toBe(phbAcolyte.fields[0].value)
  expect(srdAcolyte.key).not.toBe(phbAcolyte.key)
})

test('M02-F completes a bilingual PHB origin flow without changing selections', async ({ page, request }) => {
  test.slow()
  const name = `M02-F PHB ${Date.now()}`
  await startDraft(page, name)

  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Race', 'Elf')
  await chooseSearchable(page, 'Subrace', 'Wood Elf')
  await chooseSearchable(page, 'Background', 'Acolyte', "Player's Handbook 2014 Additions")

  await page.getByTestId('locale-option-zh-TW').click()
  await expect(page.getByRole('combobox', { name: '種族' })).toHaveValue('精靈')
  await expect(page.getByRole('combobox', { name: '亞種' })).toHaveValue('精靈 (木)')
  await expect(page.getByRole('combobox', { name: '背景' })).toHaveValue('侍僧')
  await page.getByTestId('locale-option-en').click()
  await expect(page.getByRole('combobox', { name: 'Background' })).toHaveValue('Acolyte')

  await page.getByRole('button', { name: /Abilities/ }).click()
  const beforeAbilities = await currentDraftRevision(page)
  await page.getByRole('button', { name: 'Save Ability Scores' }).click()
  await waitForDraftRevision(page, beforeAbilities)
  const languageChoice = page.locator('.builder-choice').filter({ hasText: 'Acolyte — Languages' })
  await chooseOption(page, languageChoice.getByRole('combobox', { name: 'Add selection' }), 'Celestial')
  await chooseOption(page, languageChoice.getByRole('combobox', { name: 'Add selection' }), 'Draconic')
  // Keep this flow future-proof as origin packs grow: any additional required
  // starting choice must be completed before Review, while optional roleplay stays untouched.
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  await page.getByRole('button', { name: /Class/ }).click()
  await chooseSearchable(page, 'Level 1 class', 'Barbarian')
  const skills = page.getByTestId('level-node-1').locator('.progression-choice')
  await chooseOption(page, skills.getByRole('combobox', { name: 'Add selection' }), 'Skill: Animal Handling')
  await chooseOption(page, skills.getByRole('combobox', { name: 'Add selection' }), 'Skill: Athletics')
  await fillEmptyComboboxes(page, page.locator('.level-rail'))

  await page.getByRole('button', { name: /Equipment/ }).click()
  await chooseSearchable(page, /greataxe or/, 'Greataxe')
  await chooseSearchable(page, /two handaxes or/, '2 × Handaxe')
  await chooseSearchable(page, 'Choose a holy symbol', 'Amulet')
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  const draftId = page.url().match(/\/character-builder\/([0-9a-f-]{36})$/)?.[1]
  if (!draftId) throw new Error(`Cannot parse draft id from ${page.url()}`)

  await page.getByRole('button', { name: /Review/ }).click()
  const reviewResponse = await request.get(`/api/character-builder/drafts/${draftId}/review`)
  expect(reviewResponse.ok()).toBeTruthy()
  const review = await reviewResponse.json()
  const blockingIssues = review.issues.filter(
    (issue: { severity: string }) => issue.severity === 'blocking_error',
  )
  expect(blockingIssues, JSON.stringify(review.issues, null, 2)).toEqual([])
  expect(review.can_confirm, JSON.stringify(review.issues, null, 2)).toBeTruthy()

  const confirm = page.getByRole('button', { name: 'Confirm & Create Character' })
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
})

test('M02-F keeps a GoS optional flavor selection localized and non-mandatory', async ({ page }) => {
  await startDraft(page, `M02-F GoS ${Date.now()}`)
  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Background', 'Fisher')
  await page.getByRole('button', { name: /Equipment/ }).click()

  await page.getByTestId('locale-option-zh-TW').click()
  await expect(page.getByRole('heading', { name: '選填背景細節' })).toBeVisible()
  await page.getByRole('button', { name: '+ 曾與一隻巨型龍蝦搏鬥' }).click()
  await expectDraftSaved(page)
  await expect(page.getByTestId('optional-roleplay-fishing_tale')).toHaveText('曾與一隻巨型龍蝦搏鬥')
  await page.getByRole('button', { name: '+ 我尊敬那些靠辛勤工作維生的人。' }).click()
  await expectDraftSaved(page)

  await page.getByTestId('locale-option-en').click()
  await expect(page.getByTestId('optional-roleplay-fishing_tale')).toHaveText('Wrestled a giant lobster')
  await page.getByRole('button', { name: 'Clear selection' }).click()
  await expectDraftSaved(page)
  await expect(page.getByTestId('optional-roleplay-fishing_tale')).toHaveCount(0)
})
