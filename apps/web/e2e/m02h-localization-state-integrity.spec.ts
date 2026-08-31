import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

const FIXTURE_ID = '00000000-0000-4000-8000-0000000000e0'
const LOCALE_STORAGE_KEY = 'adventure-table.locale'

type DraftSnapshot = {
  draft: {
    revision: number
    draft_payload: Record<string, unknown>
  }
}

async function setLocale(page: Page, locale: 'zh-TW' | 'en') {
  await page.getByTestId(`locale-option-${locale}`).click()
  await expect(page.locator('html')).toHaveAttribute('lang', locale)
}

async function expectDraftSaved(page: Page) {
  await expect(page.getByText(/Saved on server|已儲存至伺服器/)).toBeVisible()
}

async function currentDraftRevision(page: Page) {
  const text = (await page.locator('.builder-save-state span').innerText()).trim()
  const match = text.match(/(?:Draft revision|草稿版本)\s*(\d+)/)
  if (!match) throw new Error(`Cannot parse draft revision from: ${text}`)
  return Number(match[1])
}

async function chooseOption(page: Page, input: Locator, value: string) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  await input.fill(value)
  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error(`Combobox for "${value}" has no aria-controls listbox`)
  const listbox = page.locator(`[id="${listboxId}"]`)
  let option = listbox.getByRole('option').filter({ has: page.getByText(value, { exact: true }) })
  if ((await option.count()) > 1) {
    const srd = option.filter({ has: page.getByText('System Reference Document 5.1', { exact: true }) })
    if ((await srd.count()) === 1) option = srd
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
  await chooseOption(container.page(), container.getByRole('combobox', { name: 'Add selection' }), value)
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
  await option.click()
  await expectDraftSaved(page)
}

