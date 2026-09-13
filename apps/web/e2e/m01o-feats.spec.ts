// M01-O §10.10 — XGE / TCE feats driven through the Room Character Workspace UI.
//
// Every journey starts from the Room-scoped workshop, drives the builder's
// searchable selects / chip pickers, reads the Review step and the Character
// Sheet, and only falls back to the API for Build-level facts the UI does not
// render (casting ability, spend tags). Inventory completeness is the backend
// verifier's job; these specs cover the O-E2E-01…06 semantics.
import { expect, type Locator, type Page } from '@playwright/test'

import {
  chooseOption,
  chooseRejectedOption,
  confirmCreate,
  expectOptionAbsent,
  expectOptionDisabled,
  finishAndReview,
  finishLevelUp,
  forceLocale,
  goToStep,
  readBuild,
  reviewGrants,
  sheetFeatureChips,
  startCreate,
  startLevelUp,
  expectDraftSaved,
} from './support/builderUi'
import { test } from './support/roomTest'

const DRAGON_HIDE = 'xge:feat:dragon-hide'
const PRODIGY = 'xge:feat:prodigy'
const FIGHTING_INITIATE = 'tce:feat:fighting-initiate'
const ELDRITCH_ADEPT = 'tce:feat:eldritch-adept'
const FEY_TOUCHED = 'tce:feat:fey-touched'
const METAMAGIC_ADEPT = 'tce:feat:metamagic-adept'
const STYLE_DEFENSE = 'srd5.1:feature:fighter-fighting-style-defense'
const STYLE_DUELING = 'srd5.1:feature:fighter-fighting-style-dueling'
const DEVILS_SIGHT = 'srd5.1:feature:eldritch-invocation-devils-sight'
const ARMOR_OF_SHADOWS = 'srd5.1:feature:eldritch-invocation-armor-of-shadows'
const CAREFUL = 'srd5.1:feature:metamagic-careful-spell'
const SUBTLE = 'srd5.1:feature:metamagic-subtle-spell'

function raceFeatSelect(page: Page) {
  return page.getByRole('combobox', { name: /Feat/ }).first()
}

function nestedSelect(page: Page, featName: string, field: string) {
  return page.getByRole('combobox', { name: `${featName} — ${field}` })
}

async function readSheet(request: Parameters<typeof readBuild>[0], characterId: string) {
  const response = await request.get(`/api/characters/${characterId}/sheet`)
  expect(response.ok()).toBeTruthy()
  return response.json()
}

async function expectChipInBothLocales(page: Page, en: string, zh: string) {
  await expect(sheetFeatureChips(page).filter({ hasText: en })).toHaveCount(1)
  await forceLocale(page, 'zh-TW')
  await expect(sheetFeatureChips(page).filter({ hasText: zh })).toHaveCount(1)
  await forceLocale(page, 'en')
}

// O-E2E-01 — XGE racial prerequisite: the wrong ancestry sees the reason, the
// right one takes the feat, and Variant Human counts as Human for Prodigy.
test('O-E2E-01 racial prerequisite gates Dragon Hide by ancestry and normalizes Variant Human', async ({ page, request }) => {
  const name = 'M01-O Dragon Hide'
  await startCreate(page, name, 'Dragonborn', 'Fighter', 4)

  await goToStep(page, 'classRail')
  const asi = page.getByRole('combobox', { name: /4 . ASI or Feat/ })
  await expectOptionDisabled(page, asi, 'Prodigy', 'Requires a specific ancestry.')
  await chooseOption(page, asi, 'Dragon Hide')

  await goToStep(page, 'abilities')
  await chooseOption(page, nestedSelect(page, 'Dragon Hide', 'ability increase'), 'STR +1')

  const { review } = await finishAndReview(page, request)
  expect(review.build_candidate.feat_refs).toEqual([DRAGON_HIDE])
  await expect(reviewGrants(page).filter({ hasText: 'Dragon Hide' })).toHaveCount(1)

  const characterId = await confirmCreate(page, name)
  await expectChipInBothLocales(page, 'Dragon Hide', '龍裔鱗甲')

  const build = await readBuild(request, characterId, 1)
  expect(build.feat_acquisitions[0].selections.ability).toEqual(['ability:strength'])

  // Variant Human: Prodigy opens through ancestry normalization, Dragon Hide stays closed.
  await startCreate(page, 'M01-O Variant Human Gate', 'Variant Human', 'Fighter', 1)
  await goToStep(page, 'abilities')
  await expectOptionDisabled(page, raceFeatSelect(page), 'Dragon Hide', 'Requires a specific ancestry.')
  await chooseOption(page, raceFeatSelect(page), 'Prodigy')
  await expect(nestedSelect(page, 'Prodigy', 'expertise')).toBeVisible()
})

