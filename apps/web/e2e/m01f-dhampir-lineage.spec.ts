import { expect, test, type APIResponse, type Page } from '@playwright/test'

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

type ConfirmResult = {
  character_id: string
  current_version_id: string
  version_no: number
}

const DHAMPIR = 'vrgr:lineage:dhampir'
const HALF_ELF = 'srd5.1:race:half-elf'

const DIRECT_SOURCES = new Set([
  'content:race',
  'content:race-variant',
  'content:lineage',
  'content:background',
  'content:alignment',
  'content:subrace',
  'content:subclass',
  'content:class',
  'builder:ability-generation',
  'equipment',
])

async function json<T>(response: APIResponse): Promise<T> {
  if (!response.ok()) throw new Error(`${response.status()} ${await response.text()}`)
  return response.json() as Promise<T>
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
      if (option?.reference_id && option.category !== 'ability_bonus') {
        result.add(option.reference_id)
      }
    }
  }
  return result
}

async function patchView(
  page: Page,
  view: BuilderView,
  draftPayload: Record<string, unknown>,
): Promise<BuilderView> {
  return json<BuilderView>(
    await page.request.patch(`/api/character-builder/drafts/${view.draft.id}`, {
      data: {
        expected_revision: view.draft.revision,
        draft_payload: draftPayload,
      },
    }),
  )
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
        DIRECT_SOURCES.has(choice.option_source ?? '')
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
        if (option.reference_id && option.category !== 'ability_bonus') {
          used.add(option.reference_id)
        }
        if (selected.length === choice.choose_count) break
      }

      if (selected.length < choice.choose_count && choice.allow_duplicates) {
        const legal = choice.options.filter((option) => !option.disabled_reason)
        while (legal.length && selected.length < choice.choose_count) {
          selected.push(legal[0].option_id)
        }
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
  throw new Error('M01-F generic choices did not converge')
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
      const selected = choice.options
        .filter((option) => !option.disabled_reason)
        .slice(0, choice.choose_count)
        .map((option) => option.option_id)
      expect(selected.length, choice.label).toBe(choice.choose_count)
      selections[choice.choice_id] = selected
      changed = true
    }

    if (!changed) return view
    view = await patchView(page, view, { starting_equipment_choices: selections })
  }
  throw new Error('M01-F equipment choices did not converge')
}

async function createDraft(page: Page, name: string, lineage: boolean): Promise<BuilderView> {
  const payload: Record<string, unknown> = {
    basic: { name },
    target_level: 1,
    race_selection: { reference_id: HALF_ELF },
    background_selection: { reference_id: 'srd5.1:background:acolyte' },
    ability_generation: {
      method: 'standard_array',
      scores: {
        strength: 15,
        dexterity: 14,
        constitution: 13,
        intelligence: 12,
        wisdom: 10,
        charisma: 8,
      },
      provenance: 'm01-f-playwright',
    },
    level_choices: [
      {
        character_level: 1,
        class_ref: 'srd5.1:class:fighter',
        hp_method: 'first_level',
        hp_base_gain: 10,
      },
    ],
  }
  if (lineage) payload.lineage_selection = { reference_id: DHAMPIR }

  let view = await json<BuilderView>(
    await page.request.post('/api/character-builder/drafts', {
      data: { draft_payload: payload },
    }),
  )
  view = await fillGenericChoices(page, view)
  return fillEquipment(page, view)
}

async function confirm(page: Page, view: BuilderView): Promise<ConfirmResult> {
  const review = await json<{ can_confirm: boolean; issues: unknown[] }>(
    await page.request.get(`/api/character-builder/drafts/${view.draft.id}/review`),
  )
  expect(review.can_confirm, JSON.stringify(review.issues)).toBe(true)
  return json<ConfirmResult>(
    await page.request.post(`/api/character-builder/drafts/${view.draft.id}/confirm`),
  )
}

async function transformToDhampir(page: Page, characterId: string): Promise<ConfirmResult> {
  let view = await json<BuilderView>(
    await page.request.post(`/api/character-builder/characters/${characterId}/drafts`, {
      data: { mode: 'build_edit' },
    }),
  )
  view = await patchView(page, view, {
    lineage_selection: { reference_id: DHAMPIR },
  })
  view = await fillGenericChoices(page, view)
  return confirm(page, view)
}

test('M01-F Direct Dhampir Create reaches the Character Sheet', async ({ page }) => {
  test.slow()
  const created = await confirm(page, await createDraft(page, 'M01-F Direct E2E', true))

  await page.goto(`/characters/${created.character_id}`)
  await expect(page.getByRole('heading', { name: 'M01-F Direct E2E' })).toBeVisible()
  await expect(page.getByText('Build v1')).toBeVisible()
  await expect(page.getByTestId('movement-walk')).toContainText('35')
  await expect(page.getByTestId('movement-climb')).toContainText('35')
})

test('M01-F Existing Character transforms to Dhampir Build v2', async ({ page }) => {
  test.slow()
  const created = await confirm(page, await createDraft(page, 'M01-F Transform E2E', false))
  const transformed = await transformToDhampir(page, created.character_id)
  expect(transformed.version_no).toBe(2)

  await page.goto(`/characters/${created.character_id}`)
  await expect(page.getByRole('heading', { name: 'M01-F Transform E2E' })).toBeVisible()
  await expect(page.getByText('Build v2')).toBeVisible()
  await expect(page.getByTestId('movement-walk')).toContainText('35')
})

test('M01-F reload keeps Dhampir and Version History remains immutable', async ({ page }) => {
  test.slow()
  const created = await confirm(page, await createDraft(page, 'M01-F History E2E', false))
  await transformToDhampir(page, created.character_id)

  await page.goto(`/characters/${created.character_id}`)
  await expect(page.getByText('Build v2')).toBeVisible()
  const url = page.url()
  await page.reload()
  await expect(page).toHaveURL(url)
  await expect(page.getByText('Build v2')).toBeVisible()
  await expect(page.getByTestId('movement-walk')).toContainText('35')

  const history = await json<Array<{
    version_no: number
    version_kind: string
    is_current: boolean
  }>>(
    await page.request.get(`/api/characters/${created.character_id}/versions`),
  )
  expect(history.map((entry) => entry.version_no)).toEqual([1, 2])
  expect(history.map((entry) => entry.version_kind)).toEqual(['create', 'build_edit'])
  expect(history.map((entry) => entry.is_current)).toEqual([false, true])

  const v1 = await json<{ build: { lineage_ref?: string | null } }>(
    await page.request.get(`/api/characters/${created.character_id}/versions/1`),
  )
  const v2 = await json<{ build: { lineage_ref?: string | null } }>(
    await page.request.get(`/api/characters/${created.character_id}/versions/2`),
  )
  expect(v1.build.lineage_ref ?? null).toBeNull()
  expect(v2.build.lineage_ref).toBe(DHAMPIR)
})
