import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

const OBSERVANT = 'phb2014:feat:observant'
const TOUGH = 'phb2014:feat:tough'
const ELEMENTAL_ADEPT = 'phb2014:feat:elemental-adept'
const MARTIAL_ADEPT = 'phb2014:feat:martial-adept'
const CHROMATIC_ORB = 'phb2014:spell:chromatic-orb'
const SEARING_SMITE = 'phb2014:spell:searing-smite'

async function expectDraftSaved(page: Page) {
  await expect(page.getByText('Saved on server')).toBeVisible()
}

async function currentDraftRevision(page: Page) {
  const text = (await page.locator('.builder-save-state span').innerText()).trim()
  const match = text.match(/^Draft revision (\d+)$/)
  if (!match) throw new Error(`Cannot parse draft revision from: ${text}`)
  return Number(match[1])
}

async function waitForDraftRevision(page: Page, before: number) {
  await expect.poll(() => currentDraftRevision(page)).toBeGreaterThan(before)
  await expectDraftSaved(page)
}

async function clickAndWaitForSave(page: Page, button: Locator) {
  await expectDraftSaved(page)
  const before = await currentDraftRevision(page)
  await button.click()
  await waitForDraftRevision(page, before)
}

async function chooseOption(page: Page, input: Locator, value: string, source?: string) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  await input.fill(value)

  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error(`Combobox for "${value}" has no aria-controls listbox`)
  const listbox = page.locator(`[id="${listboxId}"]`)
  let option = listbox.getByRole('option').filter({ has: page.getByText(value, { exact: true }) })

  if (source && (await option.count()) > 1) {
    const sourced = option.filter({ has: page.getByText(source, { exact: true }) })
    if ((await sourced.count()) === 1) option = sourced
  }
  await expect(option).toHaveCount(1)
  const before = await currentDraftRevision(page)
  await option.click()
  await expect(listbox).toBeHidden()
  await waitForDraftRevision(page, before)
}

async function chooseSearchable(page: Page, label: string | RegExp, value: string, source?: string) {
  await chooseOption(page, page.getByRole('combobox', { name: label }), value, source)
}

/** Assert an option is offered but closed, with its reason attached. */
async function expectOptionDisabled(page: Page, input: Locator, value: string) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  await input.fill(value)
  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error(`Combobox for "${value}" has no aria-controls listbox`)
  const listbox = page.locator(`[id="${listboxId}"]`)
  const option = listbox
    .getByRole('option')
    .filter({ has: page.getByText(value, { exact: true }) })
  await expect(option).toHaveCount(1)
  await expect(option).toBeDisabled()
  await input.fill('')
  await page.keyboard.press('Escape')
}

/** Every label already committed somewhere in the draft.
 *
 * The builder rejects granting the same reference twice, so a naive
 * "take the first enabled option" filler collides as soon as two choices share
 * a pool (a race skill and a class skill, say). Skipping labels already in use
 * keeps the sweep on legal ground.
 */
// Choices live on different builder steps, so only the current step's inputs are
// in the DOM at any moment. The set therefore has to survive across steps.
let usedLabels = new Set<string>()

function resetUsedLabels() {
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
  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error('Combobox has no aria-controls listbox')
  const listbox = page.locator(`[id="${listboxId}"]`)
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
  // Skipping used labels is only a duplicate-avoidance heuristic. Choices such
  // as Expertise legitimately reselect something the character already has, so
  // fall back to the first enabled option rather than giving up.
  if (target < 0) target = 0

  const before = await currentDraftRevision(page)
  await options.nth(target).click()
  await waitForDraftRevision(page, before)
}

