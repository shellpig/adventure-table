import { expect, test, type APIResponse, type Locator, type Page } from '@playwright/test'

type BuilderView = {
  draft: {
    id: string
    revision: number
    draft_payload: {
      choice_selections?: Record<string, {
        choice_id: string
        source_ref?: string | null
        selected_option_ids: string[]
      }>
      starting_equipment_choices?: Record<string, string[]>
    }
  }
  choices: Array<{
    choice_id: string
    label: string
    required: boolean
    choose_count: number
    option_source?: string | null
    source_ref?: string | null
    disabled_reason?: string | null
    allow_duplicates?: boolean
    options: Array<{
      option_id: string
      reference_id?: string | null
      category?: string | null
      disabled_reason?: string | null
    }>
  }>
}

type AbilityScores = {
  strength: number
  dexterity: number
  constitution: number
  intelligence: number
  wisdom: number
  charisma: number
}

// The origin selections under test are driven through the real browser; the
// unrelated level rail, generic choices and equipment are completed through the
// same server API the UI calls, exactly like the M01-E regressions.
const DIRECT_OR_SPECIAL_SOURCES = new Set([
  'content:race',
  'content:race-variant',
  'content:background',
  'content:alignment',
  'content:subrace',
  'content:subclass',
  'content:class',
  'builder:ability-generation',
  'content:race-variant-replacement',
  'content:race-variant-spell',
  'equipment',
])

const STANDARD_ARRAY: AbilityScores = {
  strength: 15,
  dexterity: 14,
  constitution: 13,
  intelligence: 12,
  wisdom: 10,
  charisma: 8,
}

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
  await expect.poll(() => currentDraftRevision(page)).toBeGreaterThan(previousRevision)
  await expectDraftSaved(page)
}

async function chooseOption(page: Page, input: Locator, value: string) {
  await expectDraftSaved(page)
  await expect(input).toBeEnabled()
  const revision = await currentDraftRevision(page)
  await input.fill(value)
  const listboxId = await input.getAttribute('aria-controls')
  if (!listboxId) throw new Error(`Combobox for "${value}" has no aria-controls listbox`)
  const listbox = page.locator(`[id="${listboxId}"]`)
  let option = listbox
    .getByRole('option')
    .filter({ has: page.getByText(value, { exact: true }) })
  if ((await option.count()) > 1) {
    const srdOption = option.filter({
      has: page.getByText('System Reference Document 5.1', { exact: true }),
    })
    if ((await srdOption.count()) === 1) option = srdOption
  }
  await expect(option).toHaveCount(1)
  await option.click()
  await expect(listbox).toBeHidden()
  await waitForDraftRevision(page, revision)
}

async function chooseSearchable(page: Page, label: string | RegExp, value: string) {
  await chooseOption(page, page.getByRole('combobox', { name: label }), value)
}

async function startDraft(page: Page, name: string, level: number) {
  await page.goto('/characters')
  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)
  await page.getByLabel('Character name').fill(name)
  await page.getByLabel('Target character level').fill(String(level))
  await page.getByRole('button', { name: 'Save Basic Details' }).click()
  await expect(page.getByRole('heading', { name }).first()).toBeVisible()
}

function draftId(page: Page): string {
  const match = page.url().match(/\/character-builder\/([0-9a-f-]{36})$/)
  if (!match) throw new Error(`Not on a builder draft URL: ${page.url()}`)
  return match[1]
}

async function json<T>(response: APIResponse): Promise<T> {
  if (!response.ok()) throw new Error(`${response.status()} ${await response.text()}`)
  return response.json() as Promise<T>
}

async function getView(page: Page): Promise<BuilderView> {
  return json<BuilderView>(await page.request.get(`/api/character-builder/drafts/${draftId(page)}`))
}

async function patchView(page: Page, view: BuilderView, draftPayload: Record<string, unknown>) {
  return json<BuilderView>(
    await page.request.patch(`/api/character-builder/drafts/${view.draft.id}`, {
      data: { expected_revision: view.draft.revision, draft_payload: draftPayload },
    }),
  )
}

function selectedRefs(view: BuilderView): Set<string> {
  const result = new Set<string>()
  const choices = new Map(view.choices.map((choice) => [choice.choice_id, choice]))
  for (const [choiceId, selection] of Object.entries(view.draft.draft_payload.choice_selections ?? {})) {
    const choice = choices.get(choiceId)
    if (!choice) continue
    const options = new Map(choice.options.map((option) => [option.option_id, option]))
    for (const selectedId of selection.selected_option_ids) {
      const option = options.get(selectedId)
      if (option?.reference_id && option.category !== 'ability_bonus') result.add(option.reference_id)
    }
  }
  return result
}

