import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

const FIGHTER_STYLE_OPTIONS = 'tce:feature:fighter-fighting-style-options'
const PALADIN_STYLE_OPTIONS = 'tce:feature:paladin-fighting-style-options'
const RANGER_STYLE_OPTIONS = 'tce:feature:ranger-fighting-style-options'
const SUPERIOR_TECHNIQUE = 'tce:feature:superior-technique'
const BLESSED_WARRIOR = 'tce:feature:blessed-warrior'
const DRUIDIC_WARRIOR = 'tce:feature:druidic-warrior'
const MANEUVER_AMBUSH = 'tce:feature:maneuver-ambush'
const MARTIAL_VERSATILITY = 'tce:feature:fighter-martial-versatility'
const ARCHERY = 'srd5.1:feature:fighter-fighting-style-archery'
const DEFENSE = 'srd5.1:feature:fighter-fighting-style-defense'

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
  if ((await option.count()) > 1) {
    const tceOption = option.filter({
      has: page.getByText("Tasha's Cauldron of Everything", { exact: true }),
    })
    if ((await tceOption.count()) === 1) option = tceOption
  }
  if ((await option.count()) > 1) {
    const srdOption = option.filter({
      has: page.getByText('System Reference Document 5.1', { exact: true }),
    })
    if ((await srdOption.count()) === 1) option = srdOption
  }

  await expect(option).toHaveCount(1)
  const before = await currentDraftRevision(page)
  await option.click()
  await expect(listbox).toBeHidden()
  await waitForDraftRevision(page, before)
}

async function chooseSearchable(
  page: Page,
  label: string | RegExp,
  value: string,
  source?: string,
) {
  await chooseOption(page, page.getByRole('combobox', { name: label }), value, source)
}

async function goToClassStep(page: Page) {
  await page.getByRole('button', { name: 'Class Level-by-level rail' }).click()
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
  await input.focus()
  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error('Combobox has no aria-controls listbox')
  const listbox = page.locator(`[id="${listboxId}"]`)
  await expect(listbox).toBeVisible()
  const option = listbox.locator('[role="option"]:not([disabled])').first()
  await expect(option).toBeVisible()
  const before = await currentDraftRevision(page)
  await option.click()
  await waitForDraftRevision(page, before)
}

