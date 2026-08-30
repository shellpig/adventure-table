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
  const option = listbox.getByRole('option').filter({ has: page.getByText(value, { exact: true }) })

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


test('P1-F resolves starting equipment, reviews and creates Version 1 from the browser', async ({ page }) => {
  test.slow()

  await page.goto('/characters')
  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)

  await page.getByLabel('Character name').fill('P1-F Browser Hero')
  await page.getByLabel('Target character level').fill('1')
  await page.getByRole('button', { name: 'Save Basic Details' }).click()
  await expect(page.getByRole('heading', { name: 'P1-F Browser Hero' }).first()).toBeVisible()

  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Race', 'Human')
  await chooseSearchable(page, 'Background', 'Acolyte')

  await page.getByRole('button', { name: /Abilities/ }).click()
  await page.getByRole('button', { name: 'Save Ability Scores' }).click()
  await chooseSearchable(page, 'Human — Languages', 'Dwarvish')
  const backgroundLanguages = page
    .locator('.builder-choice')
    .filter({ hasText: 'Acolyte — Languages' })
  await chooseIn(backgroundLanguages, 'Celestial')
  await chooseIn(backgroundLanguages, 'Draconic')

  await page.getByRole('button', { name: /Class/ }).click()
  await chooseSearchable(page, 'Level 1 class', 'Barbarian')
  const startingSkills = page.getByTestId('level-node-1').locator('.progression-choice')
  await chooseIn(startingSkills, 'Skill: Animal Handling')
  await chooseIn(startingSkills, 'Skill: Athletics')

  await page.getByRole('button', { name: /Review/ }).click()
  await expect(page.getByRole('heading', { name: 'Equipment & final review' })).toBeVisible()

  await chooseSearchable(page, /\(a\) a greataxe or \(b\) any martial melee weapon/, 'Greataxe')
  await chooseSearchable(page, /\(a\) two handaxes or \(b\) any simple weapon/, '2 × Handaxe')
  await chooseSearchable(page, 'Acolyte — Starting Equipment', 'Amulet')

  await expect(page.getByText('No blocking issues. Confirm will create Character, immutable Version 1 and Current State in one transaction.')).toBeVisible()
  const confirm = page.getByRole('button', { name: 'Confirm & Create Character' })
  await expect(confirm).toBeEnabled()
  await confirm.click()

  await expect(page).toHaveURL(/\/characters\/[0-9a-f-]{36}$/)
  await expect(page.getByRole('heading', { name: 'P1-F Browser Hero' })).toBeVisible()
  await expect(page.getByText('Build v1')).toBeVisible()
  await expect(page.getByTestId('header-hp')).toHaveText('14')

  await page.getByRole('tab', { name: /物品欄/ }).click()
  await expect(page.getByText('Greataxe', { exact: true })).toBeVisible()
  await expect(page.getByText('Handaxe', { exact: true })).toBeVisible()
  await expect(page.getByText('Javelin', { exact: true })).toBeVisible()
})
