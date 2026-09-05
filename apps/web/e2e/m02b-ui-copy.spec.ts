import { expect, test } from '@playwright/test'

const FIXTURE_ID = '00000000-0000-4000-8000-0000000000e0'

test('M02-B switches Landing and Workshop copy and accessibility names immediately', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByText('A table-first D&D 5e 2014 character tool.')).toBeVisible()
  await expect(page.getByRole('group', { name: 'Language' })).toBeVisible()

  await page.getByTestId('locale-option-zh-TW').click()
  await expect(page.getByText('以桌上跑團為優先的 D&D 5e 2014 角色工具。')).toBeVisible()
  await expect(page.getByRole('link', { name: '開啟角色工作坊 →' })).toBeVisible()
  await expect(page.getByRole('group', { name: '語言' })).toBeVisible()

  await page.getByRole('link', { name: '開啟角色工作坊 →' }).click()
  await expect(page.getByRole('heading', { name: '角色工作坊' })).toBeVisible()
  await expect(page.getByRole('button', { name: '＋ 建立角色' })).toBeVisible()

  const workshopUrl = page.url()
  await page.getByTestId('locale-option-en').click()
  await expect(page).toHaveURL(workshopUrl)
  await expect(page.getByRole('heading', { name: 'Character Workshop' })).toBeVisible()
  await expect(page.getByRole('button', { name: '+ Create Character' })).toBeVisible()
})

test('M02-B localizes every Builder step without resetting in-progress UI state', async ({ page }) => {
  await page.goto('/characters')
  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)
  await expect(page.getByText('Saved on server')).toBeVisible()

  const builderUrl = page.url()
  await page.getByLabel('Character name').fill('Locale Hero')
  await page.getByTestId('locale-option-zh-TW').click()

  await expect(page).toHaveURL(builderUrl)
  await expect(page.getByLabel('角色名稱')).toHaveValue('Locale Hero')
  await expect(page.getByRole('heading', { name: '先設定角色基本資料' })).toBeVisible()
  await expect(page.getByRole('button', { name: '儲存基本資料' })).toBeVisible()

  await page.getByRole('button', { name: '儲存基本資料' }).click()
  await expect(page.getByText('已儲存至伺服器')).toBeVisible()

  await page.getByTestId('builder-step-origin').click()
  await expect(page.getByRole('heading', { name: '選擇出身' })).toBeVisible()

  await page.getByTestId('builder-step-abilities').click()
  await expect(page.getByRole('heading', { name: '屬性與起始選擇' })).toBeVisible()
  await expect(page.getByRole('tab', { name: '標準陣列' })).toBeVisible()

  await page.getByTestId('builder-step-class').click()
  await expect(page.getByRole('heading', { name: '建立逐等級職業配置' })).toBeVisible()

  await page.getByTestId('builder-step-spells').click()
  await expect(page.getByRole('heading', { name: '施法與資源' })).toBeVisible()

  await page.getByTestId('builder-step-equipment').click()
  await expect(page.getByRole('heading', { name: '裝備與角色扮演' })).toBeVisible()

  await page.getByTestId('builder-step-review').click()
  await expect(page.getByRole('heading', { name: '角色配置快照與最終檢視' })).toBeVisible()

  await page.getByTestId('locale-option-en').click()
  await expect(page).toHaveURL(builderUrl)
  await expect(page.getByRole('heading', { name: 'Build snapshot & final review' })).toBeVisible()
})

test('M02-B localizes Character Sheet, shared controls and Version History in place', async ({ page }) => {
  await page.goto(`/characters/${FIXTURE_ID}`)

  await expect(page.getByRole('tablist', { name: 'Character Sheet tabs' })).toBeVisible()
  await expect(page.getByRole('tab', { name: /Attributes & Skills/ })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Add condition' })).toHaveAttribute(
    'placeholder',
    'Type a keyword or open the list',
  )

  const sheetUrl = page.url()
  await page.getByTestId('locale-option-zh-TW').click()
  await expect(page).toHaveURL(sheetUrl)
  await expect(page.getByRole('tablist', { name: '角色卡分頁' })).toBeVisible()
  await expect(page.getByRole('tab', { name: /屬性與技能/ })).toBeVisible()
  await expect(page.getByRole('combobox', { name: '新增狀態' })).toHaveAttribute(
    'placeholder',
    '輸入關鍵字或展開選單',
  )

  await page.getByRole('tab', { name: /法術/ }).click()
  await expect(page.getByRole('heading', { name: '法術', exact: true })).toBeVisible()
  await expect(page.getByText('已準備', { exact: true }).first()).toBeVisible()

  await page.getByRole('tab', { name: /物品欄/ }).click()
  await expect(page.getByRole('heading', { name: '加入物品' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: '物品名稱' })).toBeVisible()

  await page.goto(`/characters/${FIXTURE_ID}/versions`)
  await expect(page.getByRole('heading', { name: '角色版本' })).toBeVisible()
  await expect(page.getByText('不可變更', { exact: true })).toBeVisible()

  const versionsUrl = page.url()
  await page.getByTestId('locale-option-en').click()
  await expect(page).toHaveURL(versionsUrl)
  await expect(page.getByRole('heading', { name: 'Character Versions' })).toBeVisible()
  await expect(page.getByText('IMMUTABLE', { exact: true })).toBeVisible()
})
