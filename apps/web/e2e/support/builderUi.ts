// Browser-level Character Builder helpers for real-backend specs.
//
// These mirror the private helpers in m01k-phb-feats-and-spells.spec.ts so the
// M01-O journeys drive the same searchable-select / step / review surfaces the
// player uses, instead of patching drafts through the API.
import { expect, type APIRequestContext, type Locator, type Page } from '@playwright/test'

import { openCharacterWorkshop } from './room'

export const LOCALE_STORAGE_KEY = 'adventure-table.locale'

export async function expectDraftSaved(page: Page) {
  await expect(page.getByText('Saved on server')).toBeVisible()
}

export async function currentDraftRevision(page: Page) {
  const text = (await page.locator('.builder-save-state span').innerText()).trim()
  const match = text.match(/^Draft revision (\d+)$/)
  if (!match) throw new Error(`Cannot parse draft revision from: ${text}`)
  return Number(match[1])
}

export async function waitForDraftRevision(page: Page, before: number) {
  await expect.poll(() => currentDraftRevision(page)).toBeGreaterThan(before)
  await expectDraftSaved(page)
}

export async function clickAndWaitForSave(page: Page, button: Locator) {
  await expectDraftSaved(page)
  const before = await currentDraftRevision(page)
  await button.click()
  await waitForDraftRevision(page, before)
}

function listboxFor(page: Page, input: Locator) {
  return input.getAttribute('aria-controls').then((listboxId) => {
    if (!listboxId) throw new Error('Combobox has no aria-controls listbox')
    return page.locator(`[id="${listboxId}"]`)
  })
}

export async function chooseOption(page: Page, input: Locator, value: string, source?: string) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  await input.fill(value)

  const listbox = await listboxFor(page, input)
  let option = listbox.getByRole('option').filter({ has: page.getByText(value, { exact: true }) })
  if (source && (await option.count()) > 1) {
    const sourced = option.filter({ has: page.getByText(source, { exact: true }) })
    if ((await sourced.count()) === 1) option = sourced
  }
  await expect(option).toHaveCount(1)
  const before = await currentDraftRevision(page)
  await option.click()
  usedLabels.add(value)
  await expect(listbox).toBeHidden()
  await waitForDraftRevision(page, before)
}

/** Pick an option the server is expected to reject; leaves the draft untouched. */
export async function chooseRejectedOption(page: Page, input: Locator, value: string) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  await input.fill(value)
  const listbox = await listboxFor(page, input)
  const option = listbox.getByRole('option').filter({ has: page.getByText(value, { exact: true }) })
  await expect(option).toHaveCount(1)
  await option.click()
  await expect(page.locator('.error-banner')).toBeVisible()
}

export async function chooseSearchable(page: Page, label: string | RegExp, value: string, source?: string) {
  await chooseOption(page, page.getByRole('combobox', { name: label }), value, source)
}

/** Assert an option is offered but closed, and that its reason is shown to the player. */
export async function expectOptionDisabled(page: Page, input: Locator, value: string, reason?: string | RegExp) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  await input.fill(value)
  const listbox = await listboxFor(page, input)
  const option = listbox.getByRole('option').filter({ has: page.getByText(value, { exact: true }) })
  await expect(option).toHaveCount(1)
  await expect(option).toBeDisabled()
  if (reason !== undefined) await expect(option.locator('small').last()).toHaveText(reason)
  await input.fill('')
  await page.keyboard.press('Escape')
}

/** Assert a value never appears in the pool at all (filtered, not merely disabled). */
export async function expectOptionAbsent(page: Page, input: Locator, value: string) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  await input.fill(value)
  const listbox = await listboxFor(page, input)
  await expect(listbox.getByRole('option').filter({ has: page.getByText(value, { exact: true }) })).toHaveCount(0)
  await input.fill('')
  await page.keyboard.press('Escape')
}

// Labels already committed somewhere in the draft. Choices live on different
// builder steps, so the set has to survive across steps (see the M01-K spec).
let usedLabels = new Set<string>()

export function resetUsedLabels() {
  usedLabels = new Set<string>()
}

async function collectUsedLabels(page: Page) {
  const inputs = page.getByRole('combobox')
  for (let index = 0; index < (await inputs.count()); index += 1) {
    const value = (await inputs.nth(index).inputValue()).trim()
    if (value) usedLabels.add(value)
  }
  return usedLabels
}