async function fillEmptyComboboxes(page: Page, container: Locator) {
  for (let pass = 0; pass < 260; pass += 1) {
    const used = await collectUsedLabels(page)
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
  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error('Spell combobox has no aria-controls listbox')
  const listbox = page.locator(`[id="${listboxId}"]`)
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

async function fillExactSpellBuckets(page: Page) {
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

function draftIdFrom(page: Page) {
  const id = page.url().match(/\/character-builder\/([0-9a-f-]{36})$/)?.[1]
  if (!id) throw new Error(`Cannot parse draft id from ${page.url()}`)
  return id
}

function characterIdFrom(page: Page) {
  const id = page.url().match(/\/characters\/([0-9a-f-]{36})$/)?.[1]
  if (!id) throw new Error(`Cannot parse character id from ${page.url()}`)
  return id
}

async function readReview(request: APIRequestContext, draftId: string) {
  const response = await request.get(`/api/character-builder/drafts/${draftId}/review`)
  expect(response.ok()).toBeTruthy()
  const review = await response.json()
  expect(review.can_confirm, JSON.stringify(review.issues, null, 2)).toBeTruthy()
  return review
}

async function readBuild(request: APIRequestContext, characterId: string, versionNo: number) {
  const response = await request.get(`/api/characters/${characterId}/versions/${versionNo}`)
  expect(response.ok()).toBeTruthy()
  return (await response.json()).build
}

async function readSheet(request: APIRequestContext, characterId: string) {
  const response = await request.get(`/api/characters/${characterId}/sheet`)
  expect(response.ok()).toBeTruthy()
  return response.json()
}

async function startCreate(
  page: Page,
  name: string,
  race: string,
  className: string,
  targetLevel: number,
) {
  resetUsedLabels()
  await page.goto('/characters')
  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)
  await expectDraftSaved(page)

  await page.getByLabel('Character name').fill(name)
  await page.getByLabel('Target character level').fill(String(targetLevel))
  await clickAndWaitForSave(page, page.getByRole('button', { name: 'Save Basic Details' }))

  await page.getByRole('button', { name: 'Origin Race & background' }).click()
  await chooseSearchable(page, 'Race', race)
  await chooseSearchable(page, 'Background', 'Acolyte', 'System Reference Document 5.1')
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  await page.getByRole('button', { name: 'Abilities Scores & starting choices' }).click()
  await clickAndWaitForSave(page, page.getByRole('button', { name: 'Save Ability Scores' }))

  await page.getByRole('button', { name: 'Class Level-by-level rail' }).click()
  for (let level = 1; level <= targetLevel; level += 1) {
    await chooseSearchable(page, `Level ${level} class`, className)
  }
}

async function finishAndReview(page: Page, request: APIRequestContext) {
  await page.getByRole('button', { name: 'Origin Race & background' }).click()
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  await page.getByRole('button', { name: 'Abilities Scores & starting choices' }).click()
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  await page.getByRole('button', { name: 'Class Level-by-level rail' }).click()
  await fillEmptyComboboxes(page, page.locator('.level-rail'))

  await page.getByRole('button', { name: 'Abilities Scores & starting choices' }).click()
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  await page.getByRole('button', { name: 'Spellcasting Access & resources' }).click()
  await fillExactSpellBuckets(page)

  await page.getByRole('button', { name: 'Equipment Gear & roleplay' }).click()
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  const draftId = draftIdFrom(page)
  await page.getByRole('button', { name: 'Review Build snapshot & confirm' }).click()
  await expect(page.getByRole('heading', { name: 'Build snapshot & final review' })).toBeVisible()
  const review = await readReview(request, draftId)
  await expect(page.getByRole('button', { name: 'Confirm & Create Character' })).toBeEnabled()
  return { draftId, review }
}

async function confirmCreate(page: Page, name: string) {
  await page.getByRole('button', { name: 'Confirm & Create Character' }).click()
  await expect(page).toHaveURL(/\/characters\/[0-9a-f-]{36}$/)
  await expect(page.getByRole('heading', { name })).toBeVisible()
  const characterId = characterIdFrom(page)
  await page.reload()
  await expect(page.getByRole('heading', { name })).toBeVisible()
  return characterId
}

// K-E2E-01 + K-E2E-03 — Variant Human takes a structural PHB feat, and an
// unmet prerequisite is visible rather than silently missing.
test('M01-K Variant Human takes a PHB feat with a nested choice', async ({ page, request }) => {
  const name = 'M01-K Observant Human'
  await startCreate(page, name, 'Variant Human', 'Fighter', 1)

  await page.getByRole('button', { name: 'Abilities Scores & starting choices' }).click()
  const featSelect = page.getByRole('combobox', { name: /Feat/ }).first()
  await expectOptionDisabled(page, featSelect, 'Elemental Adept')

  await chooseOption(page, featSelect, 'Observant')
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  const { review } = await finishAndReview(page, request)
  expect(review.build_candidate.feat_refs).toContain(OBSERVANT)

  const characterId = await confirmCreate(page, name)
  const build = await readBuild(request, characterId, 1)
  expect(build.feat_refs).toEqual([OBSERVANT])
  expect(build.feat_acquisitions).toHaveLength(1)
  expect(build.feat_acquisitions[0].selections.ability).toHaveLength(1)
  expect(
    build.static_derived_modifiers.map((entry: { target: string }) => entry.target).sort(),
  ).toEqual(['passive_investigation', 'passive_perception'])

  const sheet = await readSheet(request, characterId)
  expect(sheet.passive_investigation).toBeGreaterThan(10)
  expect(sheet.features.map((entry: { key: string }) => entry.key)).toContain(OBSERVANT)
  await expect(page.getByText('Passive Investigation')).toBeVisible()
})

// K-E2E-03 — a non-repeatable feat is visibly closed at the next opportunity.
test('M01-K blocks a second acquisition of a non-repeatable feat', async ({ page }) => {
  await startCreate(page, 'M01-K Tough Twice', 'Variant Human', 'Fighter', 4)

  await page.getByRole('button', { name: 'Abilities Scores & starting choices' }).click()
  await chooseOption(page, page.getByRole('combobox', { name: /Feat/ }).first(), 'Tough')
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  await page.getByRole('button', { name: 'Class Level-by-level rail' }).click()
  await expectOptionDisabled(page, page.getByRole('combobox', { name: /4 . ASI or Feat/ }), 'Tough')
})

// K-E2E-02 — the same feat inventory reached through Level Up.
test('M01-K takes a PHB feat at an ASI during Level Up', async ({ page, request }) => {
  const name = 'M01-K Level Up Tough'
  await startCreate(page, name, 'Human', 'Fighter', 1)
  const { review } = await finishAndReview(page, request)
  expect(review.build_candidate.feat_refs).toEqual([])
  const characterId = await confirmCreate(page, name)
  const baseSheet = await readSheet(request, characterId)

  for (const level of [2, 3, 4]) {
    await page.goto('/characters')
    const card = page.locator('.workshop-card').filter({ hasText: name })
    await expect(card).toHaveCount(1)
    await card.getByRole('button', { name: 'Level Up' }).click()
    await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)

    resetUsedLabels()
    await page.getByRole('button', { name: 'Class Level-by-level rail' }).click()
    await chooseSearchable(page, `Level ${level} class`, 'Fighter')
    if (level === 4) {
      const asi = page.getByRole('combobox', { name: /4 . ASI or Feat/ })
      await chooseOption(page, asi, 'Tough')
    }
    await fillEmptyComboboxes(page, page.locator('.level-rail'))
    await page.getByRole('button', { name: 'Abilities Scores & starting choices' }).click()
    await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

    await page.getByRole('button', { name: 'Review Build snapshot & confirm' }).click()
    await expect(page.getByRole('heading', { name: 'Level Up review' })).toBeVisible()
    const confirm = page.getByRole('button', { name: 'Confirm Level Up' })
    await expect(confirm).toBeEnabled()
    await confirm.click()
    await expect(page).toHaveURL(new RegExp(`/characters/${characterId}$`))
  }

  const versionOne = await readBuild(request, characterId, 1)
  const versionFour = await readBuild(request, characterId, 4)
  expect(versionOne.feat_refs).toEqual([])
  expect(versionFour.feat_refs).toEqual([TOUGH])
  expect(versionFour.static_derived_modifiers[0].target).toBe('max_hp')

  await page.goto(`/characters/${characterId}/versions`)
  await expect(page.getByRole('heading', { name: 'Version 1' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Version 4' })).toBeVisible()

  const sheet = await readSheet(request, characterId)
  expect(sheet.features.map((entry: { key: string }) => entry.key)).toContain(TOUGH)
  expect(sheet.max_hp).toBeGreaterThan(baseSheet.max_hp)
})

// K-E2E-04 + K-E2E-07 — a repeatable feat twice, and a PHB-only spellbook spell.
test('M01-K keeps two Elemental Adept acquisitions and a PHB spellbook spell', async ({
  page,
  request,
}) => {
  const name = 'M01-K Repeatable Wizard'
  await startCreate(page, name, 'Human', 'Wizard', 8)

  await page.getByRole('button', { name: 'Class Level-by-level rail' }).click()
  for (const level of [4, 8]) {
    const asi = page.getByRole('combobox', { name: new RegExp(`${level} . ASI or Feat`) })
    await chooseOption(page, asi, 'Elemental Adept')
  }

  await page.getByRole('button', { name: 'Abilities Scores & starting choices' }).click()
  const elements = page.getByRole('combobox', { name: /Elemental Adept/ })
  await expect(elements).toHaveCount(2)
  await chooseOption(page, elements.nth(0), 'Fire')
  await chooseOption(page, elements.nth(1), 'Cold')

  await page.getByRole('button', { name: 'Spellcasting Access & resources' }).click()
  const spellbook = page.locator('.spell-bucket').filter({ hasText: 'Spellbook' }).first()
  await chooseOption(page, spellbook.getByRole('combobox'), 'Chromatic Orb')

  const { review } = await finishAndReview(page, request)
  expect(review.build_candidate.feat_acquisitions).toHaveLength(2)

  const characterId = await confirmCreate(page, name)
  const build = await readBuild(request, characterId, 1)

  expect(build.feat_refs).toEqual([ELEMENTAL_ADEPT])
  expect(build.feat_acquisitions).toHaveLength(2)
  const elementChoices = build.feat_acquisitions
    .map((entry: { selections: { element: string[] } }) => entry.selections.element[0])
    .sort()
  expect(elementChoices).toEqual(['enum:cold', 'enum:fire'])
  expect(
    new Set(
      build.feat_acquisitions.map((entry: { acquisition_id: string }) => entry.acquisition_id),
    ).size,
  ).toBe(2)
  expect(
    build.spell_access_entries.map((entry: { spell_key: string }) => entry.spell_key),
  ).toContain(CHROMATIC_ORB)
})

// K-E2E-05 — a non-Fighter reaches the canonical maneuver pool through the feat.
test('M01-K lets a non-Fighter take Martial Adept maneuvers', async ({ page, request }) => {
  const name = 'M01-K Martial Wizard'
  await startCreate(page, name, 'Human', 'Wizard', 4)

  await page.getByRole('button', { name: 'Class Level-by-level rail' }).click()
  const asi = page.getByRole('combobox', { name: /4 . ASI or Feat/ })
  await chooseOption(page, asi, 'Martial Adept')

  await page.getByRole('button', { name: 'Abilities Scores & starting choices' }).click()
  // The maneuver pool is a 2-of-N chip picker, so its identity is the heading.
  await expect(
    page.locator('.builder-choice__heading').filter({ hasText: 'Martial Adept' }),
  ).toHaveCount(1)
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  const { review } = await finishAndReview(page, request)
  expect(review.build_candidate.feat_refs).toContain(MARTIAL_ADEPT)

  const characterId = await confirmCreate(page, name)
  const build = await readBuild(request, characterId, 1)
  const granted = build.feature_refs.filter((ref: string) => ref.includes(':feature:maneuver-'))
  expect(granted).toHaveLength(2)
  const provenance = build.feature_grant_sources
    .filter((entry: { feature_ref: string }) => granted.includes(entry.feature_ref))
    .map((entry: { source_ref: string }) => entry.source_ref)
  expect(new Set(provenance)).toEqual(new Set([MARTIAL_ADEPT]))

  const sheet = await readSheet(request, characterId)
  expect(sheet.resources['feature:superiority-dice'].remaining).toBe(1)
})

// K-E2E-06 + 08 + 09 — PHB-only spells reach class and cross-source pools.
test('M01-K exposes PHB-only spells through class and cross-source access', async ({
  page,
  request,
}) => {
  const name = 'M01-K Smiting Ranger'
  await startCreate(page, name, 'Human', 'Ranger', 5)

  await page.getByRole('button', { name: 'Spellcasting Access & resources' }).click()
  const bucket = page.locator('.spell-bucket').first()
  // Searing Smite is Paladin-only in the PHB; the Ranger only sees it because a
  // later source expanded its access.
  await chooseOption(page, bucket.getByRole('combobox'), 'Searing Smite')

  const { review } = await finishAndReview(page, request)
  const characterId = await confirmCreate(page, name)
  const build = await readBuild(request, characterId, 1)
  expect(
    build.spell_access_entries.map((entry: { spell_key: string }) => entry.spell_key),
  ).toContain(SEARING_SMITE)

  const profile = review.resolved_summary.spellcasting_profiles[0]
  const available = profile.available_spells.map((entry: { spell_key: string }) => entry.spell_key)
  expect(available).toContain(SEARING_SMITE)
  expect(available.some((key: string) => key.startsWith('phb2014:spell:'))).toBeTruthy()
})
