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
  validation: { issues: Array<{ code: string }> }
}

// Origin selections under test are driven through the real browser; the level
// rail, generic choices and equipment are completed through the same server API
// the UI calls, exactly like the M01-E and M01-L regressions.
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

const STANDARD_ARRAY = {
  strength: 15,
  dexterity: 14,
  constitution: 13,
  intelligence: 12,
  wisdom: 10,
  charisma: 8,
}

const SCAG_TIEFLING_VARIANT = 'scag:race-variant:tiefling-variants'
const ZARIEL_VARIANT = 'mtf:race-variant:zariel-tiefling'

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

function characterId(page: Page): string {
  const match = page.url().match(/\/characters\/([0-9a-f-]{36})$/)
  if (!match) throw new Error(`Not on a character URL: ${page.url()}`)
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

async function completeRequirements(page: Page, level: number) {
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
      method: 'standard_array',
      scores: STANDARD_ARRAY,
      provenance: 'm01-m-playwright',
    },
    level_choices: levelChoices,
  })
  view = await fillGenericChoices(page, view)
  await fillEquipment(page, view)
  await page.reload()
  await expectDraftSaved(page)
}

async function confirmCreate(page: Page, name: string) {
  await page.getByRole('button', { name: /Review/ }).click()
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

async function toggleEquipped(page: Page, itemName: string) {
  await page.getByRole('tab', { name: 'Inventory' }).click()
  const card = page.locator('.inventory-card').filter({ hasText: itemName }).first()
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: /^(Equip|Unequip)$/ }).click()
  await page.getByRole('tab', { name: 'Attributes' }).click()
}

// M-E2E-01
test('M01-M Eladrin keeps its current season in state across a reload', async ({ page }) => {
  test.slow()
  await startDraft(page, 'M01-M Eladrin Hero', 1)
  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Race', 'Elf')
  await chooseSearchable(page, 'Subrace', 'Eladrin')
  await chooseSearchable(page, 'Background', 'Acolyte')
  await completeRequirements(page, 1)
  await confirmCreate(page, 'M01-M Eladrin Hero')

  const season = page.getByTestId('feature-mode-eladrin-season')
  await expect(season).toHaveValue('autumn')

  await season.selectOption('winter')
  await expect(season).toHaveValue('winter')
  // Changing a live mode must not mint a Build Version.
  await expect(page.getByText('Build v1')).toBeVisible()

  const url = page.url()
  await page.reload()
  await expect(page).toHaveURL(url)
  await expect(page.getByTestId('feature-mode-eladrin-season')).toHaveValue('winter')
  await expect(page.getByText('Build v1')).toBeVisible()
})

// M-E2E-02
test('M01-M Githyanki inherits its Gith parent and level-gated psionics', async ({ page }) => {
  test.slow()
  await startDraft(page, 'M01-M Githyanki Hero', 3)
  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Race', 'Gith')
  await chooseSearchable(page, 'Subrace', 'Githyanki')
  await chooseSearchable(page, 'Background', 'Acolyte')
  await completeRequirements(page, 3)
  await confirmCreate(page, 'M01-M Githyanki Hero')

  await expect(page.getByText('Githyanki Psionics', { exact: true })).toBeVisible()
  // Gith INT +1 on top of the standard-array 12, then Githyanki STR +2 on 15.
  await expect(abilityCard(page, 'Intelligence')).toContainText('Score 13')
  await expect(abilityCard(page, 'Strength')).toContainText('Score 17')

  await page.getByRole('tab', { name: 'Spells' }).click()
  const spellList = page.locator('.spell-list')
  await expect(spellList.getByText('Mage Hand', { exact: true })).toBeVisible()
  await expect(spellList.getByText('Jump', { exact: true })).toBeVisible()
  await expect(spellList.getByText('Misty Step', { exact: true })).toHaveCount(0)

  await page.reload()
  await page.getByRole('tab', { name: 'Spells' }).click()
  await expect(page.locator('.spell-list').getByText('Jump', { exact: true })).toBeVisible()
})

