import { expect, test } from '@playwright/test'
import type { APIRequestContext } from '@playwright/test'

const FIXTURE_ID = '00000000-0000-4000-8000-0000000000e0'
const CHARACTER_URL = `/characters/${FIXTURE_ID}`

async function resetFixture(request: APIRequestContext) {
  const response = await request.patch(`/api/characters/${FIXTURE_ID}/state`, {
    data: {
      current_hp: 74,
      temporary_hp: 0,
      conditions: [],
      prepared_spell_entry_ids: ['wizard:magic-missile', 'wizard:shield', 'wizard:fireball'],
      spell_slots: {
        '1': { used: 1, remaining: 3 },
        '2': { used: 0, remaining: 3 },
        '3': { used: 1, remaining: 1 },
      },
      resources: { 'wizard:arcane-recovery': { used: 0, remaining: 1 } },
      hit_dice_state: { d10: 5, d6: 5 },
      inventory_state: [
        { entry_id: 'inventory:chain-mail', item_ref: 'srd5.1:equipment:chain-mail', quantity: 1, equipped: true, carried: true },
        { entry_id: 'inventory:shield', item_ref: 'srd5.1:equipment:shield', quantity: 1, equipped: true, carried: true },
        { entry_id: 'inventory:longsword', item_ref: 'srd5.1:equipment:longsword', quantity: 1, equipped: true, carried: true },
        { entry_id: 'inventory:healing-potion', item_ref: 'srd5.1:item:potion-of-healing-common', quantity: 2, equipped: false, carried: true },
      ],
    },
  })
  expect(response.ok()).toBeTruthy()
}

test.beforeEach(async ({ request }) => {
  await resetFixture(request)
})

test('opens the three-page P0 character sheet', async ({ page }) => {
  await page.goto(CHARACTER_URL)
  await expect(page.getByRole('heading', { name: 'P0 Human Fighter 5 / Wizard 5' })).toBeVisible()
  await expect(page.getByTestId('header-hp')).toHaveText('74')
  await expect(page.getByTestId('header-ac')).toHaveText('18')
  await expect(page.getByTestId('hit-die-d10')).toHaveText('5/5')
  await expect(page.getByTestId('hit-die-d6')).toHaveText('5/5')

  await page.getByRole('tab', { name: /法術/ }).click()
  await expect(page.getByText('Magic Missile', { exact: true })).toBeVisible()
  await expect(page.getByText('Spellbook', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('Prepared', { exact: true }).first()).toBeVisible()

  await page.getByRole('tab', { name: /物品欄/ }).click()
  await expect(page.getByText('Potion of Healing', { exact: true })).toBeVisible()
  await expect(page.getByLabel('物品名稱')).toHaveAttribute('role', 'combobox')
})

test('persists HP after a browser reload', async ({ page }) => {
  await page.goto(CHARACTER_URL)
  await page.getByTestId('current-hp-input').fill('50')
  await page.getByTestId('current-hp-input-save').click()
  await expect(page.getByTestId('header-hp')).toHaveText('50')
  await page.reload()
  await expect(page.getByTestId('header-hp')).toHaveText('50')
  await expect(page.getByTestId('current-hp-input')).toHaveValue('50')
})

test('persists temporary HP and a searchable condition selection', async ({ page }) => {
  await page.goto(CHARACTER_URL)
  await page.getByTestId('temporary-hp-input').fill('8')
  await page.getByTestId('temporary-hp-input-save').click()
  await expect(page.getByTestId('header-temp-hp')).toHaveText('8')

  const conditionBox = page.getByLabel('新增狀態')
  await conditionBox.fill('Poisoned')
  await page.getByRole('option', { name: 'Poisoned' }).click()
  await page.getByRole('button', { name: '加入 Condition' }).click()
  await expect(page.getByRole('button', { name: /Poisoned/ })).toBeVisible()
  await page.reload()
  await expect(page.getByTestId('header-temp-hp')).toHaveText('8')
  await expect(page.getByRole('button', { name: /Poisoned/ })).toBeVisible()
})

test('persists spell-slot resource usage', async ({ page }) => {
  await page.goto(CHARACTER_URL)
  await page.getByRole('tab', { name: /法術/ }).click()
  await expect(page.getByTestId('spell-slot-1-counter')).toHaveText('3 / 4')
  await page.getByTestId('spell-slot-1-use').click()
  await expect(page.getByTestId('spell-slot-1-counter')).toHaveText('2 / 4')
  await page.reload()
  await page.getByRole('tab', { name: /法術/ }).click()
  await expect(page.getByTestId('spell-slot-1-counter')).toHaveText('2 / 4')
})

test('persists live inventory quantity', async ({ page }) => {
  await page.goto(CHARACTER_URL)
  await page.getByRole('tab', { name: /物品欄/ }).click()
  await expect(page.getByTestId('inventory-inventory:healing-potion-quantity')).toHaveText('2')
  await page.getByTestId('inventory-inventory:healing-potion-decrement').click()
  await expect(page.getByTestId('inventory-inventory:healing-potion-quantity')).toHaveText('1')
  await page.reload()
  await page.getByRole('tab', { name: /物品欄/ }).click()
  await expect(page.getByTestId('inventory-inventory:healing-potion-quantity')).toHaveText('1')
})

test('unequipping Shield persists and uses authoritative AC', async ({ page }) => {
  await page.goto(CHARACTER_URL)
  await expect(page.getByTestId('header-ac')).toHaveText('18')
  await page.getByRole('tab', { name: /物品欄/ }).click()
  await page.getByTestId('inventory-inventory:shield-equip').click()
  await expect(page.getByTestId('header-ac')).toHaveText('16')
  await page.reload()
  await expect(page.getByTestId('header-ac')).toHaveText('16')
  await page.getByRole('tab', { name: /物品欄/ }).click()
  await expect(page.getByTestId('inventory-inventory:shield-equip')).toHaveText('Equip')
})

test('empty optional roleplay data does not block the sheet', async ({ page }) => {
  await page.goto(CHARACTER_URL)
  const roleplay = page.getByText('Roleplay / Biography', { exact: true })
  await expect(roleplay).toBeVisible()
  await roleplay.click()
  await expect(page.getByText('尚未填寫角色扮演資料。')).toBeVisible()
})
