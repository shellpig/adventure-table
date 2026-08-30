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
  await expect(page.locator('.builder-save-state span')).toHaveText(`Draft revision ${previousRevision + 1}`)
  await expectDraftSaved(page)
}

async function clickAndWaitForSave(page: Page, button: Locator) {
  await expectDraftSaved(page)
  const revision = await currentDraftRevision(page)
  await button.click()
  await waitForDraftRevision(page, revision)
}

async function chooseOption(page: Page, input: Locator, value: string) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  const revision = await currentDraftRevision(page)
  await input.fill(value)

  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error(`Combobox for "${value}" has no aria-controls listbox`)
  const listbox = page.locator(`[id="${listboxId}"]`)
  const option = listbox.getByRole('option').filter({ has: page.getByText(value, { exact: true }) })

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

async function chooseFirstEnabled(page: Page, input: Locator) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  const revision = await currentDraftRevision(page)
  await input.focus()

  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error('Combobox has no aria-controls listbox')
  const listbox = page.locator(`[id="${listboxId}"]`)
  await expect(listbox).toBeVisible()

  const option = listbox.locator('[role="option"]:not([disabled])').first()
  await expect(option).toBeVisible()
  await option.click()
  await waitForDraftRevision(page, revision)
}

async function fillEmptyComboboxes(page: Page, container: Locator) {
  for (let pass = 0; pass < 96; pass += 1) {
    const inputs = container.getByRole('combobox')
    const count = await inputs.count()
    let changed = false

    for (let index = 0; index < count; index += 1) {
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

async function fillExactSpellBuckets(page: Page) {
  for (let pass = 0; pass < 96; pass += 1) {
    const buckets = page.locator('.spell-bucket')
    const count = await buckets.count()
    let changed = false

    for (let index = 0; index < count; index += 1) {
      const bucket = buckets.nth(index)
      const counter = (await bucket.locator('.spell-count').innerText()).trim()
      if (counter.includes('max')) continue

      const match = counter.match(/^(\d+)\s*\/\s*(\d+)$/)
      if (!match) throw new Error(`Cannot parse exact spell counter: ${counter}`)
      const selected = Number(match[1])
      const target = Number(match[2])
      if (selected >= target) continue

      const input = bucket.getByRole('combobox')
      await expect(input).toBeEnabled()
      await chooseFirstEnabled(page, input)
      changed = true
      break
    }

    if (!changed) return
  }

  throw new Error('Required spell selections did not converge')
}


test('P1-H creates and confirms a direct Fighter 5 / Wizard 5 character end to end', async ({ page, request }, testInfo) => {
  test.slow()

  await page.goto('/characters')
  await page.screenshot({ path: testInfo.outputPath('p1-h-workshop-desktop.png'), fullPage: true })
  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)
  await expectDraftSaved(page)

  await page.getByLabel('Character name').fill('P1-H High-Level Hero')
  await page.getByLabel('Target character level').fill('10')
  await clickAndWaitForSave(page, page.getByRole('button', { name: 'Save Basic Details' }))

  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Race', 'Human')
  await chooseSearchable(page, 'Background', 'Acolyte')

  await page.getByRole('button', { name: /Abilities/ }).click()
  await clickAndWaitForSave(page, page.getByRole('button', { name: 'Save Ability Scores' }))
  await chooseSearchable(page, 'Human — Languages', 'Dwarvish')
  const backgroundLanguages = page
    .locator('.builder-choice')
    .filter({ hasText: 'Acolyte — Languages' })
  await chooseIn(backgroundLanguages, 'Celestial')
  await chooseIn(backgroundLanguages, 'Draconic')
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  await page.getByRole('button', { name: /Class/ }).click()
  for (let level = 1; level <= 5; level += 1) {
    await chooseSearchable(page, `Level ${level} class`, 'Fighter')
  }
  for (let level = 6; level <= 10; level += 1) {
    await chooseSearchable(page, `Level ${level} class`, 'Wizard')
  }

  await fillEmptyComboboxes(page, page.locator('.level-rail'))
  await expect(page.getByText('Fighter 5 / Wizard 5', { exact: true }).last()).toBeVisible()
  await expect(page.getByText('10 / 10', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('p1-h-level-rail-desktop.png'), fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: testInfo.outputPath('p1-h-builder-mobile.png'), fullPage: true })
  await page.setViewportSize({ width: 1280, height: 720 })

  const draftUrl = page.url()
  const draftMatch = draftUrl.match(/\/character-builder\/([0-9a-f-]{36})$/)
  if (!draftMatch) throw new Error(`Cannot parse draft id from ${draftUrl}`)
  const draftId = draftMatch[1]

  await page.reload()
  await expect(page).toHaveURL(draftUrl)
  await expectDraftSaved(page)
  await page.getByRole('button', { name: /Class/ }).click()
  await expect(page.getByText('Fighter 5 / Wizard 5', { exact: true }).last()).toBeVisible()

  await page.getByRole('button', { name: /Spellcasting/ }).click()
  await expect(page.getByRole('heading', { name: 'Spellcasting & resources' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Wizard 5' })).toBeVisible()
  await fillExactSpellBuckets(page)
  await page.screenshot({ path: testInfo.outputPath('p1-h-spellcasting.png'), fullPage: true })

  const preparedSelector = page.getByRole('combobox', { name: 'Add initial prepared spells' })
  if (await preparedSelector.isEnabled()) {
    await preparedSelector.focus()
    const listboxId = await preparedSelector.getAttribute('aria-controls')
    if (listboxId) {
      await expect(page.locator(`[id="${listboxId}"]`)).toBeVisible()
      await page.screenshot({ path: testInfo.outputPath('p1-h-spell-selector.png'), fullPage: true })
      await page.keyboard.press('Escape')
    }
  }

  await page.getByRole('button', { name: /Review/ }).click()
  await expect(page.getByRole('heading', { name: 'Equipment & final review' })).toBeVisible()
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  const reviewResponse = await request.get(`/api/character-builder/drafts/${draftId}/review`)
  expect(reviewResponse.ok()).toBeTruthy()
  const review = await reviewResponse.json()
  const blockingIssues = review.issues.filter(
    (issue: { severity: string }) => issue.severity === 'blocking_error',
  )
  expect(blockingIssues, JSON.stringify(review.issues, null, 2)).toEqual([])
  expect(review.can_confirm, JSON.stringify(review.issues, null, 2)).toBeTruthy()
  await expect(
    page.locator('.builder-form .summary-validation').getByText('0 blocking', { exact: true }),
  ).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('p1-h-review.png'), fullPage: true })

  const confirm = page.getByRole('button', { name: 'Confirm & Create Character' })
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(page).toHaveURL(/\/characters\/[0-9a-f-]{36}$/)
  await expect(page.getByRole('heading', { name: 'P1-H High-Level Hero' })).toBeVisible()
  await expect(page.getByText('Build v1')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('p1-h-character-sheet.png'), fullPage: true })

  const match = page.url().match(/\/characters\/([0-9a-f-]{36})$/)
  if (!match) throw new Error(`Cannot parse character id from ${page.url()}`)
  const characterId = match[1]

  const response = await request.get(`/api/characters/${characterId}`)
  expect(response.ok()).toBeTruthy()
  const character = await response.json()

  expect(character.version_no).toBe(1)
  expect(character.build.character_level).toBe(10)
  expect(character.build.class_progression).toEqual([
    ...Array(5).fill('srd5.1:class:fighter'),
    ...Array(5).fill('srd5.1:class:wizard'),
  ])
  expect(character.build.subclasses).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        class_ref: 'srd5.1:class:fighter',
        subclass_ref: 'srd5.1:subclass:champion',
      }),
      expect.objectContaining({
        class_ref: 'srd5.1:class:wizard',
        subclass_ref: 'srd5.1:subclass:evocation',
      }),
    ]),
  )
  expect(character.build.spellcasting_profiles).toHaveLength(1)
  expect(character.build.spell_access_entries.length).toBeGreaterThan(0)
  expect(character.build.starting_equipment.length).toBeGreaterThan(0)
  expect(character.state.inventory_state).toHaveLength(character.build.starting_equipment.length)

  await page.reload()
  await expect(page.getByRole('heading', { name: 'P1-H High-Level Hero' })).toBeVisible()
  await expect(page.getByText('Build v1')).toBeVisible()
})