// M-E2E-03
test('M01-M Zariel bloodline replaces the standard Tiefling packages', async ({ page }) => {
  test.slow()
  await startDraft(page, 'M01-M Zariel Hero', 3)
  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Race', 'Tiefling')
  await chooseSearchable(page, 'Background', 'Acolyte')
  await chooseSearchable(page, 'Ancestry variant (optional)', 'Zariel Tiefling')
  await chooseSearchable(page, 'Zariel bloodline', 'Legacy of Zariel')
  await completeRequirements(page, 3)
  await confirmCreate(page, 'M01-M Zariel Hero')

  await expect(page.getByText('Legacy of Zariel', { exact: true })).toBeVisible()
  await expect(page.getByText('Infernal Legacy', { exact: true })).toHaveCount(0)
  // Zariel is STR +1 / CHA +2: the standard Intelligence +1 must be gone.
  await expect(abilityCard(page, 'Strength')).toContainText('Score 16')
  await expect(abilityCard(page, 'Charisma')).toContainText('Score 10')
  await expect(abilityCard(page, 'Intelligence')).toContainText('Score 12')

  const url = page.url()
  await page.reload()
  await expect(page).toHaveURL(url)
  await expect(page.getByText('Legacy of Zariel', { exact: true })).toBeVisible()
  await expect(abilityCard(page, 'Strength')).toContainText('Score 16')
})

// M-E2E-04
test('M01-M Winged Tiefling loses its flight only while heavy armor is worn', async ({ page }) => {
  test.slow()
  await startDraft(page, 'M01-M Winged Hero', 1)
  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Race', 'Tiefling')
  await chooseSearchable(page, 'Background', 'Acolyte')
  await chooseSearchable(page, 'Ancestry variant (optional)', 'SCAG Tiefling Variants')
  await chooseSearchable(page, 'Tiefling ability package', 'Feral (DEX +2, INT +1)')
  await chooseSearchable(page, 'Tiefling legacy', 'Winged')
  await completeRequirements(page, 1)
  await confirmCreate(page, 'M01-M Winged Hero')

  // Feral replaces the standard package: DEX +2 rather than CHA +2.
  await expect(abilityCard(page, 'Dexterity')).toContainText('Score 16')
  await expect(abilityCard(page, 'Charisma')).toContainText('Score 8')
  await expect(page.getByTestId('movement-fly')).toContainText('30')

  await toggleEquipped(page, 'Chain Mail')
  await expect(page.getByTestId('movement-fly')).toHaveCount(0)
  await expect(page.getByText('Build v1')).toBeVisible()

  await toggleEquipped(page, 'Chain Mail')
  await expect(page.getByTestId('movement-fly')).toContainText('30')

  const url = page.url()
  await page.reload()
  await expect(page).toHaveURL(url)
  await expect(page.getByTestId('movement-fly')).toContainText('30')
  await expect(page.getByText('Build v1')).toBeVisible()
})

// M-E2E-05
test('M01-M rejects a forged MTF bloodline plus SCAG variant payload', async ({ page }) => {
  test.slow()
  await startDraft(page, 'M01-M Forged Hero', 1)
  await page.getByRole('button', { name: /Origin/ }).click()
  await chooseSearchable(page, 'Race', 'Tiefling')
  await chooseSearchable(page, 'Background', 'Acolyte')
  await chooseSearchable(page, 'Ancestry variant (optional)', 'Zariel Tiefling')
  await chooseSearchable(page, 'Zariel bloodline', 'Legacy of Zariel')
  await completeRequirements(page, 1)

  // The UI never offers the SCAG groups while an MTF bloodline is selected.
  await expect(page.getByRole('combobox', { name: 'Tiefling ability package' })).toHaveCount(0)

  const before = await getView(page)
  const forgedId = `race-variant:${SCAG_TIEFLING_VARIANT}:ability-package`
  const after = await patchView(page, before, {
    choice_selections: {
      ...(before.draft.draft_payload.choice_selections ?? {}),
      [forgedId]: {
        choice_id: forgedId,
        source_ref: SCAG_TIEFLING_VARIANT,
        selected_option_ids: ['feral'],
      },
    },
  })

  expect(after.validation.issues.map((issue) => issue.code)).toContain(
    'cross_variant_choice_selection',
  )

  const confirm = await page.request.post(
    `/api/character-builder/drafts/${after.draft.id}/confirm`,
    { data: { expected_revision: after.draft.revision } },
  )
  expect(confirm.status()).toBe(422)

  // Zero side effect: the rejected draft created no character.
  await page.goto('/characters')
  await expect(page.getByRole('link', { name: 'M01-M Forged Hero' })).toHaveCount(0)
})