async function fillGenericChoices(page: Page, initial: BuilderView): Promise<BuilderView> {
  let view = initial
  for (let round = 0; round < 16; round += 1) {
    const selections = { ...(view.draft.draft_payload.choice_selections ?? {}) }
    const used = selectedRefs(view)
    let changed = false
    for (const choice of view.choices) {
      if (
        !choice.required ||
        choice.disabled_reason ||
        DIRECT_OR_SPECIAL_SOURCES.has(choice.option_source ?? '')
      ) continue
      const current = selections[choice.choice_id]?.selected_option_ids ?? []
      if (current.length === choice.choose_count) continue
      const selected: string[] = []
      for (const option of choice.options) {
        if (option.disabled_reason) continue
        if (
          option.reference_id &&
          option.category !== 'ability_bonus' &&
          used.has(option.reference_id)
        ) continue
        selected.push(option.option_id)
        if (option.reference_id && option.category !== 'ability_bonus') used.add(option.reference_id)
        if (selected.length === choice.choose_count) break
      }
      if (selected.length < choice.choose_count && choice.allow_duplicates) {
        const legal = choice.options.filter((option) => !option.disabled_reason)
        while (legal.length && selected.length < choice.choose_count) selected.push(legal[0].option_id)
      }
      expect(selected.length, choice.label).toBe(choice.choose_count)
      selections[choice.choice_id] = {
        choice_id: choice.choice_id,
        source_ref: choice.source_ref,
        selected_option_ids: selected,
      }
      changed = true
    }
    if (!changed) return view
    view = await patchView(page, view, { choice_selections: selections })
  }
  throw new Error('Generic builder choices did not converge')
}

async function fillEquipment(page: Page, initial: BuilderView): Promise<BuilderView> {
  let view = initial
  for (let round = 0; round < 12; round += 1) {
    const selections = { ...(view.draft.draft_payload.starting_equipment_choices ?? {}) }
    let changed = false
    for (const choice of view.choices) {
      if (choice.option_source !== 'equipment' || choice.disabled_reason) continue
      const current = selections[choice.choice_id] ?? []
      if (current.length === choice.choose_count) continue
      const legal = choice.options.filter((option) => !option.disabled_reason)
      const selected = legal.slice(0, choice.choose_count).map((option) => option.option_id)
      expect(selected.length, choice.label).toBe(choice.choose_count)
      selections[choice.choice_id] = selected
      changed = true
    }
    if (!changed) return view
    view = await patchView(page, view, { starting_equipment_choices: selections })
  }
  throw new Error('Equipment choices did not converge')
}

async function completeRequirements(
  page: Page,
  level: number,
  abilities: { method: 'standard_array' | 'point_buy'; scores: AbilityScores } = {
    method: 'standard_array',
    scores: STANDARD_ARRAY,
  },
) {
  let view = await getView(page)
  const levelChoices = Array.from({ length: level }, (_, index) => ({
    character_level: index + 1,
    class_ref: 'srd5.1:class:fighter',
    hp_method: index === 0 ? 'first_level' : 'fixed_average',
    hp_base_gain: index === 0 ? 10 : 6,
    subclass_ref: index === 2 ? 'srd5.1:subclass:champion' : null,
  }))
  view = await patchView(page, view, {
    ability_generation: {
      method: abilities.method,
      scores: abilities.scores,
      provenance: 'm01-l-playwright',
    },
    level_choices: levelChoices,
  })
  view = await fillGenericChoices(page, view)
  await fillEquipment(page, view)
  await page.reload()
  await expectDraftSaved(page)
}

async function chooseOrigin(page: Page, race: string, subrace?: string) {
  await page.getByTestId('builder-step-origin').click()
  await chooseSearchable(page, 'Race', race)
  if (subrace) await chooseSearchable(page, 'Subrace', subrace)
  await chooseSearchable(page, 'Background', 'Acolyte')
}

async function confirmCreate(page: Page, name: string) {
  await page.getByTestId('builder-step-review').click()
  const confirm = page.getByRole('button', { name: 'Confirm & Create Character' })
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(page).toHaveURL(/\/characters\/[0-9a-f-]{36}$/)
  await expect(page.getByRole('heading', { name })).toBeVisible()
  await expect(page.getByText('Build v1')).toBeVisible()
}

