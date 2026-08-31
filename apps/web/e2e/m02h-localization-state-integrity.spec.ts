import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

const FIXTURE_ID = '00000000-0000-4000-8000-0000000000e0'
const LOCALE_STORAGE_KEY = 'adventure-table.locale'

type Locale = 'zh-TW' | 'en'

type DraftSnapshot = {
  draft: {
    revision: number
    draft_payload: Record<string, unknown>
  }
}

type CreateFlowFixture = {
  createCharacter: string
  characterName: string
  targetLevel: string
  saveBasic: string
  originStep: RegExp
  raceLabel: string
  raceValue: string
  backgroundLabel: string
  backgroundValue: string
  backgroundSource: string
  abilitiesStep: RegExp
  saveAbilities: string
  humanLanguagesLabel: string
  dwarvish: string
  backgroundLanguagesText: string
  addSelection: string
  celestial: string
  draconic: string
  classStep: RegExp
  levelOneClass: string
  barbarian: string
  animalHandling: string
  athletics: string
  equipmentStep: RegExp
  greataxeChoice: RegExp
  greataxe: string
  handaxeChoice: RegExp
  handaxes: string
  acolyteEquipment: string
  amulet: string
  reviewStep: RegExp
  confirm: string
}

const CREATE_FLOW: Record<Locale, CreateFlowFixture> = {
  en: {
    createCharacter: '+ Create Character',
    characterName: 'Character name',
    targetLevel: 'Target character level',
    saveBasic: 'Save Basic Details',
    originStep: /Origin/,
    raceLabel: 'Race',
    raceValue: 'Human',
    backgroundLabel: 'Background',
    backgroundValue: 'Acolyte',
    backgroundSource: 'SRD 5.1',
    abilitiesStep: /Abilities/,
    saveAbilities: 'Save Ability Scores',
    humanLanguagesLabel: 'Human — Languages',
    dwarvish: 'Dwarvish',
    backgroundLanguagesText: 'Acolyte — Languages',
    addSelection: 'Add selection',
    celestial: 'Celestial',
    draconic: 'Draconic',
    classStep: /Class/,
    levelOneClass: 'Level 1 class',
    barbarian: 'Barbarian',
    animalHandling: 'Skill: Animal Handling',
    athletics: 'Skill: Athletics',
    equipmentStep: /Equipment/,
    greataxeChoice: /\(a\) a greataxe or \(b\) any martial melee weapon/,
    greataxe: 'Greataxe',
    handaxeChoice: /\(a\) two handaxes or \(b\) any simple weapon/,
    handaxes: '2 × Handaxe',
    acolyteEquipment: 'Acolyte — Starting Equipment',
    amulet: 'Amulet',
    reviewStep: /Review/,
    confirm: 'Confirm & Create Character',
  },
  'zh-TW': {
    createCharacter: '＋ 建立角色',
    characterName: '角色名稱',
    targetLevel: '目標角色等級',
    saveBasic: '儲存基本資料',
    originStep: /出身/,
    raceLabel: '種族',
    raceValue: '人類',
    backgroundLabel: '背景',
    backgroundValue: '侍僧',
    backgroundSource: 'SRD 5.1',
    abilitiesStep: /屬性/,
    saveAbilities: '儲存屬性值',
    humanLanguagesLabel: '人類 — 語言',
    dwarvish: '矮人語',
    backgroundLanguagesText: '侍僧 — 語言',
    addSelection: '新增選項',
    celestial: '天界語',
    draconic: '龍語',
    classStep: /職業/,
    levelOneClass: '第 1 級職業',
    barbarian: '野蠻人',
    animalHandling: '技能：馴獸',
    athletics: '技能：運動',
    equipmentStep: /裝備/,
    greataxeChoice: /巨斧|軍用近戰武器/,
    greataxe: '巨斧',
    handaxeChoice: /兩把手斧|簡易武器/,
    handaxes: '2 × 手斧',
    acolyteEquipment: '侍僧 — 起始裝備',
    amulet: '護符',
    reviewStep: /檢視/,
    confirm: '確認並建立角色',
  },
}

async function setLocale(page: Page, locale: Locale) {
  await page.getByTestId(`locale-option-${locale}`).click()
  await expect(page.locator('html')).toHaveAttribute('lang', locale)
}

async function expectDraftSaved(page: Page) {
  await expect(page.getByText(/Saved on server|已儲存至伺服器/)).toBeVisible()
}

async function chooseOption(page: Page, input: Locator, value: string, source?: string) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  await input.fill(value)
  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error(`Combobox for "${value}" has no aria-controls listbox`)
  const listbox = page.locator(`[id="${listboxId}"]`)
  let option = listbox.getByRole('option').filter({ has: listbox.getByText(value, { exact: true }) })
  if (source) {
    option = option.filter({
      has: listbox.getByText(source, { exact: true }),
    })
  }
  await expect(option).toHaveCount(1)
  await option.click()
  await expect(listbox).toBeHidden()
  await expectDraftSaved(page)
}

async function chooseSearchable(
  page: Page,
  label: string | RegExp,
  value: string,
  source?: string,
) {
  await chooseOption(page, page.getByRole('combobox', { name: label }), value, source)
}