// O-E2E-02 — Prodigy's nested proficiency + expertise show up on Review and the Sheet.
test('O-E2E-02 Prodigy nested skill, tool, language and expertise reach Review and the Sheet', async ({ page, request }) => {
  const name = 'M01-O Prodigy'
  await startCreate(page, name, 'Variant Human', 'Fighter', 1)

  await goToStep(page, 'abilities')
  await chooseOption(page, raceFeatSelect(page), 'Prodigy')
  await chooseOption(page, nestedSelect(page, 'Prodigy', 'skill'), 'Skill: Investigation')
  await chooseOption(page, nestedSelect(page, 'Prodigy', 'tool'), "Thieves' Tools")
  await chooseOption(page, nestedSelect(page, 'Prodigy', 'language'), 'Elvish')
  // The expertise pool is server-built from the skill picked one choice earlier.
  await chooseOption(page, nestedSelect(page, 'Prodigy', 'expertise'), 'Investigation')

  const { review } = await finishAndReview(page, request)
  expect(review.build_candidate.skill_expertise_refs).toEqual(['srd5.1:skill:investigation'])
  for (const label of ['Prodigy', 'Skill: Investigation', "Thieves' Tools", 'Elvish']) {
    await expect(reviewGrants(page).filter({ hasText: label }).first()).toBeVisible()
  }

  const characterId = await confirmCreate(page, name)
  await expectChipInBothLocales(page, 'Prodigy', '奇才')

  const sheet = await readSheet(request, characterId)
  const expertiseBonus = sheet.abilities.intelligence.modifier + 2 * sheet.proficiency_bonus
  expect(sheet.skills.investigation).toBe(expertiseBonus)
  const row = page.locator('.skill-list > div').filter({ hasText: 'Investigation' })
  await expect(row.locator('strong')).toHaveText(expertiseBonus >= 0 ? `+${expertiseBonus}` : String(expertiseBonus))

  const build = readBuild(request, characterId, 1)
  expect((await build).feat_refs).toEqual([PRODIGY])
})

