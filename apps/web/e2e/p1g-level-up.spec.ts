import { expect, test, type Locator, type Page } from '@playwright/test'


async function expectDraftSaved(page: Page) {
  await expect(page.getByText('Saved on server')).toBeVisible()
}

async function chooseOption(page: Page, input: Locator, value: string) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  await input.fill(value)

  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error(`Combobox for "${value}" has no aria-controls listbox`)
  const listbox = page.locator(`[id="${listboxId}"]`)
  let option = listbox.getByRole('option').filter({ has: page.getByText(value, { exact: true }) })

  if ((await option.count()) > 1) {
    const srdOption = option.filter({
      has: page.getByText('System Reference Document 5.1', { exact: true }),
    })
    if ((await srdOption.count()) === 1) option = srdOption
  }

  await expect(option).toHaveCount(1)
  await option.click()
  await expect(listbox).toBeHidden()
  await expectDraftSaved(page)
}

async function chooseSearchable(page: Page, label: string | RegExp, value: string) {
  await chooseOption(page, page.getByRole('combobox', { name: label }), value)
}

async function chooseIn(container: Locator, value: string) {
  await chooseOption(
    container.page(),
    container.getByRole('combobox', { name: 'Add selection' }),
    value,
  )
}

async function createBarbarianOne(page: Page) {
  await page.goto('/characters')
  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)

  await page.getByLabel('Character name').fill('P1-G Browser Hero')
  await page.getByLabel('Target character level').fill('1')
  await page.getByRole('button', { name: 'Save Basic Details' }).click()

  await page.getByTestId('builder-step-origin').click()
  await chooseSearchable(page, 'Race', 'Human')
  await chooseSearchable(page, 'Background', 'Acolyte')

  await page.getByTestId('builder-step-abilities').click()
  await page.getByRole('button', { name: 'Save Ability Scores' }).click()
  await chooseSearchable(page, 'Human — Languages', 'Dwarvish')
  const backgroundLanguages = page
    .locator('.builder-choice')
    .filter({ hasText: 'Acolyte — Languages' })
  await chooseIn(backgroundLanguages, 'Celestial')
  await chooseIn(backgroundLanguages, 'Draconic')

  await page.getByTestId('builder-step-class').click()
  await chooseSearchable(page, 'Level 1 class', 'Barbarian')
  const startingSkills = page.getByTestId('level-node-1').locator('.progression-choice')
  await chooseIn(startingSkills, 'Skill: Animal Handling')
  await chooseIn(startingSkills, 'Skill: Athletics')

  await page.getByTestId('builder-step-equipment').click()
  await expect(page.getByRole('heading', { name: 'Equipment & roleplay' })).toBeVisible()
  await chooseSearchable(page, /\(a\) a greataxe or \(b\) any martial melee weapon/, 'Greataxe')
  await chooseSearchable(page, /\(a\) two handaxes or \(b\) any simple weapon/, '2 × Handaxe')
  await chooseSearchable(page, 'Acolyte — Starting Equipment', 'Amulet')

  await page.getByTestId('builder-step-review').click()
  const confirm = page.getByRole('button', { name: 'Confirm & Create Character' })
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(page).toHaveURL(/\/characters\/[0-9a-f-]{36}$/)
}


test('P1-G levels up through the real backend and preserves live Current State', async ({ page, request }, testInfo) => {
  test.slow()
  await createBarbarianOne(page)

  const match = page.url().match(/\/characters\/([0-9a-f-]{36})$/)
  if (!match) throw new Error(`Cannot parse character id from ${page.url()}`)
  const characterId = match[1]

  const beforeResponse = await request.get(`/api/characters/${characterId}`)
  expect(beforeResponse.ok()).toBeTruthy()
  const before = await beforeResponse.json()
  expect(before.version_no).toBe(1)
  expect(before.state.current_hp).toBe(14)
  const originalInventory = before.state.inventory_state

  const patchResponse = await request.patch(`/api/characters/${characterId}/state`, {
    data: {
      current_hp: 9,
      temporary_hp: 3,
      hit_dice_state: { d12: 0 },
      inventory_state: originalInventory,
    },
  })
  expect(patchResponse.ok()).toBeTruthy()

  await page.goto('/characters')
  const card = page.locator('.workshop-card').filter({ hasText: 'P1-G Browser Hero' })
  await expect(card).toHaveCount(1)
  await card.getByRole('button', { name: 'Level Up' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)

  await page.getByTestId('builder-step-class').click()
  await expect(page.getByTestId('level-node-1')).toContainText('Barbarian 1')
  await chooseSearchable(page, 'Level 2 class', 'Barbarian')

  await page.getByTestId('builder-step-review').click()
  await expect(page.getByRole('heading', { name: 'Level Up review' })).toBeVisible()
  await expect(page.getByText('Current State Reconciliation')).toBeVisible()
  await expect(page.getByText('Existing damage delta is preserved')).toBeVisible()
  await expect(page.getByText('18', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('No blocking issues. Confirm will append one immutable Build Version and reconcile Current State in one transaction.')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('p1-h-level-up-reconciliation.png'), fullPage: true })

  const confirm = page.getByRole('button', { name: 'Confirm Level Up' })
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(page).toHaveURL(new RegExp(`/characters/${characterId}$`))
  await expect(page.getByText('Build v2')).toBeVisible()
  await expect(page.getByTestId('header-hp')).toHaveText('18')

  const afterResponse = await request.get(`/api/characters/${characterId}`)
  expect(afterResponse.ok()).toBeTruthy()
  const after = await afterResponse.json()
  expect(after.version_no).toBe(2)
  expect(after.state.current_hp).toBe(18)
  expect(after.state.temporary_hp).toBe(3)
  expect(after.state.hit_dice_state.d12).toBe(1)
  expect(after.state.inventory_state).toEqual(originalInventory)

  await page.goto(`/characters/${characterId}/versions`)
  await expect(page.getByRole('heading', { name: 'Character Versions' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Version 1' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Version 2' })).toBeVisible()
  await expect(page.getByText('Level Up', { exact: true })).toBeVisible()
  await expect(page.getByText('CURRENT', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('p1-h-version-history.png'), fullPage: true })
})