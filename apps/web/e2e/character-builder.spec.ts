import { expect, test, type Page } from '@playwright/test'


async function chooseSearchable(page: Page, label: string | RegExp, value: string) {
  const input = page.getByRole('combobox', { name: label })
  await input.fill(value)
  await input.press('ArrowDown')
  await input.press('Enter')
}

async function chooseIn(container: ReturnType<Page['locator']>, value: string) {
  const input = container.getByRole('combobox', { name: 'Add selection' })
  await input.fill(value)
  await input.press('ArrowDown')
  await input.press('Enter')
}


test('P1-C creates and resumes an ordered Fighter 5 / Wizard 5 rail', async ({ page }) => {
  await page.goto('/characters')
  await expect(page.getByRole('heading', { name: 'Character Workshop' })).toBeVisible()
  await expect(page.getByText('Fighter 5 / Wizard 5', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)

  await page.getByLabel('Character name').fill('P1-C Browser Hero')
  await page.getByLabel('Target character level').fill('10')
  await page.getByLabel('Appearance').fill('A weathered traveler')
  await page.getByRole('button', { name: 'Save Basic Details' }).click()
  await expect(page.getByText('P1-C Browser Hero').first()).toBeVisible()

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
  await chooseIn(fighterStartingSkills, 'Acrobatics')
  await chooseIn(fighterStartingSkills, 'Athletics')
  await expect(fighterStartingSkills).toContainText('2 / 2')

  await chooseSearchable(page, 'Level 2 class', 'Fighter')
  const level2 = page.getByTestId('level-node-2')
  await level2.getByLabel('HP method').selectOption('manual_rolled')
  await level2.getByLabel('Base HP gain').fill('7')

  await chooseSearchable(page, 'Level 3 class', 'Fighter')
  await chooseSearchable(page, /Fighter subclass/, 'Champion')
  await chooseSearchable(page, 'Level 4 class', 'Fighter')
  await chooseSearchable(page, 'Level 5 class', 'Fighter')

  // Wizard is legal here only because the Human +1 resolves INT 12 -> 13.
  await chooseSearchable(page, 'Level 6 class', 'Wizard')
  await chooseSearchable(page, 'Level 7 class', 'Wizard')
  await chooseSearchable(page, /Wizard subclass/, 'Evocation')
  await chooseSearchable(page, 'Level 8 class', 'Wizard')
  await chooseSearchable(page, 'Level 9 class', 'Wizard')
  await chooseSearchable(page, 'Level 10 class', 'Wizard')

  await expect(page.getByText('Fighter 5 / Wizard 5', { exact: true }).last()).toBeVisible()
  await expect(page.getByText('10 / 10', { exact: true })).toBeVisible()
  await expect(page.getByText('0 blocking')).toHaveCount(0)
  await expect(page.getByText(/builder phase not complete/i)).toBeVisible()

  const url = page.url()
  await page.reload()
  await expect(page).toHaveURL(url)
  await expect(page.getByRole('heading', { name: 'P1-C Browser Hero' }).first()).toBeVisible()
  await page.getByRole('button', { name: /Class/ }).click()
  await expect(page.getByText('Fighter 5 / Wizard 5', { exact: true }).last()).toBeVisible()
  await expect(page.getByTestId('level-node-3')).toContainText('Champion')
  await expect(page.getByTestId('level-node-7')).toContainText('Evocation')
  await expect(page.getByTestId('level-node-2').getByLabel('HP method')).toHaveValue('manual_rolled')
  await expect(page.getByTestId('level-node-2').getByLabel('Base HP gain')).toHaveValue('7')
  await expect(page.getByTestId('level-node-6')).toContainText('Multiclass entry')

  await page.goto('/characters')
  await expect(page.getByRole('heading', { name: 'Creation Drafts' })).toBeVisible()
  await expect(page.getByText('P1-C Browser Hero')).toBeVisible()
})