async function fillEmptyComboboxes(page: Page, container: Locator) {
  for (let pass = 0; pass < 96; pass += 1) {
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
  await input.focus()
  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error('Spell combobox has no aria-controls listbox')
  const listbox = page.locator(`[id="${listboxId}"]`)
  await expect(listbox).toBeVisible()
  const options = listbox.locator('[role="option"]:not([disabled])')
  const count = await options.count()
  if (count === 0) throw new Error('Spell combobox has no selectable option')

  let bestIndex = 0
  let bestLevel = Number.POSITIVE_INFINITY
  for (let index = 0; index < count; index += 1) {
    const text = (await options.nth(index).innerText()).trim()
    const level = /Cantrip/.test(text) ? 0 : Number(text.match(/Level (\d+)/)?.[1] ?? Number.NaN)
    if (!Number.isNaN(level) && level < bestLevel) {
      bestLevel = level
      bestIndex = index
    }
  }
  await options.nth(bestIndex).click()
  await expectDraftSaved(page)
}

async function fillExactSpellBuckets(page: Page) {
  for (let pass = 0; pass < 96; pass += 1) {
    const buckets = page.locator('.spell-bucket')
    let changed = false
    for (let index = 0; index < (await buckets.count()); index += 1) {
      const bucket = buckets.nth(index)
      const counter = (await bucket.locator('.spell-count').innerText()).trim()
      if (counter.includes('max')) continue
      const match = counter.match(/^(\d+)\s*\/\s*(\d+)$/)
      if (!match || Number(match[1]) >= Number(match[2])) continue
      await chooseLowestLevelSpell(page, bucket.getByRole('combobox'))
      changed = true
      break
    }
    if (!changed) return
  }
  throw new Error('Required spell selections did not converge')
}

async function readDraft(request: APIRequestContext, draftId: string): Promise<DraftSnapshot> {
  const response = await request.get(`/api/character-builder/drafts/${draftId}`)
  expect(response.ok()).toBeTruthy()
  return response.json()
}

async function readCharacter(request: APIRequestContext, characterId: string) {
  const response = await request.get(`/api/characters/${characterId}`)
  expect(response.ok()).toBeTruthy()
  return response.json()
}

async function createSimpleCharacter(page: Page, name: string) {
  await page.goto('/characters')
  if ((await page.locator('html').getAttribute('lang')) !== 'en') await setLocale(page, 'en')
  await page.getByRole('button', { name: '+ Create Character' }).click()
  await page.getByLabel('Character name').fill(name)
  await page.getByLabel('Target character level').fill('1')
  await page.getByRole('button', { name: 'Save Basic Details' }).click()

  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Race', 'Human')
  await chooseSearchable(page, 'Background', 'Acolyte')

  await page.getByRole('button', { name: /Abilities/ }).click()
  await page.getByRole('button', { name: 'Save Ability Scores' }).click()
  await chooseSearchable(page, 'Human — Languages', 'Dwarvish')
  const languages = page.locator('.builder-choice').filter({ hasText: 'Acolyte — Languages' })
  await chooseIn(languages, 'Celestial')
  await chooseIn(languages, 'Draconic')

  await page.getByRole('button', { name: /Class/ }).click()
  await chooseSearchable(page, 'Level 1 class', 'Barbarian')
  const startingSkills = page.getByTestId('level-node-1').locator('.progression-choice')
  await chooseIn(startingSkills, 'Skill: Animal Handling')
  await chooseIn(startingSkills, 'Skill: Athletics')

  await page.getByRole('button', { name: /Equipment/ }).click()
  await chooseSearchable(page, /\(a\) a greataxe or \(b\) any martial melee weapon/, 'Greataxe')
  await chooseSearchable(page, /\(a\) two handaxes or \(b\) any simple weapon/, '2 × Handaxe')
  await chooseSearchable(page, 'Acolyte — Starting Equipment', 'Amulet')

  await page.getByRole('button', { name: /Review/ }).click()
  const confirm = page.getByRole('button', { name: 'Confirm & Create Character' })
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(page).toHaveURL(/\/characters\/[0-9a-f-]{36}$/)
  const characterId = page.url().match(/\/characters\/([0-9a-f-]{36})$/)?.[1]
  if (!characterId) throw new Error(`Cannot parse character id from ${page.url()}`)
  return characterId
}

async function resetStateFixture(request: APIRequestContext) {
  const response = await request.patch(`/api/characters/${FIXTURE_ID}/state`, {
    data: {
      current_hp: 51,
      temporary_hp: 7,
      conditions: [{ condition_ref: 'srd5.1:condition:poisoned', note: 'M02-H integrity' }],
      prepared_spell_entry_ids: ['wizard:magic-missile', 'wizard:shield', 'wizard:fireball'],
      spell_slots: {
        '1': { used: 2, remaining: 2 },
        '2': { used: 1, remaining: 2 },
        '3': { used: 1, remaining: 1 },
      },
      resources: { 'wizard:arcane-recovery': { used: 1, remaining: 0 } },
      hit_dice_state: { d10: 4, d6: 3 },
      inventory_state: [
        { entry_id: 'inventory:chain-mail', item_ref: 'srd5.1:equipment:chain-mail', quantity: 1, equipped: true, carried: true },
        { entry_id: 'inventory:shield', item_ref: 'srd5.1:equipment:shield', quantity: 1, equipped: true, carried: true },
        { entry_id: 'inventory:healing-potion', item_ref: 'srd5.1:item:potion-of-healing-common', quantity: 2, equipped: false, carried: true },
      ],
    },
  })
  expect(response.ok()).toBeTruthy()
}

test('M02-H proves full Create -> Confirm -> Sheet survives en -> zh-TW -> reload without domain mutation', async ({ page, request }) => {
  test.slow()
  await page.goto('/')
  await page.evaluate((key) => localStorage.setItem(key, 'en'), LOCALE_STORAGE_KEY)
  await page.reload()

  const characterId = await createSimpleCharacter(page, 'M02-H EN to ZH Hero')
  const before = await readCharacter(request, characterId)
  await setLocale(page, 'zh-TW')
  await expect(page.getByRole('tablist', { name: '角色卡分頁' })).toBeVisible()
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-TW')
  const after = await readCharacter(request, characterId)
  expect(after).toEqual(before)
})

test('M02-H proves full Create -> Confirm -> Sheet survives zh-TW -> en -> reload without domain mutation', async ({ page, request }) => {
  test.slow()
  await page.goto('/')
  await page.evaluate((key) => localStorage.setItem(key, 'en'), LOCALE_STORAGE_KEY)
  await page.reload()

  const characterId = await createSimpleCharacter(page, 'M02-H ZH to EN Hero')
  await setLocale(page, 'zh-TW')
  const before = await readCharacter(request, characterId)
  await setLocale(page, 'en')
  await expect(page.getByRole('tablist', { name: 'Character Sheet tabs' })).toBeVisible()
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  const after = await readCharacter(request, characterId)
  expect(after).toEqual(before)
})

test('M02-H preserves a populated race/subrace/background/class/spells/equipment/roleplay Draft across four switches', async ({ page, request }) => {
  test.slow()
  await page.goto('/')
  await page.evaluate((key) => localStorage.setItem(key, 'en'), LOCALE_STORAGE_KEY)
  await page.goto('/characters')
  await page.getByRole('button', { name: '+ Create Character' }).click()
  await page.getByLabel('Character name').fill('M02-H Complex Draft')
  await page.getByLabel('Target character level').fill('1')
  await page.getByRole('button', { name: 'Save Basic Details' }).click()

  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Race', 'Elf')
  await chooseSearchable(page, 'Subrace', 'Wood Elf')
  await chooseSearchable(page, 'Background', 'Acolyte')

  await page.getByRole('button', { name: /Abilities/ }).click()
  await page.getByRole('button', { name: 'Save Ability Scores' }).click()
  const backgroundLanguages = page.locator('.builder-choice').filter({ hasText: 'Acolyte — Languages' })
  await chooseIn(backgroundLanguages, 'Celestial')
  await chooseIn(backgroundLanguages, 'Draconic')
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  await page.getByRole('button', { name: /Class/ }).click()
  await chooseSearchable(page, 'Level 1 class', 'Wizard')
  await fillEmptyComboboxes(page, page.locator('.level-rail'))

  await page.getByRole('button', { name: /Spellcasting/ }).click()
  await fillExactSpellBuckets(page)

  await page.getByRole('button', { name: /Equipment/ }).click()
  await fillEmptyComboboxes(page, page.locator('.builder-choice-list'))

  const draftId = page.url().match(/\/character-builder\/([0-9a-f-]{36})$/)?.[1]
  if (!draftId) throw new Error(`Cannot parse draft id from ${page.url()}`)
  const beforeRoleplay = await readDraft(request, draftId)
  const roleplayPayload = {
    ...beforeRoleplay.draft.draft_payload,
    roleplay_profile: {
      appearance: 'Silver hair and a travel-stained blue cloak.',
      biography: 'A bilingual M02-H persistence fixture.',
      personality_traits: ['Curious about old ruins.'],
      ideals: ['Knowledge should be shared.'],
      bonds: ['Protects their companions.'],
      flaws: ['Too eager to investigate mysteries.'],
    },
  }
  const patch = await request.patch(`/api/character-builder/drafts/${draftId}`, {
    data: { expected_revision: beforeRoleplay.draft.revision, draft_payload: roleplayPayload },
  })
  expect(patch.ok()).toBeTruthy()
  await page.reload()
  await expectDraftSaved(page)

  const baseline = await readDraft(request, draftId)
  const baselineUrl = page.url()
  const baselineRevision = baseline.draft.revision
  const mutationRequests: string[] = []
  page.on('request', (request) => {
    if (request.url().includes(`/api/character-builder/drafts/${draftId}`) && ['PATCH', 'POST', 'DELETE'].includes(request.method())) {
      mutationRequests.push(`${request.method()} ${request.url()}`)
    }
  })

  for (const locale of ['zh-TW', 'en', 'zh-TW', 'en'] as const) {
    await setLocale(page, locale)
    expect(page.url()).toBe(baselineUrl)
    const snapshot = await readDraft(request, draftId)
    expect(snapshot.draft.revision).toBe(baselineRevision)
    expect(snapshot.draft.draft_payload).toEqual(baseline.draft.draft_payload)
  }
  expect(mutationRequests).toEqual([])
})

test('M02-H preserves HP, Temp HP, conditions, resources, prepared spells and inventory through repeated switches and reload', async ({ page, request }) => {
  await resetStateFixture(request)
  await page.goto(`/characters/${FIXTURE_ID}`)
  const baseline = await readCharacter(request, FIXTURE_ID)

  for (const locale of ['zh-TW', 'en', 'zh-TW', 'en', 'zh-TW'] as const) {
    await setLocale(page, locale)
    const snapshot = await readCharacter(request, FIXTURE_ID)
    expect(snapshot.state).toEqual(baseline.state)
    expect(snapshot.current_version_id).toBe(baseline.current_version_id)
  }

  await page.reload()
  const afterReload = await readCharacter(request, FIXTURE_ID)
  expect(afterReload.state).toEqual(baseline.state)
  expect(afterReload.current_version_id).toBe(baseline.current_version_id)
})
