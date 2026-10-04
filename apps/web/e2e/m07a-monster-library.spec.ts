import { expect, test, type APIRequestContext, type Page } from './support/roomTest'
import {
  addSeat,
  createCampaign,
  enterAsMember,
  json,
  startSession,
  PLAYWRIGHT_BASE_URL,
  type Lobby,
} from './support/quickCombat'

type MonsterSummary = { ref: string; name: string }
type MonsterDetail = {
  ref: string
  name: string
  revision: number
  rules: Record<string, unknown>
  presentation: Record<string, unknown>
}
type MonsterInstance = { id: string }
type CombatEntryRef = { id: string; monster_instance_id: string | null }

function omitKeys(value: Record<string, unknown>, keys: string[]): Record<string, unknown> {
  return Object.fromEntries(Object.entries(value).filter(([key]) => !keys.includes(key)))
}

test('M07-A Monster Library journey in English: create from built-in, edit only AC, copy, archive, referenced delete error, refresh', async ({
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext

  // 1. Room workspace -> Monster Library button visible for Owner
  await page.goto(`/rooms/${roomId}`)
  const libLink = page.getByRole('link', { name: 'Open Monster Library' })
  await expect(libLink).toBeVisible()
  await libLink.click()
  await expect(page).toHaveURL(new RegExp(`/rooms/${roomId}/monster-library/?$`))

  // 2. Verify "Load more" reveals entries beyond the first page
  await expect(page.getByRole('heading', { name: 'Monster Library', level: 1 })).toBeVisible()
  const loadMoreBtn = page.getByRole('button', { name: 'Load more' })
  await expect(loadMoreBtn).toBeVisible()
  const initialCount = await page.locator('.monster-library__item').count()
  expect(initialCount).toBe(50)
  await loadMoreBtn.click()
  await expect(page.locator('.monster-library__item')).toHaveCount(100)

  // 2b. Find built-in Goblin by typing into the search box
  const searchInput = page.getByPlaceholder('Search by monster name, type, or subtype…')
  await searchInput.fill('Goblin')
  await page.getByRole('button', { name: 'Refresh' }).click()
  const goblinItem = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: /^Goblin$/ }),
  })
  await expect(goblinItem).toBeVisible()
  await goblinItem.click()

  // 3. Detail pane shows read-only built-in detail and "Create custom monster from this"
  await expect(page.locator('.monster-library__builtin-view')).toBeVisible()
  const createFromContentBtn = page.getByRole('button', { name: 'Create custom monster from this' })
  await expect(createFromContentBtn).toBeVisible()
  await createFromContentBtn.click()

  // 4. Modal: specify new custom name
  const nameInput = page.getByLabel('New template name (optional)')
  await nameInput.fill('E2E Goblin Scout')
  await page.getByRole('button', { name: 'Create', exact: true }).click()

  // 5. New custom monster is created, selected, and form is editable
  const customHeading = page.locator('.monster-library__title-block h2').filter({ hasText: /^E2E Goblin Scout$/ })
  await expect(customHeading).toBeVisible()

  // 6. Edit only AC to 16, leaving other abilities untouched
  const acInput = page.getByLabel('Armor Class (AC)')
  await acInput.fill('16')
  await page.getByRole('button', { name: 'Save Changes' }).click()
  await expect(page.locator('.form-success')).toBeVisible()

  // Reload or verify input retained 16 and traits are still present
  await expect(acInput).toHaveValue('16')
  await expect(page.locator('input[value="Nimble Escape"]')).toBeVisible()

  // 7. Copy custom monster
  await page.getByRole('button', { name: 'Copy', exact: true }).click()
  const copyInput = page.getByLabel('New template name (optional)')
  await copyInput.fill('E2E Goblin Veteran')
  await page.getByRole('button', { name: 'Copy Monster', exact: true }).click()

  // 8. Copy appears in the list and can be archived
  const vetItem = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: /^E2E Goblin Veteran$/ }),
  })
  await expect(vetItem).toBeVisible()
  await vetItem.click()

  page.once('dialog', (dialog) => void dialog.accept())
  await page.getByRole('button', { name: 'Archive', exact: true }).click()
  await expect(page.locator('.monster-library__title-block .badge.archived')).toBeVisible()

  // 9. Reference protection: create a combat session referencing E2E Goblin Scout
  // First, find the template id for E2E Goblin Scout
  const scoutItem = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: /^E2E Goblin Scout$/ }),
  })
  await scoutItem.click()

  // Create Campaign and Session, then spawn an instance referencing this custom template
  const campaign = await createCampaign(request, roomId, 'M07A E2E Campaign')
  const ownerLobby = await json<Lobby>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`),
  )
  expect(ownerLobby.caller_access_session_id).not.toBeNull()
  await addSeat(
    request,
    roomId,
    campaign.id,
    'dm',
    ownerLobby.caller_access_session_id!,
    'M07-A',
  )
  const sessionId = await startSession(page, roomId, campaign.id)

  // Grab the custom template ref from the list via API
  const listedCustom = await json<MonsterSummary[]>(
    await request.get(`/api/rooms/${roomId}/monster-library?source=custom`),
  )
  const scoutTemplate = listedCustom.find((m) => m.name === 'E2E Goblin Scout')
  expect(scoutTemplate).toBeDefined()
  const scoutRef = scoutTemplate!.ref

  // Create instance in session referencing custom template
  await json<MonsterInstance>(
    await request.post(
      `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}/monster-instances/from-content`,
      {
        data: {
          content_key: scoutRef,
          name: 'Active Scout Instance',
          idempotency_key: `e2e-m07a-${Date.now()}`,
        },
      },
    ),
  )

  // Navigate back to Monster Library to attempt delete on the referenced template
  await page.goto(`/rooms/${roomId}/monster-library`)
  const searchInputAgain = page.getByPlaceholder('Search by monster name, type, or subtype…')
  await searchInputAgain.fill('E2E Goblin Scout')
  await page.getByRole('button', { name: 'Refresh' }).click()
  const scoutItemRef = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: /^E2E Goblin Scout$/ }),
  })
  await scoutItemRef.click()

  // Now attempt to delete E2E Goblin Scout in UI -> Expect referenced error
  page.once('dialog', (dialog) => void dialog.accept())
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(
    page.getByText('This monster template is in use (referenced by map placements, campaigns, or history) and cannot be deleted; archive it instead.'),
  ).toBeVisible()

  // Form values remain intact
  await expect(acInput).toHaveValue('16')

  // 10. Refresh keeps state
  await page.reload()
  const searchInputReload = page.getByPlaceholder('Search by monster name, type, or subtype…')
  await searchInputReload.fill('E2E Goblin Scout')
  await page.getByRole('button', { name: 'Refresh' }).click()
  const scoutItemAfterReload = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: /^E2E Goblin Scout$/ }),
  })
  await scoutItemAfterReload.click()
  await expect(acInput).toHaveValue('16')
})

test('M07-A editing a custom monster in the UI preserves unedited rules and presentation', async ({
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext
  const templateName = 'Cult Fanatic'

  const created = await json<MonsterDetail>(
    await request.post(`/api/rooms/${roomId}/monster-library/custom/from-content`, {
      data: { content_key: 'srd5.1:monster:cult-fanatic' },
    }),
  )
  const templateId = created.ref.replace(/^custom:/, '')
  const withMultipleSpeeds = await json<MonsterDetail>(
    await request.patch(`/api/rooms/${roomId}/monster-library/custom/${templateId}`, {
      data: {
        expected_revision: created.revision,
        speed: { walk: '30 ft.', fly: '40 ft.', swim: '20 ft.' },
      },
    }),
  )
  const duplicateIndexResponse = await request.patch(
    `/api/rooms/${roomId}/monster-library/custom/${templateId}`,
    {
      data: {
        expected_revision: withMultipleSpeeds.revision,
        traits: [
          { source_index: 1, name: 'Spellcasting' },
          { source_index: 1, name: 'Duplicate' },
        ],
      },
    },
  )
  expect(duplicateIndexResponse.status()).toBe(422)
  const outOfRangeResponse = await request.patch(
    `/api/rooms/${roomId}/monster-library/custom/${templateId}`,
    {
      data: {
        expected_revision: withMultipleSpeeds.revision,
        traits: [{ source_index: 2, name: 'Out of range' }],
      },
    },
  )
  expect(outOfRangeResponse.status()).toBe(422)
  const mixedMarkerResponse = await request.patch(
    `/api/rooms/${roomId}/monster-library/custom/${templateId}`,
    {
      data: {
        expected_revision: withMultipleSpeeds.revision,
        traits: [
          { source_index: 0, name: 'Dark Devotion' },
          { name: 'Spellcasting' },
        ],
      },
    },
  )
  expect(mixedMarkerResponse.status()).toBe(422)
  const structuredEditResponse = await request.patch(
    `/api/rooms/${roomId}/monster-library/custom/${templateId}`,
    {
      data: {
        expected_revision: withMultipleSpeeds.revision,
        actions: [{ source_index: 0, name: 'Multiattack', attack_bonus: 5 }],
      },
    },
  )
  expect(structuredEditResponse.status()).toBe(422)
  const afterRejectedEdits = await json<MonsterDetail>(
    await request.get(
      `/api/rooms/${roomId}/monster-library/${encodeURIComponent(withMultipleSpeeds.ref)}`,
    ),
  )
  expect(afterRejectedEdits.revision).toBe(withMultipleSpeeds.revision)
  expect(afterRejectedEdits.rules).toEqual(withMultipleSpeeds.rules)
  expect(afterRejectedEdits.presentation).toEqual(withMultipleSpeeds.presentation)
  const withUnannotatedTrait = await json<MonsterDetail>(
    await request.patch(`/api/rooms/${roomId}/monster-library/custom/${templateId}`, {
      data: {
        expected_revision: withMultipleSpeeds.revision,
        traits: [
          { source_index: 0, name: 'Dark Devotion' },
          { source_index: 1, name: 'Spellcasting' },
          { source_index: null, name: 'Unannotated Trait' },
        ],
      },
    }),
  )
  const before = await json<MonsterDetail>(
    await request.get(
      `/api/rooms/${roomId}/monster-library/${encodeURIComponent(withUnannotatedTrait.ref)}`,
    ),
  )
  const originalTraits = before.rules.traits as Array<Record<string, unknown>>
  const originalActions = before.rules.actions as Array<Record<string, unknown>>
  expect(originalTraits.some((trait) => trait.name === 'Spellcasting')).toBe(true)
  expect(originalTraits[2]).toEqual({ name: 'Unannotated Trait' })
  expect(originalActions.some((action) => action.name === 'Multiattack')).toBe(true)
  expect(before.rules.speed).toEqual({ walk: '30 ft.', fly: '40 ft.', swim: '20 ft.' })
  expect(before.presentation.ability_names).toBeDefined()
  expect(before.presentation.name_is_custom).toBe(false)
  expect(before.presentation.names).toMatchObject({
    en: 'Cult Fanatic',
    'zh-TW': '邪教狂信者',
  })

  await page.goto(`/rooms/${roomId}/monster-library`)
  await page.locator('.monster-library__filters select').selectOption('custom')
  const searchInput = page.getByPlaceholder('Search by monster name, type, or subtype…')
  await searchInput.fill(templateName)
  await page.getByRole('button', { name: 'Refresh' }).click()
  const item = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: new RegExp(`^${templateName}$`) }),
  })
  await item.click()

  const acInput = page.getByLabel('Armor Class (AC)')
  await acInput.fill('19')
  await page.getByRole('button', { name: 'Save Changes' }).click()
  await expect(page.locator('.form-success')).toBeVisible()

  const afterAcEdit = await json<MonsterDetail>(
    await request.get(
      `/api/rooms/${roomId}/monster-library/${encodeURIComponent(before.ref)}`,
    ),
  )
  expect(afterAcEdit.rules.armor_class).toBe(19)
  expect(omitKeys(afterAcEdit.rules, ['armor_class', 'armor_class_options'])).toEqual(
    omitKeys(before.rules, ['armor_class', 'armor_class_options']),
  )
  expect(afterAcEdit.presentation).toEqual(before.presentation)

  const editedName = 'E2E Cult Fanatic Archivist'
  const editedDescription = 'Field notes for this particular encounter.'
  await page.getByLabel('Name').fill(editedName)
  await page.locator('.monster-library__custom-form textarea').first().fill(editedDescription)
  await page.getByRole('button', { name: 'Save Changes' }).click()
  await expect(page.locator('.form-success')).toBeVisible()

  const afterTextEdit = await json<MonsterDetail>(
    await request.get(
      `/api/rooms/${roomId}/monster-library/${encodeURIComponent(before.ref)}`,
    ),
  )
  expect(afterTextEdit.name).toBe(editedName)
  expect(afterTextEdit.rules.name).toBe(editedName)
  expect(afterTextEdit.rules.description).toBe(editedDescription)
  expect(
    omitKeys(afterTextEdit.rules, ['name', 'description']),
  ).toEqual(omitKeys(afterAcEdit.rules, ['name', 'description']))
  expect(afterTextEdit.presentation.ability_names).toEqual(
    afterAcEdit.presentation.ability_names,
  )

  const editedSpellcastingDescription = 'This caster prepares a different set of spells.'
  await page.getByPlaceholder('Trait description').nth(1).fill(editedSpellcastingDescription)
  await page.getByRole('button', { name: 'Save Changes' }).click()
  await expect(page.locator('.form-success')).toBeVisible()

  const afterTraitEdit = await json<MonsterDetail>(
    await request.get(
      `/api/rooms/${roomId}/monster-library/${encodeURIComponent(before.ref)}`,
    ),
  )
  const textEditTraits = afterTextEdit.rules.traits as Array<Record<string, unknown>>
  const editedTraits = structuredClone(textEditTraits)
  const spellcastingIndex = editedTraits.findIndex((trait) => trait.name === 'Spellcasting')
  expect(spellcastingIndex).toBeGreaterThanOrEqual(0)
  editedTraits[spellcastingIndex] = {
    ...editedTraits[spellcastingIndex],
    desc: editedSpellcastingDescription,
  }
  expect(afterTraitEdit.rules.traits).toEqual(editedTraits)
  expect(afterTraitEdit.rules.actions).toEqual(afterTextEdit.rules.actions)
  expect(afterTraitEdit.presentation.ability_names).toEqual(
    afterTextEdit.presentation.ability_names,
  )

  // Removing the first visible row must keep the next row's original structure and locale name.
  const editRows = page.locator('.monster-library__item-edit-row')
  await editRows.nth(0).getByRole('button', { name: 'Remove' }).click()
  await editRows.nth(2).getByRole('button', { name: 'Remove' }).click()
  await page.getByRole('button', { name: 'Save Changes' }).click()
  await expect(page.locator('.form-success')).toBeVisible()

  const afterRemoval = await json<MonsterDetail>(
    await request.get(
      `/api/rooms/${roomId}/monster-library/${encodeURIComponent(before.ref)}`,
    ),
  )
  expect(afterRemoval.rules.traits).toEqual([
    editedTraits[spellcastingIndex],
    editedTraits[2],
  ])
  expect(afterRemoval.rules.actions).toEqual([
    (afterTextEdit.rules.actions as Array<Record<string, unknown>>)[1],
  ])
  expect(afterRemoval.presentation.ability_names).toMatchObject({
    traits: [{ en: 'Spellcasting', 'zh-TW': '施法' }, {}],
    actions: [{ en: 'Dagger', 'zh-TW': '匕首' }],
  })

  const editedSpellcastingName = 'Arcane Spellcasting'
  await page.getByPlaceholder('Trait name').first().fill(editedSpellcastingName)
  await page.getByRole('button', { name: 'Save Changes' }).click()
  await expect(page.locator('.form-success')).toBeVisible()

  const afterTraitRename = await json<MonsterDetail>(
    await request.get(
      `/api/rooms/${roomId}/monster-library/${encodeURIComponent(before.ref)}`,
    ),
  )
  const remainingTraits = afterRemoval.rules.traits as Array<Record<string, unknown>>
  expect(afterTraitRename.rules.traits).toEqual([
    { ...remainingTraits[0], name: editedSpellcastingName },
    remainingTraits[1],
  ])
  const renamedAbilityNames = afterTraitRename.presentation.ability_names as Record<
    string,
    Array<Record<string, string>>
  >
  expect(renamedAbilityNames.traits).toEqual([{}, {}])
  expect(renamedAbilityNames.actions).toEqual(
    (afterRemoval.presentation.ability_names as Record<string, unknown[]>).actions,
  )
})

test('M07-A Monster Library in zh-TW: built-in shows Chinese names and English desc with label, search ignores desc words', async ({
  page,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext

  // Set locale in browser localStorage
  await page.goto('/')
  await page.evaluate(
    ({ room }) => {
      window.localStorage.setItem('adventure-table.recent-rooms.v1', JSON.stringify([room]))
      window.localStorage.setItem('adventure-table.locale', 'zh-TW')
      window.sessionStorage.setItem('adventure-table.active-room.v1', room.roomId)
    },
    {
      room: {
        roomId,
        code: roomContext.code,
        name: roomContext.name,
        accessToken: roomContext.accessToken,
        authority: roomContext.authority,
      },
    },
  )

  await page.goto(`/rooms/${roomId}/monster-library`)
  await expect(page.getByRole('heading', { name: '怪物庫', level: 1 })).toBeVisible()

  // Find built-in Goblin by typing into the search box (displays as '地精' in zh-TW)
  const searchInput = page.getByPlaceholder('搜尋怪物名稱、類型或子類型…')
  await searchInput.fill('地精')
  await page.getByRole('button', { name: '重新整理' }).click()

  const goblinItem = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: /^地精$/ }),
  })
  await expect(goblinItem).toBeVisible()
  await goblinItem.click()

  // Heading and ability names are localized, while ability desc shows English original with label
  await expect(page.locator('.monster-library__title-block h2').filter({ hasText: /^地精$/ })).toBeVisible()
  await expect(page.getByText('迅捷逃逸')).toBeVisible()
  await expect(page.locator('.monster-library__desc-lang-label').first()).toContainText('英文原文')

  // Search by an English description-only word: should NOT match Goblin
  await searchInput.fill('disengage')
  await page.getByRole('button', { name: '重新整理' }).click()

  await expect(page.getByText('找不到符合條件的怪物範本。')).toBeVisible()
  await expect(
    page.locator('.monster-library__item').filter({
      has: page.locator('.monster-library__item-name', { hasText: /^地精$/ }),
    }),
  ).not.toBeVisible()

  // Search by Chinese name: matches Goblin
  await searchInput.fill('地精')
  await page.getByRole('button', { name: '重新整理' }).click()
  await expect(
    page.locator('.monster-library__item').filter({
      has: page.locator('.monster-library__item-name', { hasText: /^地精$/ }),
    }),
  ).toBeVisible()
})

test('M07-D F12 Quick Enemy template opens in the editor and saves only the changed AC', async ({
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext
  const templateName = 'E2E M07D Quick Thug'

  const campaign = await createCampaign(request, roomId, 'M07-D Quick Template Campaign')
  const ownerLobby = await json<Lobby>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`),
  )
  await addSeat(
    request,
    roomId,
    campaign.id,
    'dm',
    ownerLobby.caller_access_session_id!,
    'M07-D',
  )
  const sessionId = await startSession(page, roomId, campaign.id)
  const prefix = `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const idempotency = `e2e-m07d-quick-${Date.now()}`

  // A Quick Enemy instance carries only size/AC/HP/speed (+ optional attack).
  const instance = await json<MonsterInstance>(
    await request.post(`${prefix}/monster-instances/quick-enemy`, {
      data: {
        name: 'Club Thug',
        armor_class: 12,
        max_hp: 11,
        attack: { name: 'Club', attack_bonus: 4, damage: '1d6+2' },
        idempotency_key: `${idempotency}-create`,
      },
    }),
  )
  await json(
    await request.post(`${prefix}/combat/start`, {
      data: { idempotency_key: `${idempotency}-start` },
    }),
  )
  await json(
    await request.post(`${prefix}/combat/entries/monsters`, {
      data: { monster_instance_id: instance.id, idempotency_key: `${idempotency}-add` },
    }),
  )

  // Save the Quick Enemy as a Room template through the combat UI.
  await page.reload()
  const detail = await json<{ entries: CombatEntryRef[] }>(
    await request.get(`${prefix}/combat/detail`),
  )
  const quickEntry = detail.entries.find((e) => e.monster_instance_id === instance.id)!
  expect(quickEntry).toBeDefined()
  const controls = page.locator(`[data-monster-controls="${quickEntry.id}"]`)
  await expect(controls).toBeVisible()
  await controls.locator('[data-monster-template-name]').fill(templateName)
  await controls.locator('[data-monster-save-template]').click()
  await expect(controls.locator('[data-monster-template-notice="success"]')).toBeVisible()

  const stored = await json<MonsterDetail>(
    await request.get(
      `/api/rooms/${roomId}/monster-library/${encodeURIComponent((await json<MonsterSummary[]>(
        await request.get(`/api/rooms/${roomId}/monster-library?source=custom`),
      )).find((m) => m.name === templateName)!.ref)}`,
    ),
  )
  const rulesBefore = stored.rules as Record<string, unknown>
  expect(rulesBefore['armor_class']).toBe(12)
  // The quick-enemy shape has no full ability block, type, or alignment.
  expect(rulesBefore['ability_scores']).toBeUndefined()
  expect(rulesBefore['type']).toBeUndefined()
  expect(rulesBefore['alignment']).toBeUndefined()

  // The template opens in the editor without errors and shows unset fields.
  await page.goto(`/rooms/${roomId}/monster-library`)
  const searchInput = page.getByPlaceholder('Search by monster name, type, or subtype…')
  await searchInput.fill(templateName)
  await page.getByRole('button', { name: 'Refresh' }).click()
  const item = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: new RegExp(`^${templateName}$`) }),
  })
  await item.click()
  const acInput = page.getByLabel('Armor Class (AC)')
  await expect(acInput).toHaveValue('12')
  await expect(page.getByLabel('Type')).toHaveValue('')
  await expect(page.getByLabel('Alignment')).toHaveValue('')

  // Change only AC and save: nothing else in the stored rules may change.
  await acInput.fill('16')
  await page.getByRole('button', { name: 'Save Changes' }).click()
  await expect(page.locator('.form-success')).toBeVisible()

  const storedAfter = await json<MonsterDetail>(
    await request.get(
      `/api/rooms/${roomId}/monster-library/${encodeURIComponent(stored.ref)}`,
    ),
  )
  expect(storedAfter.rules['armor_class']).toBe(16)
  expect(storedAfter.revision).toBeGreaterThan(stored.revision)
  const { armor_class: _beforeAc, ...restBefore } = rulesBefore
  const { armor_class: _afterAc, ...restAfter } = storedAfter.rules as Record<string, unknown>
  expect(restAfter).toEqual(restBefore)

  // Reopening still shows the saved AC with the other fields untouched.
  await page.reload()
  const searchAgain = page.getByPlaceholder('Search by monster name, type, or subtype…')
  await searchAgain.fill(templateName)
  await page.getByRole('button', { name: 'Refresh' }).click()
  const itemAgain = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: new RegExp(`^${templateName}$`) }),
  })
  await itemAgain.click()
  await expect(page.getByLabel('Armor Class (AC)')).toHaveValue('16')
  await expect(page.getByLabel('Type')).toHaveValue('')
})

test('M07-A Member directly visiting /monster-library gets no library data and sees forbidden error', async ({
  browser,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext
  const member = await enterAsMember(request, roomContext, 'M07A Member User')

  const context = await browser.newContext({ baseURL: PLAYWRIGHT_BASE_URL })
  const memberPage = await context.newPage()
  await memberPage.goto('/')
  await memberPage.evaluate(
    ({ room }) => {
      window.localStorage.setItem('adventure-table.recent-rooms.v1', JSON.stringify([room]))
      window.localStorage.setItem('adventure-table.locale', 'en')
      window.sessionStorage.setItem('adventure-table.active-room.v1', room.roomId)
    },
    {
      room: {
        roomId,
        code: roomContext.code,
        name: roomContext.name,
        accessToken: member.access_token,
        authority: member.authority,
      },
    },
  )

  // 1. On room workspace, Monster Library button is NOT visible for member
  await memberPage.goto(`/rooms/${roomId}`)
  await expect(memberPage.getByRole('link', { name: 'Open Monster Library' })).not.toBeVisible()

  // 2. Direct navigation to /monster-library shows forbidden error and NO library data
  await memberPage.goto(`/rooms/${roomId}/monster-library`)
  await expect(
    memberPage.getByText('Only the Room owner or DM can manage the monster library.'),
  ).toBeVisible()
  await expect(memberPage.locator('.monster-library__list')).not.toBeVisible()
  await expect(memberPage.getByRole('button', { name: 'Create Custom Monster' })).not.toBeVisible()

  await context.close()
})
