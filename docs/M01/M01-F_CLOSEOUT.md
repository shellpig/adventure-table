# M01-F Closeout Checklist

M01-F — VRGR Lineage & Dhampir closeout scope：

- [x] 新增 `lineage` StableKind 與 `vrgr` Content Pack（`manifest.json` / `lineages.json` / `features.json`），Dhampir 以 Lineage identity 存在，不偽裝成 subrace。
- [x] Dhampir core identity 正確：Creature Type Humanoid、size medium / small、walking 35、climb 35、ability score branch `+2/+1` 與 `+1/+1/+1`、Darkvision 60、Deathless Nature、Spider Climb、Vampiric Bite。
- [x] `CharacterBuild` 取得 `lineage_ref` / `ancestral_origin_ref` / `ancestral_legacy` 三個 typed field，且 lineage-only field 與 `lineage_ref` 互為必要條件；不整包 copy 舊 race JSON。
- [x] Direct Create 走 ability branch / size / language / 2 個自選 Skill 的 Ancestral Legacy 規則，`ancestral_origin_ref` 為 null。
- [x] Existing Character 重用 P1-G `BUILD_EDIT` workflow 轉換為 Dhampir，產生 immutable Version N+1，Version N build snapshot 不變。
- [x] Ancestral Legacy whitelist 只允許原 Race 來源的 Skill proficiencies 與 climb / fly / swim speeds；old ability bonus、weapon / armor proficiency、racial spell、racial trait、walking speed 均不出現在 options，且 server 端拒絕偽造 payload。
- [x] Provenance 以 Builder choice source_ref 與原 race content 交集判定，不把 background / class 來源的 skill 誤列為 racial legacy。
- [x] Direct Create 與 Existing transformation 的 language 規則分開處理，由 server 依 workflow / source mode 決定。
- [x] Spider Climb 基礎 climb speed 立即存在，stronger Spider Climb feature 自 Character Level 3 起授予。
- [x] Vampiric Bite 保存 natural weapon identity、CON attack / damage、1d4 piercing、HP ≤ half max 的 advantage metadata、heal / next check-or-attack bonus empowerment、uses = PB、Long Rest recharge 與 Construct / Undead restriction；不實作 Combat attack action。
- [x] Transformation reconciliation 保留 damage delta、Temp HP、Conditions、Inventory 與 legal prepared spells，Starting Equipment 不重建。
- [x] Level Up 不得新增、移除或替換 lineage。
- [x] `lineage` name 納入 localization field policy，`zh-TW` / `en` required completeness 為 0 issues。
- [x] Direct Dhampir Create、Existing Character → Dhampir Build v2、reload + Version History 三條 real-browser flow 通過。

## Verification evidence

2026-09-01 最終驗證，分支 `feat/m01-f-vrgr-dhampir` HEAD `9037bd9`：

```text
cd apps/server
..\..\.venv\Scripts\python.exe -m pytest
313 passed in 86.73s

cd apps/web
npm test -- --run
15 test files / 76 tests passed

npm run build
TypeScript / Vite build passed

npx playwright test --reporter=list
48 passed (1.6m)
```

E2E 前已清空 `characters` / `character_versions` / `character_states` / `character_build_drafts`，並以 `python -m app.scripts.seed_p0_fighter_wizard` 重新建立共用 fixture 角色；本機 PostgreSQL 位於 alembic head `0006_character_archive`。

Playwright 全套在本次為 48/48 全綠，且未再需要手動指定 worker 數。

## 驗證過程中修正的測試基礎設施問題

`apps/web/playwright.config.ts` 原本只有 `fullyParallel: false`，該設定僅讓單一檔案內序列，檔案之間仍平行。本機多核心環境會開 15 個 worker，多條 spec 同時 `PATCH` 同一隻共用 fixture 角色 `00000000-0000-4000-8000-0000000000e0`，導致同一份程式碼連續兩次執行各有 15 條失敗、且失敗集合不同。本 Subphase 加入 `workers: 1` 後穩定全綠。互相污染的檔案至少包含 `character-sheet.spec.ts`、`m02b-ui-copy.spec.ts`、`m02h-bilingual-site-smoke.spec.ts` 與 `m02h-localization-state-integrity.spec.ts`。

另記錄一項本機執行須知：上述四個 spec 在 `beforeEach` 直接 `PATCH` 共用 fixture 角色但不自行建立它，因此清空資料表之後必須重新執行 seed script，否則會產生 15 條與程式碼無關的假性失敗。CI 的 `p0a-foundation.yml` 已有對應的「Seed deterministic P0 fixture」步驟。

## Boundary

- 不建立 Hunger gameplay system。
- 不把 origin flavor table 變成 mandatory。
- 不實作 Vampiric Bite 的 Combat attack action；M01-F 只要求 metadata 正確。
- 不新增第二套 Transform Character persistence service；transformation 重用既有 Build Edit。
- 本次 verifier 只更新關門文件與 SSOT；沒有修改產品碼、測試或 fixture。

## 已知限制（使用者已於 2026-09-01 接受並決定關門）

- `apps/web/e2e/m01f-dhampir-lineage.spec.ts` 透過 `page.request` 建立角色，僅在 Character Sheet 階段驅動瀏覽器；不像 `m01d-vgm-races.spec.ts` / `m01e-half-elf-variants.spec.ts` 那樣點擊 Builder UI 完成 lineage 選擇。
- `apps/web/src/i18n/m01fLineageBuilder.test.ts` 的第二個測試以讀取 `CharacterBuilderPage.tsx` 原始碼並比對字面字串的方式驗證接線，不 render 元件。

兩者合計的後果：lineage Builder UI 目前沒有測試實際渲染或操作它。localization presentation、server 契約與 persistence round-trip 均有實質覆蓋，此限制僅存在於該 UI 互動層。

## Handoff

M01-F 已完成並關門。下一個可開工 Subphase：**M01-G — TCE Artificer Core**。

M01-G 繼續遵守 M02 localization Definition of Done：新增、修改或首次 expose 的 user-visible system / rules content，必須在同一 Subphase 同步 `zh-TW` / `en`。
