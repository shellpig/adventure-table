import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

const ARTIFICER = 'tce:class:artificer'
const ALCHEMIST = 'tce:subclass:alchemist'
const WIZARD = 'srd5.1:class:wizard'

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

  // Some selectors only show source provenance when the visible label collides.
  // Keep unique options selectable by label, and disambiguate only when needed.
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

async function chooseSearchable(page: Page, label: string | RegExp, value: string, source?: string) {
  await chooseOption(page, page.getByRole('combobox', { name: label }), value, source)
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
  for (let pass = 0; pass < 160; pass += 1) {
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
  for (let pass = 0; pass < 160; pass += 1) {
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

async function saveManualArtificerAbilities(page: Page) {
  await page.getByRole('tab', { name: 'Manual Input' }).click()
  const scores: Record<string, string> = {
    'STR · Strength': '10',
    'DEX · Dexterity': '14',
    'CON · Constitution': '14',
    'INT · Intelligence': '16',
    'WIS · Wisdom': '12',
    'CHA · Charisma': '8',
  }
  for (const [label, score] of Object.entries(scores)) {
    await page.getByLabel(label).fill(score)
  }
  await clickAndWaitForSave(page, page.getByRole('button', { name: 'Save Ability Scores' }))
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

async function prepareCreateReview(
  page: Page,
  request: APIRequestContext,
  options: {
    name: string
    classes: ('Artificer' | 'Wizard')[]
    specialist?: 'Alchemist'
  },
) {
  await page.goto('/characters')
  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)
  await expectDraftSaved(page)

  await page.getByLabel('Character name').fill(options.name)
  await page.getByLabel('Target character level').fill(String(options.classes.length))
  await clickAndWaitForSave(page, page.getByRole('button', { name: 'Save Basic Details' }))

  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Race', 'Human', 'System Reference Document 5.1')
  await chooseSearchable(page, 'Background', 'Acolyte', 'System Reference Document 5.1')

  await page.getByRole('button', { name: /Abilities/ }).click()
  await saveManualArtificerAbilities(page)
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  await page.getByRole('button', { name: /Class/ }).click()
  for (let level = 1; level <= options.classes.length; level += 1) {
    await chooseSearchable(page, `Level ${level} class`, options.classes[level - 1])
  }
  if (options.specialist) {
    await chooseSearchable(
      page,
      'Artificer subclass · required at class level 3',
      options.specialist,
      "Tasha's Cauldron of Everything",
    )
  }
  await fillEmptyComboboxes(page, page.locator('.level-rail'))

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

async function confirmCreate(page: Page, expectedName: string) {
  await page.getByRole('button', { name: 'Confirm & Create Character' }).click()
  await expect(page).toHaveURL(/\/characters\/[0-9a-f-]{36}$/)
  await expect(page.getByRole('heading', { name: expectedName })).toBeVisible()
  return characterIdFrom(page)
}

test('M01-G real backend creates an Artificer level 1', async ({ page, request }) => {
  test.slow()
  const name = `M01-G Artificer 1 ${Date.now()}`
  const { review } = await prepareCreateReview(page, request, { name, classes: ['Artificer'] })

  expect(review.resolved_summary.class_summary).toBe('Artificer 1')
  const profile = review.resolved_summary.spellcasting_profiles.find(
    (item: { class_ref: string }) => item.class_ref === ARTIFICER,
  )
  expect(profile?.access_model).toBe('prepared')
  expect(profile?.class_level).toBe(1)
  expect(profile?.max_spell_level).toBe(1)

  const characterId = await confirmCreate(page, name)
  const response = await request.get(`/api/characters/${characterId}`)
  expect(response.ok()).toBeTruthy()
  expect((await response.json()).version_no).toBe(1)
})

test('M01-G real backend creates Artificer 3 with an Alchemist Specialist', async ({ page, request }) => {
  test.slow()
  const name = `M01-G Alchemist 3 ${Date.now()}`
  const { review } = await prepareCreateReview(page, request, {
    name,
    classes: ['Artificer', 'Artificer', 'Artificer'],
    specialist: 'Alchemist',
  })

  const level3 = review.resolved_summary.progression[2]
  expect(level3.class_ref).toBe(ARTIFICER)
  expect(level3.subclass_ref).toBe(ALCHEMIST)
  expect(level3.automatic_feature_refs).toEqual(
    expect.arrayContaining([
      'tce:feature:alchemist-tool-proficiency',
      'tce:feature:alchemist-spells',
      'tce:feature:experimental-elixir',
    ]),
  )
  await confirmCreate(page, name)
})

test('M01-G real backend reviews and creates high-level Artificer 15 progression', async ({ page, request }) => {
  test.slow()
  const name = `M01-G Alchemist 15 ${Date.now()}`
  const { review } = await prepareCreateReview(page, request, {
    name,
    classes: Array.from({ length: 15 }, () => 'Artificer' as const),
    specialist: 'Alchemist',
  })

  expect(review.resolved_summary.progression).toHaveLength(15)
  const level15 = review.resolved_summary.progression[14]
  expect(level15.class_ref).toBe(ARTIFICER)
  expect(level15.subclass_ref).toBe(ALCHEMIST)
  expect(level15.automatic_feature_refs).toContain('tce:feature:chemical-mastery')
  const profile = review.resolved_summary.spellcasting_profiles.find(
    (item: { class_ref: string }) => item.class_ref === ARTIFICER,
  )
  expect(profile?.class_level).toBe(15)
  expect(profile?.max_spell_level).toBe(4)
  await confirmCreate(page, name)
})

test('M01-G real backend reviews Artificer 1 / Wizard 1 shared multiclass slots', async ({ page, request }) => {
  test.slow()
  const name = `M01-G Artificer Wizard ${Date.now()}`
  const { review } = await prepareCreateReview(page, request, {
    name,
    classes: ['Artificer', 'Wizard'],
  })

  expect(review.resolved_summary.class_summary).toBe('Artificer 1 / Wizard 1')
  const pool = review.resolved_summary.spell_resource_pools.find(
    (item: { pool_type: string }) => item.pool_type === 'normal_multiclass_slots',
  )
  expect(pool).toBeTruthy()
  expect(pool.slots.find((slot: { level: number }) => slot.level === 1)?.count).toBe(3)
  const artificerProfile = review.resolved_summary.spellcasting_profiles.find(
    (item: { class_ref: string }) => item.class_ref === ARTIFICER,
  )
  const wizardProfile = review.resolved_summary.spellcasting_profiles.find(
    (item: { class_ref: string }) => item.class_ref === WIZARD,
  )
  expect(artificerProfile?.class_level).toBe(1)
  expect(wizardProfile?.class_level).toBe(1)
  await confirmCreate(page, name)
})

test('M01-G real backend levels an existing Artificer 2 to 3 and adds Specialist without resetting live state', async ({ page, request }) => {
  test.slow()
  const name = `M01-G Level Up ${Date.now()}`
  await prepareCreateReview(page, request, { name, classes: ['Artificer', 'Artificer'] })
  const characterId = await confirmCreate(page, name)

  const beforeResponse = await request.get(`/api/characters/${characterId}`)
  expect(beforeResponse.ok()).toBeTruthy()
  const before = await beforeResponse.json()
  const originalInventory = before.state.inventory_state
  const patchResponse = await request.patch(`/api/characters/${characterId}/state`, {
    data: {
      current_hp: Math.max(1, before.state.current_hp - 4),
      temporary_hp: 4,
      hit_dice_state: { ...before.state.hit_dice_state, d8: 1 },
      inventory_state: originalInventory,
    },
  })
  expect(patchResponse.ok()).toBeTruthy()

  await page.goto('/characters')
  const card = page.locator('.workshop-card').filter({ hasText: name })
  await expect(card).toHaveCount(1)
  await card.getByRole('button', { name: 'Level Up' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)
  await expectDraftSaved(page)

  await page.getByRole('button', { name: /Class/ }).click()
  await expect(page.getByTestId('level-node-1')).toContainText('Artificer 1')
  await expect(page.getByTestId('level-node-2')).toContainText('Artificer 2')
  await chooseSearchable(page, 'Level 3 class', 'Artificer')
  await chooseSearchable(
    page,
    'Artificer subclass · required at class level 3',
    'Alchemist',
    "Tasha's Cauldron of Everything",
  )
  await fillEmptyComboboxes(page, page.getByTestId('level-node-3'))

  const draftId = draftIdFrom(page)
  await page.getByRole('button', { name: /Review/ }).click()
  await expect(page.getByRole('heading', { name: 'Level Up review' })).toBeVisible()
  const review = await readReview(request, draftId)
  expect(review.resolved_summary.progression[2].subclass_ref).toBe(ALCHEMIST)

  const confirm = page.getByRole('button', { name: 'Confirm Level Up' })
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(page).toHaveURL(new RegExp(`/characters/${characterId}$`))
  await expect(page.getByText('Build v2')).toBeVisible()

  const afterResponse = await request.get(`/api/characters/${characterId}`)
  expect(afterResponse.ok()).toBeTruthy()
  const after = await afterResponse.json()
  expect(after.version_no).toBe(2)
  expect(after.state.temporary_hp).toBe(4)
  expect(after.state.inventory_state).toEqual(originalInventory)

  await page.goto(`/characters/${characterId}/versions`)
  await expect(page.getByRole('heading', { name: 'Version 1' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Version 2' })).toBeVisible()
})