import { expect, test, type Locator, type Page } from '@playwright/test'


// Every builder selection starts an async draft save, and the page disables its
// comboboxes while that save is in flight. Settling on both sides of the
// interaction keeps a fast sequence from typing into a control that is about to
// be disabled, and keeps a keystroke from silently landing on an empty option
// list while the server-generated choices are still being refetched.
async function expectDraftSaved(page: Page) {
  await expect(page.getByText('Saved on server')).toBeVisible()
}

// Click the option whose label matches exactly. When M01-B introduces the same
// display name from another content pack, preserve this older P1 regression as
// an SRD baseline by choosing the SRD row explicitly.
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


test('P1-D preserves an ordered Fighter 5 / Wizard 5 rail with ASI and feat choices', async ({ page }) => {
  test.slow()

  await page.goto('/characters')
  await expect(page.getByRole('heading', { name: 'Character Workshop' })).toBeVisible()
  await expect(page.getByText('Fighter 5 / Wizard 5', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)

  await page.getByLabel('Character name').fill('P1-D Browser Hero')
  await page.getByLabel('Target character level').fill('10')
  await page.getByLabel('Appearance').fill('A weathered traveler')
  await page.getByRole('button', { name: 'Save Basic Details' }).click()
  await expect(page.getByText('P1-D Browser Hero').first()).toBeVisible()

  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Race', 'Human')
  await expect(page.getByText('Human', { exact: true }).last()).toBeVisible()
  await chooseSearchable(page, 'Background', 'Acolyte')
  await expect(page.getByText('Acolyte', { exact: true }).last()).toBeVisible()

  await page.getByRole('button', { name: /Abilities/ }).click()
  await expect(page.getByRole('tab', { name: 'Standard Array' })).toHaveAttribute('aria-selected', 'true')
  await page.getByRole('button', { name: 'Save Ability Scores' }).click()
  await expect(page.locator('.summary-abilities')).toContainText('16')

  await chooseSearchable(page, 'Human — Languages', 'Dwarvish')
  const backgroundLanguages = page
    .locator('.builder-choice')
    .filter({ hasText: 'Acolyte — Languages' })
  await chooseIn(backgroundLanguages, 'Celestial')
  await expect(backgroundLanguages).toContainText('1 / 2')
  await chooseIn(backgroundLanguages, 'Draconic')
  await expect(backgroundLanguages).toContainText('2 / 2')

  // Preserve the P1-B ability-method browser coverage while leaving the same
  // legal scores in the draft. Human +1 puts the default INT 12 at effective 13,
  // which is deliberately used below to prove multiclass availability reads the
  // effective score rather than the raw score.
  await page.getByRole('tab', { name: 'Point Buy' }).click()
  await expect(page.getByText(/Point Buy · 27 \/ 27 points used/)).toBeVisible()
  await page.getByRole('button', { name: 'Save Ability Scores' }).click()
  await page.getByRole('tab', { name: 'Manual Input' }).click()
  await expect(page.locator('.builder-abilities input')).toHaveCount(6)
  await page.getByRole('button', { name: 'Save Ability Scores' }).click()

  await page.getByRole('button', { name: /Class/ }).click()
  await expect(page.getByRole('heading', { name: 'Build the level rail' })).toBeVisible()
  await expect(page.locator('[data-testid^="level-node-"]')).toHaveCount(10)

  await chooseSearchable(page, 'Level 1 class', 'Fighter')
  const fighterStartingSkills = page
    .getByTestId('level-node-1')
    .locator('.progression-choice')
  await chooseIn(fighterStartingSkills, 'Skill: Acrobatics')
  await expect(fighterStartingSkills).toContainText('1 / 2')
  await chooseIn(fighterStartingSkills, 'Skill: Athletics')
  await expect(fighterStartingSkills).toContainText('2 / 2')

  await chooseSearchable(page, 'Level 2 class', 'Fighter')
  const level2 = page.getByTestId('level-node-2')
  await level2.getByLabel('HP method').selectOption('manual_rolled')
  await level2.getByLabel('Base HP gain').fill('7')

  await chooseSearchable(page, 'Level 3 class', 'Fighter')
  await chooseSearchable(page, /Fighter subclass/, 'Champion')
  await chooseSearchable(page, 'Level 4 class', 'Fighter')

  // Fighter class level 4 is the first ASI opportunity. The same ability may
  // legally receive both +1 selections, and the live summary must resolve it once.
  await chooseSearchable(page, 'Fighter 4 — ASI or Feat', 'Ability Score Improvement')
  const fighterAsi = page
    .getByTestId('level-node-4')
    .locator('.progression-choice')
    .filter({ hasText: 'Assign 2 ability score points' })
  await chooseIn(fighterAsi, 'STR +1')
  await expect(fighterAsi).toContainText('1 / 2')
  await chooseIn(fighterAsi, 'STR +1')
  await expect(fighterAsi).toContainText('2 / 2')
  await expect(page.locator('.summary-abilities')).toContainText('18')

  await chooseSearchable(page, 'Level 5 class', 'Fighter')

  // Wizard is legal here only because the Human +1 resolves INT 12 -> 13.
  await chooseSearchable(page, 'Level 6 class', 'Wizard')
  await chooseSearchable(page, 'Level 7 class', 'Wizard')
  await chooseSearchable(page, /Wizard subclass/, 'Evocation')
  await chooseSearchable(page, 'Level 8 class', 'Wizard')
  await chooseSearchable(page, 'Level 9 class', 'Wizard')

  // Wizard class level 4 is a second, independent ASI opportunity. Grappler is
  // legal because the effective STR already satisfies its structural prerequisite.
  await chooseSearchable(page, 'Wizard 4 — ASI or Feat', 'Grappler')
  await chooseSearchable(page, 'Level 10 class', 'Wizard')

  await expect(page.getByText('Fighter 5 / Wizard 5', { exact: true }).last()).toBeVisible()
  await expect(page.getByText('10 / 10', { exact: true })).toBeVisible()
  await expect(page.getByText('0 blocking')).toHaveCount(0)
  await expect(
    page.getByText(/P1-F adds starting equipment and final server Review/i),
  ).toBeVisible()

  const url = page.url()
  await page.reload()
  await expect(page).toHaveURL(url)
  await expect(page.getByRole('heading', { name: 'P1-D Browser Hero' }).first()).toBeVisible()
  await page.getByRole('button', { name: /Class/ }).click()
  await expect(page.getByText('Fighter 5 / Wizard 5', { exact: true }).last()).toBeVisible()
  await expect(page.getByTestId('level-node-3').getByRole('combobox', { name: /Fighter subclass/ })).toHaveValue('Champion')
  await expect(page.getByTestId('level-node-7').getByRole('combobox', { name: /Wizard subclass/ })).toHaveValue('Evocation')
  await expect(page.getByTestId('level-node-4').getByRole('combobox', { name: 'Fighter 4 — ASI or Feat' })).toHaveValue('Ability Score Improvement')
  await expect(page.getByTestId('level-node-9').getByRole('combobox', { name: 'Wizard 4 — ASI or Feat' })).toHaveValue('Grappler')
  await expect(page.getByTestId('level-node-2').getByLabel('HP method')).toHaveValue('manual_rolled')
  await expect(page.getByTestId('level-node-2').getByLabel('Base HP gain')).toHaveValue('7')
  await expect(page.getByTestId('level-node-6')).toContainText('Multiclass entry')
  await expect(page.locator('.summary-abilities')).toContainText('18')

  await page.goto('/characters')
  await expect(page.getByRole('heading', { name: 'Creation Drafts' })).toBeVisible()
  await expect(page.getByText('P1-D Browser Hero')).toBeVisible()
})