// O-E2E-03 — Fighting Initiate: canonical style pool, duplicate rejection both
// ways, and replacement only at an ASI Level Up. Also the spellcasting gate a
// martial character sees on Eldritch Adept.
test('O-E2E-03 Fighting Initiate excludes the known style and retrains only at an ASI level', async ({ page, request }) => {
  const name = `M01-O Fighting Initiate ${Date.now()}`
  await startCreate(page, name, 'Variant Human', 'Fighter', 1)

  await goToStep(page, 'classRail')
  await chooseOption(page, page.getByRole('combobox', { name: /Fighting Style/ }).first(), 'Fighting Style: Archery')

  await goToStep(page, 'abilities')
  const feat = raceFeatSelect(page)
  await expectOptionDisabled(page, feat, 'Eldritch Adept', 'Requires the ability to cast at least one spell.')
  await chooseOption(page, feat, 'Fighting Initiate')
  const style = nestedSelect(page, 'Fighting Initiate', 'style')
  await expectOptionDisabled(page, style, 'Fighting Style: Archery', 'This fighting style is already known.')
  await chooseOption(page, style, 'Fighting Style: Defense')

  await finishAndReview(page, request)
  const characterId = await confirmCreate(page, name)
  await expect(sheetFeatureChips(page).filter({ hasText: 'Fighting Style: Defense' })).toHaveCount(1)

  // Level 2 grants no ASI: the server refuses the replacement and the UI says so.
  await startLevelUp(page, name, 'Fighter', 2)
  await goToStep(page, 'abilities')
  await chooseRejectedOption(page, nestedSelect(page, 'Fighting Initiate', 'style'), 'Fighting Style: Dueling')
  await page.reload()
  await expectDraftSaved(page)
  await finishLevelUp(page, characterId)

  await startLevelUp(page, name, 'Fighter', 3)
  await finishLevelUp(page, characterId)

  // Level 4 grants an ASI: one replacement is allowed and versioned.
  await startLevelUp(page, name, 'Fighter', 4)
  await chooseOption(page, page.getByRole('combobox', { name: /4 . ASI or Feat/ }), 'Ability Score Improvement')
  await goToStep(page, 'abilities')
  await chooseOption(page, nestedSelect(page, 'Fighting Initiate', 'style'), 'Fighting Style: Dueling')
  await finishLevelUp(page, characterId)

  await expect(sheetFeatureChips(page).filter({ hasText: 'Fighting Style: Dueling' })).toHaveCount(1)
  await expect(sheetFeatureChips(page).filter({ hasText: 'Fighting Style: Defense' })).toHaveCount(0)
  expect((await readBuild(request, characterId, 3)).feature_refs).toContain(STYLE_DEFENSE)
  const versionFour = await readBuild(request, characterId, 4)
  expect(versionFour.feature_refs).toContain(STYLE_DUELING)
  expect(versionFour.feature_refs).not.toContain(STYLE_DEFENSE)
  expect(versionFour.feat_refs).toEqual([FIGHTING_INITIATE])

  await page.goto(`/characters/${characterId}/versions`)
  await expect(page.getByRole('heading', { name: 'Version 1' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Version 4' })).toBeVisible()
})

// O-E2E-04 — Eldritch Adept: a caster passes the gate, prerequisite invocations
// stay Warlock-only, and the invocation can be swapped at the next level.
test('O-E2E-04 Eldritch Adept gates invocations and retrains at the next Level Up', async ({ page, request }) => {
  const name = `M01-O Eldritch Adept ${Date.now()}`
  await startCreate(page, name, 'Variant Human', 'Wizard', 1)

  await goToStep(page, 'abilities')
  await chooseOption(page, raceFeatSelect(page), 'Eldritch Adept')
  const invocation = nestedSelect(page, 'Eldritch Adept', 'invocation')
  await expectOptionDisabled(
    page,
    invocation,
    'Eldritch Invocation: Agonizing Blast',
    'This invocation has a prerequisite that only a qualifying Warlock can meet.',
  )
  await chooseOption(page, invocation, "Eldritch Invocation: Devil's Sight")

  const { review } = await finishAndReview(page, request)
  expect(review.build_candidate.feature_refs).toContain(DEVILS_SIGHT)
  await expect(reviewGrants(page).filter({ hasText: "Devil's Sight" })).toHaveCount(1)

  const characterId = await confirmCreate(page, name)
  await expect(sheetFeatureChips(page).filter({ hasText: "Devil's Sight" })).toHaveCount(1)

  await startLevelUp(page, name, 'Wizard', 2)
  await goToStep(page, 'abilities')
  await chooseOption(page, nestedSelect(page, 'Eldritch Adept', 'invocation'), 'Eldritch Invocation: Armor of Shadows')
  await finishLevelUp(page, characterId)

  await expect(sheetFeatureChips(page).filter({ hasText: 'Armor of Shadows' })).toHaveCount(1)
  await expect(sheetFeatureChips(page).filter({ hasText: "Devil's Sight" })).toHaveCount(0)
  const versionTwo = await readBuild(request, characterId, 2)
  expect(versionTwo.feature_refs).toContain(ARMOR_OF_SHADOWS)
  expect(versionTwo.feature_refs).not.toContain(DEVILS_SIGHT)
  expect(versionTwo.feat_refs).toEqual([ELDRITCH_ADEPT])
})

// O-E2E-05 — Fey Touched: the spell selector is school-filtered and the chosen
// ability drives every feat spell's casting stat.
test('O-E2E-05 Fey Touched filters spells by school and binds casting ability to the chosen score', async ({ page, request }) => {
  const name = 'M01-O Fey Touched'
  await startCreate(page, name, 'Variant Human', 'Wizard', 1)

  await goToStep(page, 'abilities')
  await chooseOption(page, raceFeatSelect(page), 'Fey Touched')
  await chooseOption(page, nestedSelect(page, 'Fey Touched', 'ability increase'), 'WIS +1')
  const spell = nestedSelect(page, 'Fey Touched', 'spell')
  await expectOptionAbsent(page, spell, 'False Life')
  await chooseOption(page, spell, 'Charm Person')

  await finishAndReview(page, request)
  const characterId = await confirmCreate(page, name)
  await expectChipInBothLocales(page, 'Fey Touched', '妖精眷顧')
  await page.getByRole('tab', { name: /Spells/ }).click()
  await expect(page.locator('.spell-list').filter({ hasText: 'Misty Step' })).toHaveCount(1)
  await expect(page.locator('.spell-list').filter({ hasText: 'Charm Person' })).toHaveCount(1)

  const build = await readBuild(request, characterId, 1)
  const featSpells = Object.fromEntries(
    build.spell_access_entries
      .filter((entry: { source_type: string }) => entry.source_type === 'feat')
      .map((entry: { spell_key: string; casting_ability: string }) => [entry.spell_key, entry.casting_ability]),
  )
  expect(featSpells).toEqual({ 'srd5.1:spell:misty-step': 'wisdom', 'srd5.1:spell:charm-person': 'wisdom' })
  expect(build.feat_refs).toEqual([FEY_TOUCHED])

  // Shadow Touched mirrors the filter with the other two schools.
  await startCreate(page, 'M01-O Shadow Touched Filter', 'Variant Human', 'Wizard', 1)
  await goToStep(page, 'abilities')
  await chooseOption(page, raceFeatSelect(page), 'Shadow Touched')
  const shadowSpell = nestedSelect(page, 'Shadow Touched', 'spell')
  await expectOptionAbsent(page, shadowSpell, 'Charm Person')
  await chooseOption(page, shadowSpell, 'False Life')
})

async function metamagicChips(page: Page): Promise<Locator> {
  const picker = page.locator('.builder-choice').filter({
    has: page.locator('.builder-choice__heading', { hasText: 'Metamagic Adept' }),
  })
  await expect(picker).toHaveCount(1)
  return picker.locator('.builder-choice__chips button')
}

async function addMetamagic(page: Page, value: string) {
  const picker = page.locator('.builder-choice').filter({
    has: page.locator('.builder-choice__heading', { hasText: 'Metamagic Adept' }),
  })
  await chooseOption(page, picker.getByRole('combobox'), value)
}

// O-E2E-06 — Metamagic Adept: two distinct options through the chip picker,
// draft reload keeps them, and the Sheet shows the feat-scoped 2-point pool.
test('O-E2E-06 Metamagic Adept keeps two distinct options across reload and shows its restricted pool', async ({ page, request }) => {
  const name = 'M01-O Metamagic Adept'
  await startCreate(page, name, 'Variant Human', 'Wizard', 1)

  await goToStep(page, 'abilities')
  await chooseOption(page, raceFeatSelect(page), 'Metamagic Adept')
  await addMetamagic(page, 'Metamagic: Careful Spell')
  await addMetamagic(page, 'Metamagic: Subtle Spell')
  await expect(await metamagicChips(page)).toHaveCount(2)
  await expect(
    page.locator('.builder-choice__heading', { hasText: 'Metamagic Adept' }).locator('span'),
  ).toHaveText('2 / 2')

  await page.reload()
  await expectDraftSaved(page)
  await goToStep(page, 'abilities')
  await expect(await metamagicChips(page)).toHaveCount(2)
  await expect(await metamagicChips(page)).toContainText(['Careful Spell', 'Subtle Spell'])

  const { review } = await finishAndReview(page, request)
  expect(review.build_candidate.feature_refs).toEqual(expect.arrayContaining([CAREFUL, SUBTLE]))
  await expect(reviewGrants(page).filter({ hasText: 'Careful Spell' })).toHaveCount(1)
  await expect(reviewGrants(page).filter({ hasText: 'Subtle Spell' })).toHaveCount(1)

  const characterId = await confirmCreate(page, name)
  await expectChipInBothLocales(page, 'Metamagic Adept', '超魔學徒')
  const pool = page.locator('.resource-list > div').filter({ hasText: 'Metamagic Adept Sorcery Points' })
  await page.getByRole('tab', { name: /Spells/ }).click()
  await expect(pool.locator('strong')).toHaveText('2 / 2')
  await page.reload()
  await page.getByRole('tab', { name: /Spells/ }).click()
  await expect(pool.locator('strong')).toHaveText('2 / 2')

  const build = await readBuild(request, characterId, 1)
  expect(build.feat_refs).toEqual([METAMAGIC_ADEPT])
  expect(build.feat_resource_grants).toContainEqual(
    expect.objectContaining({
      resource_id: 'metamagic-adept-sorcery-points',
      capacity: 2,
      allowed_spend_tags: ['metamagic'],
      source_ref: METAMAGIC_ADEPT,
    }),
  )
})
