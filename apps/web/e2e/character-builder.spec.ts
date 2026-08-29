import { expect, test } from '@playwright/test'


test('P1-B workshop creates and resumes a server-backed character draft', async ({ page }) => {
  await page.goto('/characters')
  await expect(page.getByRole('heading', { name: 'Character Workshop' })).toBeVisible()
  await expect(page.getByText('Fighter 5 / Wizard 5', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)

  await page.getByLabel('Character name').fill('P1-B Browser Hero')
  await page.getByLabel('Target character level').fill('1')
  await page.getByLabel('Appearance').fill('A weathered traveler')
  await page.getByRole('button', { name: 'Save Basic Details' }).click()
  await expect(page.getByText('P1-B Browser Hero').first()).toBeVisible()

  await page.getByRole('button', { name: /Origin/ }).click()
  const race = page.getByRole('combobox', { name: 'Race' })
  await race.fill('Human')
  await race.press('ArrowDown')
  await race.press('Enter')
  await expect(page.getByText('Human', { exact: true }).last()).toBeVisible()

  const background = page.getByRole('combobox', { name: 'Background' })
  await background.fill('Acolyte')
  await background.press('ArrowDown')
  await background.press('Enter')
  await expect(page.getByText('Acolyte', { exact: true }).last()).toBeVisible()

  await page.getByRole('button', { name: /Abilities/ }).click()
  await expect(page.getByRole('tab', { name: 'Standard Array' })).toHaveAttribute('aria-selected', 'true')
  await page.getByRole('button', { name: 'Save Ability Scores' }).click()
  await expect(page.locator('.summary-abilities')).toContainText('16')

  const humanLanguage = page.locator('.builder-choice').filter({ hasText: 'Human — Languages' })
  const humanLanguageInput = humanLanguage.getByRole('combobox', { name: 'Add selection' })
  await humanLanguageInput.fill('Dwarvish')
  await humanLanguageInput.press('ArrowDown')
  await humanLanguageInput.press('Enter')

  const backgroundLanguages = page
    .locator('.builder-choice')
    .filter({ hasText: 'Acolyte — Languages' })
  const addBackgroundLanguage = backgroundLanguages.getByRole('combobox', { name: 'Add selection' })
  await addBackgroundLanguage.fill('Celestial')
  await addBackgroundLanguage.press('ArrowDown')
  await addBackgroundLanguage.press('Enter')
  await addBackgroundLanguage.fill('Draconic')
  await addBackgroundLanguage.press('ArrowDown')
  await addBackgroundLanguage.press('Enter')
  await expect(backgroundLanguages).toContainText('2 / 2')

  await page.getByRole('tab', { name: 'Point Buy' }).click()
  await expect(page.getByText(/Point Buy · 27 \/ 27 points used/)).toBeVisible()
  await page.getByRole('button', { name: 'Save Ability Scores' }).click()
  await page.getByRole('tab', { name: 'Manual Input' }).click()
  await expect(page.locator('.builder-abilities input')).toHaveCount(6)
  await page.getByRole('button', { name: 'Save Ability Scores' }).click()

  const url = page.url()
  await page.reload()
  await expect(page).toHaveURL(url)
  await expect(page.getByRole('heading', { name: 'P1-B Browser Hero' }).first()).toBeVisible()
  await expect(page.getByText('Human', { exact: true }).last()).toBeVisible()
  await expect(page.getByText('Acolyte', { exact: true }).last()).toBeVisible()
  await expect(page.getByText('Class progression is intentionally locked until P1-C')).toBeVisible()

  await page.goto('/characters')
  await expect(page.getByRole('heading', { name: 'Creation Drafts' })).toBeVisible()
  await expect(page.getByText('P1-B Browser Hero')).toBeVisible()
})
