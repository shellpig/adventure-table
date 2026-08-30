import { expect, test, type Locator, type Page } from '@playwright/test'


async function currentDraftRevision(page: Page) {
  const text = (await page.locator('.builder-save-state span').innerText()).trim()
  const match = text.match(/^Draft revision (\d+)$/)
  if (!match) throw new Error(`Cannot parse draft revision from: ${text}`)
  return Number(match[1])
}

async function expectDraftSaved(page: Page) {
  await expect(page.getByText('Saved on server')).toBeVisible()
}

async function waitForDraftRevision(page: Page, previousRevision: number) {
  await expect(page.locator('.builder-save-state span')).toHaveText(
    `Draft revision ${previousRevision + 1}`,
  )
  await expectDraftSaved(page)
}

async function chooseOption(page: Page, input: Locator, value: string) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  const revision = await currentDraftRevision(page)
  await input.fill(value)

  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error(`Combobox for "${value}" has no aria-controls listbox`)
  const listbox = page.locator(`[id="${listboxId}"]`)
  const option = listbox
    .getByRole('option')
    .filter({ has: page.getByText(value, { exact: true }) })

  await expect(option).toHaveCount(1)
  await option.click()
  await expect(listbox).toBeHidden()
  await waitForDraftRevision(page, revision)
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

async function startLevelOneDraft(page: Page, name: string) {
  await page.goto('/characters')
  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)

  await page.getByLabel('Character name').fill(name)
  await page.getByLabel('Target character level').fill('1')
  await page.getByRole('button', { name: 'Save Basic Details' }).click()
  await expect(page.getByRole('heading', { name }).first()).toBeVisible()
}

async function saveDefaultAbilities(page: Page) {
  await page.getByRole('button', { name: /Abilities/ }).click()
  await page.getByRole('button', { name: 'Save Ability Scores' }).click()
  await expectDraftSaved(page)
}

async function chooseBarbarian(page: Page, skills: [string, string]) {
  await page.getByRole('button', { name: /Class/ }).click()
  await chooseSearchable(page, 'Level 1 class', 'Barbarian')
  const startingSkills = page.getByTestId('level-node-1').locator('.progression-choice')
  await chooseIn(startingSkills, skills[0])
  await chooseIn(startingSkills, skills[1])
}

async function chooseBarbarianEquipment(page: Page) {
  await page.getByRole('button', { name: /Equipment/ }).click()
  await expect(page.getByRole('heading', { name: 'Equipment & roleplay' })).toBeVisible()
  await chooseSearchable(
    page,
    /\(a\) a greataxe or \(b\) any martial melee weapon/,
    'Greataxe',
  )
  await chooseSearchable(
    page,
    /\(a\) two handaxes or \(b\) any simple weapon/,
    '2 × Handaxe',
  )
}

async function confirmAndReload(page: Page, name: string) {
  await page.getByRole('button', { name: /Review/ }).click()
  await expect(page.getByRole('heading', { name: 'Build snapshot & final review' })).toBeVisible()
  await expect(
    page.getByText(
      'No blocking issues. Confirm will create Character, immutable Version 1 and Current State in one transaction.',
    ),
  ).toBeVisible()

  const confirm = page.getByRole('button', { name: 'Confirm & Create Character' })
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(page).toHaveURL(/\/characters\/[0-9a-f-]{36}$/)
  await expect(page.getByRole('heading', { name })).toBeVisible()
  await expect(page.getByText('Build v1')).toBeVisible()

  const url = page.url()
  await page.reload()
  await expect(page).toHaveURL(url)
  await expect(page.getByRole('heading', { name })).toBeVisible()
  await expect(page.getByText('Build v1')).toBeVisible()
}


test('M01-C creates and reloads an SCAG background character through the real browser', async ({ page }) => {
  test.slow()
  await startLevelOneDraft(page, 'M01-C SCAG Hero')

  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Race', 'Human')
  await chooseSearchable(page, 'Background', 'City Watch')

  await saveDefaultAbilities(page)
  await chooseSearchable(page, 'Human — Languages', 'Dwarvish')
  const backgroundLanguages = page
    .locator('.builder-choice')
    .filter({ hasText: 'City Watch — Languages' })
  await chooseIn(backgroundLanguages, 'Celestial')
  await chooseIn(backgroundLanguages, 'Draconic')

  await chooseBarbarian(page, ['Skill: Animal Handling', 'Skill: Perception'])
  await chooseBarbarianEquipment(page)
  await confirmAndReload(page, 'M01-C SCAG Hero')
})


test('M01-C creates and reloads a GoS background character with a PHB subrace', async ({ page }) => {
  test.slow()
  await startLevelOneDraft(page, 'M01-C GoS Hero')

  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Race', 'Elf')
  await chooseSearchable(page, 'Subrace', 'Wood Elf')
  await chooseSearchable(page, 'Background', 'Fisher')

  await saveDefaultAbilities(page)
  const backgroundLanguages = page
    .locator('.builder-choice')
    .filter({ hasText: 'Fisher — Languages' })
  await chooseIn(backgroundLanguages, 'Dwarvish')

  await chooseBarbarian(page, ['Skill: Animal Handling', 'Skill: Athletics'])
  await chooseBarbarianEquipment(page)
  await confirmAndReload(page, 'M01-C GoS Hero')
})