async function chooseIn(container: Locator, addSelectionLabel: string, value: string) {
  await chooseOption(
    container.page(),
    container.getByRole('combobox', { name: addSelectionLabel }),
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
  await input.press('ArrowDown')
  await expect(input).toHaveAttribute('aria-expanded', 'true')
  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error('Spell combobox has no aria-controls listbox')
  const listbox = page.locator(`[id="${listboxId}"]`)
  await expect(listbox).toBeVisible()
  const option = listbox.locator('[role="option"]:not([disabled])').first()
  await expect(option).toBeVisible()
  await option.click()
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

async function createSimpleCharacter(page: Page, name: string, locale: Locale) {
  const fixture = CREATE_FLOW[locale]
  await page.goto('/characters')
  if ((await page.locator('html').getAttribute('lang')) !== locale) await setLocale(page, locale)
  await expect(page.locator('html')).toHaveAttribute('lang', locale)

  await page.getByRole('button', { name: fixture.createCharacter }).click()
  await expect(page.locator('html')).toHaveAttribute('lang', locale)
  await page.getByLabel(fixture.characterName).fill(name)
  await page.getByLabel(fixture.targetLevel).fill('1')
  await page.getByRole('button', { name: fixture.saveBasic }).click()

  await page.locator('.builder-rail').getByRole('button', { name: fixture.originStep }).click()
  await chooseSearchable(page, fixture.raceLabel, fixture.raceValue)
  await chooseSearchable(
    page,
    fixture.backgroundLabel,
    fixture.backgroundValue,
    fixture.backgroundSource,
  )

  await page.locator('.builder-rail').getByRole('button', { name: fixture.abilitiesStep }).click()
  await page.getByRole('button', { name: fixture.saveAbilities }).click()
  await chooseSearchable(page, fixture.humanLanguagesLabel, fixture.dwarvish)
  const languages = page
    .locator('.builder-choice')
    .filter({ hasText: fixture.backgroundLanguagesText })
  await chooseIn(languages, fixture.addSelection, fixture.celestial)
  await chooseIn(languages, fixture.addSelection, fixture.draconic)

  await page.locator('.builder-rail').getByRole('button', { name: fixture.classStep }).click()
  await chooseSearchable(page, fixture.levelOneClass, fixture.barbarian)
  const startingSkills = page.getByTestId('level-node-1').locator('.progression-choice')
  await chooseIn(startingSkills, fixture.addSelection, fixture.animalHandling)
  await chooseIn(startingSkills, fixture.addSelection, fixture.athletics)

  await page.locator('.builder-rail').getByRole('button', { name: fixture.equipmentStep }).click()
  await chooseSearchable(page, fixture.greataxeChoice, fixture.greataxe)
  await chooseSearchable(page, fixture.handaxeChoice, fixture.handaxes)
  await chooseSearchable(page, fixture.acolyteEquipment, fixture.amulet)

  await page.locator('.builder-rail').getByRole('button', { name: fixture.reviewStep }).click()
  await expect(page.locator('html')).toHaveAttribute('lang', locale)
  const confirm = page.getByRole('button', { name: fixture.confirm })
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(page).toHaveURL(/\/characters\/[0-9a-f-]{36}$/)
  await expect(page.locator('html')).toHaveAttribute('lang', locale)
  const characterId = page.url().match(/\/characters\/([0-9a-f-]{36})$/)?.[1]
  if (!characterId) throw new Error(`Cannot parse character id from ${page.url()}`)
  return characterId
}

async function resetStateFixture(request: APIRequestContext) {
  const response = await request.patch(`/api/characters/${FIXTURE_ID}/state`, {
    data: {
      current_hp: 51,
      temporary_hp: 7,
      conditions: [
        { condition_ref: 'srd5.1:condition:poisoned', note: 'M02-H integrity' },
      ],
      prepared_spell_entry_ids: ['wizard:magic-missile', 'wizard:shield', 'wizard:fireball'],
      spell_slots: {
        '1': { used: 2, remaining: 2 },
        '2': { used: 1, remaining: 2 },
        '3': { used: 1, remaining: 1 },
      },
      resources: { 'wizard:arcane-recovery': { used: 1, remaining: 0 } },
      hit_dice_state: { d10: 4, d6: 3 },
      inventory_state: [
        {
          entry_id: 'inventory:chain-mail',
          item_ref: 'srd5.1:equipment:chain-mail',
          quantity: 1,
          equipped: true,
          carried: true,
        },
        {
          entry_id: 'inventory:shield',
          item_ref: 'srd5.1:equipment:shield',
          quantity: 1,
          equipped: true,
          carried: true,
        },
        {
          entry_id: 'inventory:healing-potion',
          item_ref: 'srd5.1:item:potion-of-healing-common',
          quantity: 2,
          equipped: false,
          carried: true,
        },
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

  const characterId = await createSimpleCharacter(page, 'M02-H EN to ZH Hero', 'en')
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
  await page.evaluate((key) => localStorage.setItem(key, 'zh-TW'), LOCALE_STORAGE_KEY)
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-TW')

  const characterId = await createSimpleCharacter(page, 'M02-H ZH to EN Hero', 'zh-TW')
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
  await chooseSearchable(page, 'Background', 'Acolyte', 'SRD 5.1')

  await page.getByRole('button', { name: /Abilities/ }).click()
  await page.getByRole('button', { name: 'Save Ability Scores' }).click()
  const backgroundLanguages = page
    .locator('.builder-choice')
    .filter({ hasText: 'Acolyte — Languages' })
  await chooseIn(backgroundLanguages, 'Add selection', 'Celestial')
  await chooseIn(backgroundLanguages, 'Add selection', 'Draconic')
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
    data: {
      expected_revision: beforeRoleplay.draft.revision,
      draft_payload: roleplayPayload,
    },
  })
  expect(patch.ok()).toBeTruthy()
  await page.reload()
  await expectDraftSaved(page)

  const baseline = await readDraft(request, draftId)
  const baselineUrl = page.url()
  const baselineRevision = baseline.draft.revision
  const mutationRequests: string[] = []
  page.on('request', (request) => {
    if (
      request.url().includes(`/api/character-builder/drafts/${draftId}`) &&
      ['PATCH', 'POST', 'DELETE'].includes(request.method())
    ) {
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