async function fillEmptyComboboxes(page: Page, container: Locator) {
  for (let pass = 0; pass < 220; pass += 1) {
    const inputs = container.getByRole('combobox')
    let changed = false
    for (let index = 0; index < (await inputs.count()); index += 1) {
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
  for (let pass = 0; pass < 220; pass += 1) {
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
  const blocking = review.issues.filter(
    (issue: { severity: string }) => issue.severity === 'blocking_error',
  )
  expect(blocking, JSON.stringify(review.issues, null, 2)).toEqual([])
  expect(review.can_confirm, JSON.stringify(review.issues, null, 2)).toBeTruthy()
  return review
}

async function startCreate(
  page: Page,
  name: string,
  className: 'Fighter' | 'Paladin' | 'Ranger',
  targetLevel: number,
) {
  await page.goto('/characters')
  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)
  await expectDraftSaved(page)

  await page.getByLabel('Character name').fill(name)
  await page.getByLabel('Target character level').fill(String(targetLevel))
  await clickAndWaitForSave(page, page.getByRole('button', { name: 'Save Basic Details' }))

  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Race', 'Human', 'System Reference Document 5.1')
  await chooseSearchable(page, 'Background', 'Acolyte', 'System Reference Document 5.1')

  await page.getByRole('button', { name: /Abilities/ }).click()
  await clickAndWaitForSave(page, page.getByRole('button', { name: 'Save Ability Scores' }))
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  await goToClassStep(page)
  for (let level = 1; level <= targetLevel; level += 1) {
    await chooseSearchable(page, `Level ${level} class`, className)
  }
}

async function activateOptionalFeature(page: Page, featureName: string) {
  await page.getByRole('button', { name: /Abilities/ }).click()
  await chooseSearchable(
    page,
    new RegExp(`${featureName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}.*Optional Class Feature`, 'i'),
    featureName,
    "Tasha's Cauldron of Everything",
  )
}

async function finishCreateReview(page: Page, request: APIRequestContext) {
  await page.getByRole('button', { name: /Spellcasting/ }).click()
  await fillExactSpellBuckets(page)

  await page.getByRole('button', { name: /Equipment/ }).click()
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  const draftId = draftIdFrom(page)
  await page.getByRole('button', { name: /Review/ }).click()
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

function buildFrom(review: { build_candidate?: unknown }) {
  expect(review.build_candidate).toBeTruthy()
  return review.build_candidate as {
    feature_refs: string[]
    spell_access_entries: {
      spell_key: string
      source_key: string
      source_type: string
      access_type: string
      casting_ability?: string | null
    }[]
  }
}

test('M01-I Fighter selects a TCE Fighting Style with its nested maneuver', async ({ page, request }) => {
  test.slow()
  const name = `M01-I Fighter Style ${Date.now()}`
  await startCreate(page, name, 'Fighter', 1)
  await activateOptionalFeature(page, 'Fighting Style Options')

  await goToClassStep(page)
  const level1 = page.getByTestId('level-node-1')
  await chooseOption(page, level1.getByRole('combobox', { name: /Fighting Style/i }), 'Superior Technique')
  await chooseOption(
    page,
    level1.getByRole('combobox', { name: 'Superior Technique — Choice' }),
    'Maneuver: Ambush',
  )
  await fillEmptyComboboxes(page, page.locator('.level-rail'))

  const { review } = await finishCreateReview(page, request)
  const build = buildFrom(review)
  expect(build.feature_refs).toEqual(
    expect.arrayContaining([FIGHTER_STYLE_OPTIONS, SUPERIOR_TECHNIQUE, MANEUVER_AMBUSH]),
  )

  await confirmCreate(page, name)
})

test('M01-I Paladin Blessed Warrior persists two Cleric cantrips with Charisma', async ({ page, request }) => {
  test.slow()
  const name = `M01-I Blessed Warrior ${Date.now()}`
  await startCreate(page, name, 'Paladin', 2)
  await activateOptionalFeature(page, 'Fighting Style Options')

  await goToClassStep(page)
  const level2 = page.getByTestId('level-node-2')
  await chooseOption(page, level2.getByRole('combobox', { name: /Fighting Style/i }), 'Blessed Warrior')
  const cantripChoice = level2.locator('.builder-choice.progression-choice').filter({
    hasText: 'Blessed Warrior — Choice',
  })
  await expect(cantripChoice).toBeVisible()
  await chooseIn(cantripChoice, 'Guidance')
  await chooseIn(cantripChoice, 'Sacred Flame')
  await fillEmptyComboboxes(page, page.locator('.level-rail'))

  const { review } = await finishCreateReview(page, request)
  const build = buildFrom(review)
  expect(build.feature_refs).toEqual(expect.arrayContaining([PALADIN_STYLE_OPTIONS, BLESSED_WARRIOR]))
  const styleSpells = build.spell_access_entries.filter((entry) => entry.source_key === BLESSED_WARRIOR)
  expect(styleSpells).toHaveLength(2)
  expect(styleSpells.map((entry) => entry.spell_key)).toEqual(
    expect.arrayContaining(['srd5.1:spell:guidance', 'srd5.1:spell:sacred-flame']),
  )
  expect(new Set(styleSpells.map((entry) => entry.casting_ability))).toEqual(new Set(['charisma']))

  await confirmCreate(page, name)
  await page.getByRole('tab', { name: /Spells/ }).click()
  await expect(page.getByRole('heading', { name: 'Guidance' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Sacred Flame' })).toBeVisible()
})

test('M01-I Ranger Druidic Warrior persists two Druid cantrips with Wisdom', async ({ page, request }) => {
  test.slow()
  const name = `M01-I Druidic Warrior ${Date.now()}`
  await startCreate(page, name, 'Ranger', 2)
  await activateOptionalFeature(page, 'Fighting Style Options')

  await goToClassStep(page)
  const level2 = page.getByTestId('level-node-2')
  await chooseOption(page, level2.getByRole('combobox', { name: /Fighting Style/i }), 'Druidic Warrior')
  const cantripChoice = level2.locator('.builder-choice.progression-choice').filter({
    hasText: 'Druidic Warrior — Choice',
  })
  await expect(cantripChoice).toBeVisible()
  await chooseIn(cantripChoice, 'Druidcraft')
  await chooseIn(cantripChoice, 'Produce Flame')
  await fillEmptyComboboxes(page, page.locator('.level-rail'))

  const { review } = await finishCreateReview(page, request)
  const build = buildFrom(review)
  expect(build.feature_refs).toEqual(expect.arrayContaining([RANGER_STYLE_OPTIONS, DRUIDIC_WARRIOR]))
  const styleSpells = build.spell_access_entries.filter((entry) => entry.source_key === DRUIDIC_WARRIOR)
  expect(styleSpells).toHaveLength(2)
  expect(styleSpells.map((entry) => entry.spell_key)).toEqual(
    expect.arrayContaining(['srd5.1:spell:druidcraft', 'srd5.1:spell:produce-flame']),
  )
  expect(new Set(styleSpells.map((entry) => entry.casting_ability))).toEqual(new Set(['wisdom']))

  await confirmCreate(page, name)
  await page.getByRole('tab', { name: /Spells/ }).click()
  await expect(page.getByRole('heading', { name: 'Druidcraft' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Produce Flame' })).toBeVisible()
})

test('M01-I Ranger replacement flow removes all represented base grants from the final Build', async ({ page, request }) => {
  test.slow()
  const name = `M01-I Ranger Replacements ${Date.now()}`
  await startCreate(page, name, 'Ranger', 10)

  await activateOptionalFeature(page, 'Deft Explorer')
  await activateOptionalFeature(page, 'Favored Foe')
  await activateOptionalFeature(page, 'Primal Awareness')
  await activateOptionalFeature(page, "Nature's Veil")

  await goToClassStep(page)
  await chooseSearchable(page, /Ranger subclass/, 'Hunter')
  await fillEmptyComboboxes(page, page.locator('.level-rail'))

  const { review } = await finishCreateReview(page, request)
  const build = buildFrom(review)
  expect(build.feature_refs).toEqual(
    expect.arrayContaining([
      'tce:feature:deft-explorer',
      'tce:feature:favored-foe',
      'tce:feature:primal-awareness',
      'tce:feature:natures-veil',
    ]),
  )
  expect(build.feature_refs.some((ref) => ref.includes('natural-explorer-'))).toBeFalsy()
  expect(build.feature_refs.some((ref) => ref.includes('favored-enemy-'))).toBeFalsy()
  expect(build.feature_refs).not.toContain('srd5.1:feature:primeval-awareness')
  expect(build.feature_refs).not.toContain('srd5.1:feature:hide-in-plain-sight')

  await confirmCreate(page, name)
})

test('M01-I existing Fighter levels up with Martial Versatility and preserves Version History', async ({ page, request }) => {
  test.slow()
  const name = `M01-I Martial Versatility ${Date.now()}`
  await startCreate(page, name, 'Fighter', 3)

  const level1 = page.getByTestId('level-node-1')
  await chooseOption(page, level1.getByRole('combobox', { name: /Fighting Style/i }), 'Fighting Style: Archery')
  await chooseSearchable(page, /Fighter subclass/, 'Champion')
  await fillEmptyComboboxes(page, page.locator('.level-rail'))

  await finishCreateReview(page, request)
  const characterId = await confirmCreate(page, name)

  const version1Response = await request.get(`/api/characters/${characterId}`)
  expect(version1Response.ok()).toBeTruthy()
  const version1 = await version1Response.json()
  expect(version1.version_no).toBe(1)
  expect(version1.build.feature_refs).toContain(ARCHERY)

  await page.goto('/characters')
  const card = page.locator('.workshop-card').filter({ hasText: name })
  await expect(card).toHaveCount(1)
  await card.getByRole('button', { name: 'Level Up' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)
  await expectDraftSaved(page)

  await goToClassStep(page)
  await chooseSearchable(page, 'Level 4 class', 'Fighter')
  await chooseSearchable(page, 'Fighter 4 — ASI or Feat', 'Grappler')

  const level4 = page.getByTestId('level-node-4')
  await chooseOption(
    page,
    level4.getByRole('combobox', { name: /Martial Versatility.*Optional Class Feature/i }),
    'Martial Versatility',
    "Tasha's Cauldron of Everything",
  )
  await chooseOption(
    page,
    level4.getByRole('combobox', { name: /Martial Versatility.*Fighting Style/i }),
    'Replace one choice',
  )
  await chooseOption(
    page,
    level4.getByRole('combobox', { name: /Martial Versatility.*Replace/i }),
    'Fighting Style: Archery',
  )
  await chooseOption(
    page,
    level4.getByRole('combobox', { name: /Martial Versatility.*New choice/i }),
    'Fighting Style: Defense',
  )

  const draftId = draftIdFrom(page)
  await page.getByRole('button', { name: /Review/ }).click()
  await expect(page.getByRole('heading', { name: 'Level Up review' })).toBeVisible()
  const review = await readReview(request, draftId)
  const build = buildFrom(review)
  expect(build.feature_refs).toContain(MARTIAL_VERSATILITY)
  expect(build.feature_refs).toContain(DEFENSE)
  expect(build.feature_refs).not.toContain(ARCHERY)

  const confirm = page.getByRole('button', { name: 'Confirm Level Up' })
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(page).toHaveURL(new RegExp(`/characters/${characterId}$`))
  await expect(page.getByText('Build v2')).toBeVisible()

  const version2Response = await request.get(`/api/characters/${characterId}`)
  expect(version2Response.ok()).toBeTruthy()
  const version2 = await version2Response.json()
  expect(version2.version_no).toBe(2)
  expect(version2.build.feature_refs).toContain(DEFENSE)
  expect(version2.build.feature_refs).not.toContain(ARCHERY)

  await page.goto(`/characters/${characterId}/versions`)
  await expect(page.getByRole('heading', { name: 'Version 1' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Version 2' })).toBeVisible()
})