function abilityCard(page: Page, label: string): Locator {
  return page.locator('.ability-card').filter({ hasText: label })
}

test('M01-L Lizardfolk keeps a swim speed and Natural Armor across reload', async ({ page }) => {
  test.slow()
  await startDraft(page, 'M01-L Lizardfolk Hero', 1)
  await chooseOrigin(page, 'Lizardfolk')
  await completeRequirements(page, 1)
  await confirmCreate(page, 'M01-L Lizardfolk Hero')

  await expect(page.getByText('Natural Armor', { exact: true })).toBeVisible()
  await expect(page.getByTestId('movement-walk')).toContainText('30')
  await expect(page.getByTestId('movement-swim')).toContainText('30')
  await expect(page.getByTestId('movement-climb')).toHaveCount(0)
  // Unarmoured Lizardfolk: 13 + the standard-array DEX 14 modifier.
  await expect(page.getByTestId('header-ac')).toHaveText('15')

  const url = page.url()
  await page.reload()
  await expect(page).toHaveURL(url)
  await expect(page.getByTestId('movement-swim')).toContainText('30')
  await expect(page.getByTestId('header-ac')).toHaveText('15')
})

test('M01-L Kobold applies a negative racial modifier below the Point Buy minimum', async ({ page }) => {
  test.slow()
  await startDraft(page, 'M01-L Kobold Hero', 1)
  await chooseOrigin(page, 'Kobold')
  await completeRequirements(page, 1, {
    method: 'point_buy',
    scores: {
      strength: 8,
      dexterity: 15,
      constitution: 15,
      intelligence: 15,
      wisdom: 8,
      charisma: 8,
    },
  })
  await confirmCreate(page, 'M01-L Kobold Hero')

  const strength = abilityCard(page, 'Strength')
  await expect(strength).toContainText('Score 6')
  await expect(strength).toContainText('-2')
  await expect(strength).not.toContainText('+-2')
  await expect(abilityCard(page, 'Dexterity')).toContainText('Score 17')

  const url = page.url()
  await page.reload()
  await expect(page).toHaveURL(url)
  await expect(abilityCard(page, 'Strength')).toContainText('Score 6')
})

test('M01-L Triton racial spell access honours the character level gate', async ({ page }) => {
  test.slow()
  await startDraft(page, 'M01-L Triton Hero', 3)
  await chooseOrigin(page, 'Triton')
  await completeRequirements(page, 3)
  await confirmCreate(page, 'M01-L Triton Hero')

  await expect(page.getByText('Control Air and Water', { exact: true })).toBeVisible()
  await expect(page.getByTestId('movement-swim')).toContainText('30')

  await page.getByRole('tab', { name: 'Spells' }).click()
  const spellList = page.locator('.spell-list')
  await expect(spellList.getByText('Fog Cloud', { exact: true })).toBeVisible()
  await expect(spellList.getByText('Gust of Wind', { exact: true })).toBeVisible()
  await expect(spellList.getByText('Wall of Water', { exact: true })).toHaveCount(0)

  await page.reload()
  await page.getByRole('tab', { name: 'Spells' }).click()
  await expect(page.locator('.spell-list').getByText('Gust of Wind', { exact: true })).toBeVisible()
})

test('M01-L Deep Gnome inherits its Gnome parent grants exactly once', async ({ page }) => {
  test.slow()
  await startDraft(page, 'M01-L Deep Gnome Hero', 1)
  await chooseOrigin(page, 'Gnome', 'Deep Gnome (Svirfneblin)')
  await completeRequirements(page, 1)
  await confirmCreate(page, 'M01-L Deep Gnome Hero')

  await expect(page.getByText('Superior Darkvision', { exact: true })).toBeVisible()
  await expect(page.getByText('Stone Camouflage', { exact: true })).toBeVisible()
  // Gnome INT +2 applied once on top of the standard-array 12, plus Deep Gnome DEX +1.
  await expect(abilityCard(page, 'Intelligence')).toContainText('Score 14')
  await expect(abilityCard(page, 'Dexterity')).toContainText('Score 15')
  await expect(page.getByTestId('movement-walk')).toContainText('25')

  const url = page.url()
  await page.reload()
  await expect(page).toHaveURL(url)
  await expect(abilityCard(page, 'Intelligence')).toContainText('Score 14')
})
