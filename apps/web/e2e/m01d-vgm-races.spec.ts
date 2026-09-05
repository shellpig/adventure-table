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
  await expect.poll(() => currentDraftRevision(page)).toBeGreaterThan(previousRevision)
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
  let option = listbox
    .getByRole('option')
    .filter({ has: page.getByText(value, { exact: true }) })

  // Same-name entries can coexist across content packs. These M01-D scenarios
  // intentionally use the SRD Acolyte baseline, so disambiguate it exactly the
  // same way as the established P1 browser regressions.
  if ((await option.count()) > 1) {
    const srdOption = option.filter({
      has: page.getByText('System Reference Document 5.1', { exact: true }),
    })
    if ((await srdOption.count()) === 1) option = srdOption
  }

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

async function startDraft(page: Page, name: string, level: number) {
  await page.goto('/characters')
  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)
  await page.getByLabel('Character name').fill(name)
  await page.getByLabel('Target character level').fill(String(level))
  await page.getByRole('button', { name: 'Save Basic Details' }).click()
  await expect(page.getByRole('heading', { name }).first()).toBeVisible()
}

async function saveDefaultAbilities(page: Page) {
  await page.getByTestId('builder-step-abilities').click()
  await page.getByRole('button', { name: 'Save Ability Scores' }).click()
  await expectDraftSaved(page)
}

async function chooseAcolyteLanguages(page: Page) {
  const languages = page.locator('.builder-choice').filter({ hasText: 'Acolyte — Languages' })
  await chooseIn(languages, 'Dwarvish')
  await chooseIn(languages, 'Elvish')
}

async function chooseBarbarianLevelOne(page: Page) {
  await chooseSearchable(page, 'Level 1 class', 'Barbarian')
  const skills = page.getByTestId('level-node-1').locator('.progression-choice')
  await chooseIn(skills, 'Skill: Animal Handling')
  await chooseIn(skills, 'Skill: Athletics')
}

async function chooseBarbarianEquipment(page: Page) {
  await page.getByTestId('builder-step-equipment').click()
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
  await chooseSearchable(page, 'Acolyte — Starting Equipment', 'Amulet')
}

async function confirmCreateAndReload(page: Page, name: string) {
  await page.getByTestId('builder-step-review').click()
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

test('M01-D creates and reloads a Goblin character', async ({ page }) => {
  test.slow()
  await startDraft(page, 'M01-D Goblin Hero', 1)
  await page.getByTestId('builder-step-origin').click()
  await chooseSearchable(page, 'Race', 'Goblin')
  await chooseSearchable(page, 'Background', 'Acolyte')
  await saveDefaultAbilities(page)
  await chooseAcolyteLanguages(page)
  await page.getByTestId('builder-step-class').click()
  await chooseBarbarianLevelOne(page)
  await chooseBarbarianEquipment(page)
  await confirmCreateAndReload(page, 'M01-D Goblin Hero')
  await expect(page.getByText('Fury of the Small', { exact: true })).toBeVisible()
  await expect(page.getByText('Nimble Escape', { exact: true })).toBeVisible()
})

test('M01-D creates a Hobgoblin with two martial weapon choices', async ({ page }) => {
  test.slow()
  await startDraft(page, 'M01-D Hobgoblin Hero', 1)
  await page.getByTestId('builder-step-origin').click()
  await chooseSearchable(page, 'Race', 'Hobgoblin')
  await chooseSearchable(page, 'Background', 'Acolyte')
  await saveDefaultAbilities(page)
  await chooseAcolyteLanguages(page)

  const martialTraining = page
    .locator('.builder-choice')
    .filter({ hasText: 'Hobgoblin — Proficiencies' })
  await chooseIn(martialTraining, 'Longswords')
  await chooseIn(martialTraining, 'Longbows')
  await expect(martialTraining).toContainText('2 / 2')

  await page.getByTestId('builder-step-class').click()
  await chooseBarbarianLevelOne(page)
  await chooseBarbarianEquipment(page)
  await confirmCreateAndReload(page, 'M01-D Hobgoblin Hero')
  await expect(page.getByText('Saving Face', { exact: true })).toBeVisible()
})

test('M01-D requires an Aasimar subrace and persists its level-one grants', async ({ page }) => {
  test.slow()
  await startDraft(page, 'M01-D Protector Hero', 1)
  await page.getByTestId('builder-step-origin').click()
  await chooseSearchable(page, 'Race', 'Aasimar')
  await expect(page.getByText(/requires a subrace selection/i)).toBeVisible()
  await chooseSearchable(page, 'Subrace', 'Protector Aasimar')
  await chooseSearchable(page, 'Background', 'Acolyte')
  await saveDefaultAbilities(page)
  await chooseAcolyteLanguages(page)
  await page.getByTestId('builder-step-class').click()
  await chooseBarbarianLevelOne(page)
  await chooseBarbarianEquipment(page)
  await confirmCreateAndReload(page, 'M01-D Protector Hero')
  await expect(page.getByText('Healing Hands', { exact: true })).toBeVisible()
  await expect(page.getByText('Light Bearer', { exact: true })).toBeVisible()
  await expect(page.getByText('Radiant Soul', { exact: true })).toHaveCount(0)
})

test('M01-D Aasimar level 2 to 3 adds the level-gated transformation in Build v2', async ({ page }) => {
  test.slow()
  await startDraft(page, 'M01-D Threshold Hero', 2)
  await page.getByTestId('builder-step-origin').click()
  await chooseSearchable(page, 'Race', 'Aasimar')
  await chooseSearchable(page, 'Subrace', 'Protector Aasimar')
  await chooseSearchable(page, 'Background', 'Acolyte')
  await saveDefaultAbilities(page)
  await chooseAcolyteLanguages(page)

  await page.getByTestId('builder-step-class').click()
  await chooseBarbarianLevelOne(page)
  await chooseSearchable(page, 'Level 2 class', 'Barbarian')
  await chooseBarbarianEquipment(page)
  await confirmCreateAndReload(page, 'M01-D Threshold Hero')
  await expect(page.getByText('Healing Hands', { exact: true })).toBeVisible()
  await expect(page.getByText('Radiant Soul', { exact: true })).toHaveCount(0)

  await page.goto('/characters')
  const card = page.locator('.workshop-card').filter({ hasText: 'M01-D Threshold Hero' })
  await card.getByRole('button', { name: 'Level Up' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)
  await page.getByTestId('builder-step-class').click()
  await chooseSearchable(page, 'Level 3 class', 'Barbarian')
  await chooseSearchable(page, /Barbarian subclass/, 'Berserker')
  await page.getByTestId('builder-step-review').click()
  const confirm = page.getByRole('button', { name: 'Confirm Level Up' })
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(page.getByText('Build v2')).toBeVisible()
  await expect(page.getByText('Radiant Soul', { exact: true })).toBeVisible()

  await page.reload()
  await expect(page.getByText('Build v2')).toBeVisible()
  await expect(page.getByText('Radiant Soul', { exact: true })).toBeVisible()
})