async function chooseFirstEnabled(page: Page, input: Locator, used: Set<string>) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  await input.focus()
  const listbox = await listboxFor(page, input)
  await expect(listbox).toBeVisible()
  const options = listbox.locator('[role="option"]:not([disabled])')
  const count = await options.count()
  if (!count) throw new Error('Combobox has no selectable option')

  let target = -1
  for (let index = 0; index < count; index += 1) {
    const label = (await options.nth(index).innerText()).trim().split(/\r?\n/)[0].trim()
    if (!used.has(label)) {
      target = index
      used.add(label)
      break
    }
  }
  if (target < 0) target = 0

  const before = await currentDraftRevision(page)
  await options.nth(target).click()
  await waitForDraftRevision(page, before)
}

export async function fillEmptyComboboxes(page: Page, container: Locator) {
  const used = await collectUsedLabels(page)
  for (let pass = 0; pass < 260; pass += 1) {
    const inputs = container.getByRole('combobox')
    let changed = false
    for (let index = 0; index < (await inputs.count()); index += 1) {
      const input = inputs.nth(index)
      if (!(await input.isVisible()) || !(await input.isEnabled())) continue
      if ((await input.inputValue()).trim()) continue
      await chooseFirstEnabled(page, input, used)
      changed = true
      break
    }
    if (!changed) return
  }
  throw new Error('Required combobox selections did not converge')
}

async function chooseLowestLevelSpell(page: Page, input: Locator) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  await input.focus()
  const listbox = await listboxFor(page, input)
  await expect(listbox).toBeVisible()
  const options = listbox.locator('[role="option"]:not([disabled])')
  const count = await options.count()
  if (!count) throw new Error('Spell combobox has no selectable option')

  let bestIndex = -1
  let bestLevel = Number.POSITIVE_INFINITY
  for (let index = 0; index < count; index += 1) {
    const text = (await options.nth(index).innerText()).trim()
    const level = /Cantrip/.test(text) ? 0 : Number(text.match(/Level (\d+)/)?.[1] ?? Number.NaN)
    if (Number.isNaN(level)) throw new Error(`Cannot parse spell level from option: ${text}`)
    if (level < bestLevel) {
      bestLevel = level
      bestIndex = index
    }
  }

  const before = await currentDraftRevision(page)
  await options.nth(bestIndex).click()
  await waitForDraftRevision(page, before)
}

export async function fillExactSpellBuckets(page: Page) {
  for (let pass = 0; pass < 260; pass += 1) {
    const buckets = page.locator('.spell-bucket')
    let changed = false
    for (let index = 0; index < (await buckets.count()); index += 1) {
      const bucket = buckets.nth(index)
      const counter = (await bucket.locator('.spell-count').innerText()).trim()
      if (counter.includes('max')) continue
      const match = counter.match(/^(\d+)\s*\/\s*(\d+)$/)
      if (!match) continue
      if (Number(match[1]) >= Number(match[2])) continue
      await chooseLowestLevelSpell(page, bucket.getByRole('combobox'))
      changed = true
      break
    }
    if (!changed) return
  }
  throw new Error('Required spell selections did not converge')
}

export function draftIdFrom(page: Page) {
  const id = page.url().match(/\/character-builder\/([0-9a-f-]{36})$/)?.[1]
  if (!id) throw new Error(`Cannot parse draft id from ${page.url()}`)
  return id
}

export function characterIdFrom(page: Page) {
  const id = page.url().match(/\/characters\/([0-9a-f-]{36})$/)?.[1]
  if (!id) throw new Error(`Cannot parse character id from ${page.url()}`)
  return id
}

export async function readReview(request: APIRequestContext, draftId: string) {
  const response = await request.get(`/api/character-builder/drafts/${draftId}/review`)
  expect(response.ok()).toBeTruthy()
  const review = await response.json()
  expect(review.can_confirm, JSON.stringify(review.issues, null, 2)).toBeTruthy()
  return review
}

export async function readBuild(request: APIRequestContext, characterId: string, versionNo: number) {
  const response = await request.get(`/api/characters/${characterId}/versions/${versionNo}`)
  expect(response.ok()).toBeTruthy()
  return (await response.json()).build
}

export const STEP = {
  origin: 'Origin Race & background',
  abilities: 'Abilities Scores & starting choices',
  classRail: 'Class Level-by-level rail',
  spellcasting: 'Spellcasting Access & resources',
  equipment: 'Equipment Gear & roleplay',
  review: 'Review Build snapshot & confirm',
} as const

export async function goToStep(page: Page, step: keyof typeof STEP) {
  await page.getByRole('button', { name: STEP[step] }).click()
}

/** Start a Create draft from the Room Character Workspace and set up name, origin, abilities and class rail. */
export async function startCreate(
  page: Page,
  name: string,
  race: string,
  className: string,
  targetLevel: number,
) {
  resetUsedLabels()
  await openCharacterWorkshop(page)
  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)
  await expectDraftSaved(page)

  await page.getByLabel('Character name').fill(name)
  await page.getByLabel('Target character level').fill(String(targetLevel))
  await clickAndWaitForSave(page, page.getByRole('button', { name: 'Save Basic Details' }))

  await goToStep(page, 'origin')
  await chooseSearchable(page, 'Race', race)
  await chooseSearchable(page, 'Background', 'Acolyte', 'System Reference Document 5.1')
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  await goToStep(page, 'abilities')
  await clickAndWaitForSave(page, page.getByRole('button', { name: 'Save Ability Scores' }))

  await goToStep(page, 'classRail')
  for (let level = 1; level <= targetLevel; level += 1) {
    await chooseSearchable(page, `Level ${level} class`, className)
  }
}

/** Fill every remaining required choice on every step and land on the Review step. */
export async function finishAndReview(page: Page, request: APIRequestContext) {
  await goToStep(page, 'origin')
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  await goToStep(page, 'abilities')
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  await goToStep(page, 'classRail')
  await fillEmptyComboboxes(page, page.locator('.level-rail'))

  await goToStep(page, 'abilities')
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  await goToStep(page, 'spellcasting')
  await fillExactSpellBuckets(page)

  await goToStep(page, 'equipment')
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  const draftId = draftIdFrom(page)
  await goToStep(page, 'review')
  await expect(page.getByRole('heading', { name: 'Build snapshot & final review' })).toBeVisible()
  const review = await readReview(request, draftId)
  await expect(page.getByRole('button', { name: 'Confirm & Create Character' })).toBeEnabled()
  return { draftId, review }
}

export async function confirmCreate(page: Page, name: string) {
  await page.getByRole('button', { name: 'Confirm & Create Character' }).click()
  await expect(page).toHaveURL(/\/characters\/[0-9a-f-]{36}$/)
  await expect(page.getByRole('heading', { name })).toBeVisible()
  const characterId = characterIdFrom(page)
  await page.reload()
  await expect(page.getByRole('heading', { name })).toBeVisible()
  return characterId
}

/** Open a Level Up draft for the named character from the Room Character Workspace. */
export async function startLevelUp(page: Page, name: string, className: string, level: number) {
  await openCharacterWorkshop(page)
  const card = page.locator('.workshop-card').filter({ hasText: name })
  await expect(card).toHaveCount(1)
  await card.getByRole('button', { name: 'Level Up' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)
  await expectDraftSaved(page)
  resetUsedLabels()
  await goToStep(page, 'classRail')
  await chooseSearchable(page, `Level ${level} class`, className)
}

/** Fill the remaining Level Up choices and confirm the new version. */
export async function finishLevelUp(page: Page, characterId: string) {
  await goToStep(page, 'classRail')
  await fillEmptyComboboxes(page, page.locator('.level-rail'))
  await goToStep(page, 'abilities')
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))
  await goToStep(page, 'spellcasting')
  await fillExactSpellBuckets(page)

  await goToStep(page, 'review')
  await expect(page.getByRole('heading', { name: 'Level Up review' })).toBeVisible()
  const confirm = page.getByRole('button', { name: 'Confirm Level Up' })
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(page).toHaveURL(new RegExp(`/characters/${characterId}$`))
}

export async function forceLocale(page: Page, locale: 'zh-TW' | 'en') {
  await page.evaluate(
    ({ key, value }) => localStorage.setItem(key, value),
    { key: LOCALE_STORAGE_KEY, value: locale },
  )
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('lang', locale)
}

/** Feature chips on the Character Sheet. */
export function sheetFeatureChips(page: Page) {
  return page.locator('.feature-panel .feature-chips span')
}

/** Resolved-grant rows on the Review step. */
export function reviewGrants(page: Page) {
  return page.locator('.summary-grants .grant-row strong')
}
