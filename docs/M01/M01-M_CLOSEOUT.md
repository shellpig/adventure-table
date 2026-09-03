# M01-M Closeout Checklist

M01-M — MTF Planar Race Expansion & Tiefling Bloodline / Variant System closeout scope：

- [x] `mtf` Content Pack 合法且 deterministic：manifest 宣告 5 個 category / 40 個 entry，與 runtime 實際 shipped 數量逐 kind 一致，`mtf` 已進 default enabled pack list。
- [x] MTF non-Tiefling scope 7 / 7 accounted for（Duergar / Eladrin / Sea Elf / Shadar-kai / Gith / Githyanki / Githzerai），parent 關係為 Duergar → Dwarf、Eladrin / Sea Elf / Shadar-kai → Elf、Githyanki / Githzerai → `mtf:race:gith`，且每個 parent ref 都指向已安裝的 race。
- [x] Expected inventory 為 machine-verifiable：`data/rules/dnd5e-2014/m01m-race-inventory.json` 逐 key 宣告 7 個 planar identity、9 個血脈 disposition、SCAG composite variant key 與 cross-pack 依賴；`validate_m01m_inventory()` 在 default registry load 時比對 key、name、kind、parent ref 與 pack 全集，漂移即 fail-fast。
- [x] Tiefling 九獄大魔血脈 9 / 9 accounted：Asmodeus 為 canonical mapping 指向既有 `srd5.1:race:tiefling`，其餘 8 個為新的 `mtf:race-variant:*` identity。Duplicate Asmodeus identity 為 0，inventory gate 明確拒絕任何含 `asmodeus` 的 variant key。
- [x] 既有 SRD/PHB Tiefling 未 migration、未換 key、未補 fake subrace：分支不含任何 alembic migration，Builder 對 Tiefling 只提供 9 個 variant option 且沒有第二個「Standard / Asmodeus」條目。
- [x] 8 個 bloodline 同時替換兩個 package：standard Infernal Legacy 由 grant identity 移除後才加入該血脈 Legacy，ability package 走 replacement group flag，grant summary 不出現任何偽造的 `*ability-score-increase*` identity；base Tiefling 的共同 grant 只保留一次。
- [x] SCAG 的 ability 與 legacy 兩個 replacement group 正交：baseline、Feral only、三種 Legacy replacement only、Feral + 各 Legacy 共 8 種合法組合全部通過；同一 group 選兩個為 blocking 且不產生 build candidate。
- [x] MTF non-Asmodeus bloodline 與 SCAG mechanical variant 的交叉組合全部阻擋：option generation 不提供，forged payload 由 `cross_variant_choice_selection` blocking，confirm 回 422 且不建立任何角色。
- [x] Race-variant group selection 進 immutable Build Version 並可 deterministic 還原 Build Edit seed；restart-equivalent rebind 後 Feral + Winged 分支完整回來。M01-E 舊 Build 缺少 `race_variant_group_selections` 欄位仍可讀、仍可 seed 原分支，不 bulk rewrite 歷史。
- [x] Winged Tiefling 的 fly 30 為 Current State 推導：immutable Build 的 `fly_speed` 為 `None`，Character Sheet 依 equipped body armor 決定；穿重甲消失、換輕甲仍在、脫甲恢復，全程不產生 Build Version，restart 後由同一 Build + State 重新 derive。
- [x] Eladrin Seasonal Aspect 使用 `feature_modes` + `initial_state_seed`：四個 season 皆可作為 initial seed，切換只改 State、不產生 Build Version，restart 後保留；沒有 `eladrin_season` 專用欄位。
- [x] Feature mode 驗證為 default-deny：Build 未宣告 mode descriptor 的 key 一律 blocking，被拒的請求對既有 state 零副作用。Armor Model / Eldritch Cannon 改宣告 typed content descriptor 並走同一個 generic validator，subclass + level 前置條件由「Build 未授予該 feature」自然成立。
- [x] Racial psionics / legacy spell metadata 無損保存：Duergar Lv3 / Lv5 gate、Githyanki INT 與 Githzerai WIS 分離、component-free casting、Duergar enlarge 的封閉 casting modifier；Tiefling 側六個代表驗 `cast_at_level` 固定環位與 Mammon 的 short-or-long recharge，24 條 bloodline legacy spell 全數 `uses_spell_slot=false`。
- [x] Sea Elf swim 30 重用 M01-L 的 generic movement grant（subrace `movement_grants`），沒有 source-specific movement engine；穿脫裝備不影響 unconditional movement。
- [x] Tiefling Appearance 維持 optional roleplay helper：12 條 supplied suggestion 可選可不選，完全不填仍可 Confirm，填了也不改變 variant group selection 或任何 legality。
- [x] `zh-TW` / `en` localization completeness 對 `mtf` 的 race / subrace / race-variant / feature / language 為 0 issues；SCAG 新增的 appearance suggestion 已進 policy 且兩語齊全；ability bonus 與 movement 等 mechanics 欄位維持 locale-neutral。
- [x] Runtime 不依賴 authoring Markdown：`apps/server/app` 與 `apps/web/src` 全樹不出現 `暫用規則資訊` / `種族_MTF` / `種族_SCAG`，server Dockerfile 沒有任何 `COPY` 帶 `docs`，且每個 enabled pack 都有對應的 `COPY` 行。
- [x] P0 / P1 / M01-A～L / M02 regression 保持 green。

## Verification evidence

2026-09-03 最終驗證，分支 `feat/m01-m-mtf-tiefling` HEAD `5ecd23f`：

```text
cd apps/server
..\..\.venv\Scripts\python.exe -m pytest
700 passed（exit 0，374s）

cd apps/web
npx tsc --noEmit
TypeScript clean

npx vitest run
18 test files / 88 tests passed

npm run test:e2e:docker
86 passed, 1 skipped (6.4m)
```

Playwright 走 `npm run test:e2e:docker`，對容器化的 server / web 執行；唯一 skip 為既有的 `KI-M01J-001`（`test.fixme()`），與 M01-M 無關。

M01-M 專屬後端覆蓋為 4 個測試檔共 111 個測試：

| 檔案 | 測試數 | 對應測試指南 |
|---|---|---|
| `apps/server/tests/test_m01m_inventory.py` | 10 | M.1 / M.3 / M.12 |
| `apps/server/tests/test_m01m_ancestry.py` | 25 | M.2 / M.9 / M.10 |
| `apps/server/tests/test_m01m_tiefling.py` | 58 | M.4 / M.5 / M.6 / M.9 / M.11 |
| `apps/server/tests/test_m01m_state.py` | 18 | M.7 / M.8 |

共用 draft helper 放在 `apps/server/tests/m01m_support.py`；HTTP 與 restart plumbing 沿用 `m01k_support`，與 `test_m01l_races.py` 的做法一致，不複製第二套 harness。

瀏覽器覆蓋為 `apps/web/e2e/m01m-mtf-tiefling.spec.ts`（M-E2E-01～05，5 條真後端 flow）。

## M01-M Closeout Evidence

```text
MTF non-Tiefling inventory: 7 / 7
Tiefling bloodlines accounted: 9 / 9（1 canonical mapping + 8 implemented variants）
Asmodeus duplicate identities: 0
New MTF bloodline variants: 8 / 8
Parent/inheritance matrix: PASS（Duergar→Dwarf、Eladrin/Sea Elf/Shadar-kai→Elf、Githyanki/Githzerai→Gith；parent grant 各出現一次；切換 subrace 不殘留前一分支）
MTF bloodline replacement matrix: PASS（8 血脈 × ability package / Legacy grant / Legacy spell 三面向；無 double apply、無偽造 ability grant identity）
SCAG standard-baseline compatibility matrix: PASS（8 種合法組合全通過；同 group 雙選為 blocking）
Illegal MTF+SCAG combination rejection: PASS（option generation 不提供；forged payload blocking，confirm 422，zero side effect）
Race-variant group persistence: PASS（進 Build Version、restart rebind 還原、Build Edit seed 還原 Feral+Winged；M01-E 舊 Build 無欄位仍可讀可 seed）
Winged conditional movement: PASS（Build fly_speed = None；重甲消失／輕甲保留／脫甲恢復；version_no 與 current_version_id 不變；restart 一致）
Eladrin feature_modes state: PASS（4 season seed、切換不建版本、restart 保留；default-deny 5 個負面案例被拒且 state 未污染）
Racial spell/psionic metadata: PASS（Duergar Lv3/Lv5 gate 與 enlarge 封閉 modifier；Githyanki INT / Githzerai WIS；6 個 Tiefling 代表驗 cast_at_level 與 Mammon short_rest+long_rest；24 條 legacy spell uses_spell_slot=false）
Appearance optionality: PASS（12 條 suggestion；不填可 Confirm；填了不改 group selection）
Localization completeness: PASS（mtf × zh-TW / en，0 issues；SCAG appearance suggestion 兩語齊全）
Runtime without docs: PASS（靜態依賴掃描 + server image 不含 docs/；每個 enabled pack 都有 COPY 行）
Focused E2E: 5 / 5（M-E2E-01～05）
Human smoke: 未執行（見「已知限制」）
Restart persistence dataset: 部分自動化（見「已知限制」）
P0/P1/M01-A～L/M02 regression: PASS（後端 700、前端 88、Playwright 86 passed + 1 skipped）
```

## 關門過程中修正的問題

1. **`build_version_summary()` 被誤刪，整個 server 無法 import。** `dd2db44` 在加入 race-variant group seeding 時把 `versions.py` 的 `build_version_summary()` 一併移除，但 `app/persistence/characters.py` 仍 import 並呼叫它。`app.main` 因此無法 import，28 個測試模組直接 collection ERROR，容器化 server 也起不來。此後 35 個 commit 都疊在這個狀態上。已原位還原該函式並補回被同一 commit 刪掉的檔尾換行。

2. **`data/mtf` 未進 server Dockerfile，shipped image 無法啟動。** Dockerfile 為了排除 `docs/` 而逐一 `COPY` 各 data pack，新增的 `mtf` 沒有對應行。啟用 pack 後 server container 直接以 `ContentValidationError: enabled content pack directory is missing: /app/data/mtf` 退出，整個 Docker E2E stack 無法建立。已補 `COPY data/mtf`，並加測試要求每個 enabled pack 都必須出現在 image 的 COPY 清單中。

3. **既有 gate 未同步 `mtf`。** `test_m01c_backgrounds.py` 的 enabled pack tuple 仍是 M01-M 之前的 8 個 pack；`data/scag/locales/zh-TW/m01m.json` 的 variant 名稱帶「SCAG 」前綴，觸發 M02-D 的 zh-TW 混語 gate。已分別補上 `mtf` 與改為「提夫林變體」（M01-E 的 variant 譯名同樣不帶 source 前綴）。

4. **Conditional movement 被寫進 immutable Build。** `race_variants.py` 的兩條 movement 路徑都忽略 grant 的 `condition`，Winged Tiefling 的 Build 因此存下 `fly_speed=30`——那不是所有 Current State 都成立的事實，違反測試指南 M.7 第 8 條。Character Sheet 當時仍顯示正確（`effective_movement()` 會清掉未成立的模式），但任何直讀 `build.fly_speed` 的 consumer 都會得到錯的答案。已讓 Build 編譯跳過 conditional grant，飛行只由 feature 的 `conditional_movement` 對 live equipment 解析；winged option 中因此變成無效的 `movement` 區塊一併移除。

5. **Feature mode 驗證 fail-open。** `validate_feature_modes()` 對不認得的 key 直接放行，`CharacterState.feature_modes` 等於可以夾帶任意 client 值，也會留住 Build 已不再授予的 mode。Artificer 子系統則是另一套寫死兩個 feature ref 的 if/elif，對其他 key 同樣 fail-open。已把 Armor Model / Eldritch Cannon 改宣告 typed content `feature_mode` descriptor、刪除 Artificer 專用驗證，generic validator 改為 default-deny。reconciliation 與 initial-state seeding 本來就吃同一份 descriptor，兩個 Artificer mode 因而一併取得 generic 行為（建角 seed content 預設值、Build Edit 移除 granting feature 時產生 removal change）。

## Boundary

- 不允許 MTF non-Asmodeus bloodline 與 SCAG mechanical variant 交叉混搭；SCAG variants 只作用於 standard / Asmodeus baseline。
- 不建立 duplicate Asmodeus identity，也不為既有 Tiefling 補 subrace / variant key。
- 不建立 generic arbitrary condition / effect DSL。`MovementConditionData` 目前只接受 `not_wearing_armor_category`，其餘在 content 邊界即拒絕。
- 不建立完整 Spell / Combat / Rest Engine。Duergar 日照限制、Eladrin Fey Step 的 target / save / effect、Shadar-kai 傳送後的 damage resistance duration、Gith psychic 效果與所有 Tiefling legacy spell 的效果解算，一律保留 structured / manual / deferred metadata。
- 沒有正式 Rest transaction 之前，server 不假裝知道「剛完成長休」；Eladrin 換季為手動操作，UI 明示規則時機。
- 不做 2024 Tiefling / species rules，不把 supplied Markdown 變成 runtime source。

## 已知限制

- **Human smoke 未執行。** 測試指南 M.14 要求人工確認看不到 duplicate Asmodeus option、建立 MTF non-Asmodeus Tiefling、建立 Feral + Winged 並實際切換重甲、建立 Eladrin 並換季、切換兩語確認 MTF / SCAG presentation。等價路徑已由 M-E2E-01～05 的真後端瀏覽器 flow 覆蓋，但那是自動化執行，不等於人工操作確認。此項留給專案 owner。
- **Restart persistence dataset 只覆蓋六項中的四項。** M.14 列的六種 restart 對象中，MTF bloodline、Feral + Legacy replacement、Winged + 重甲狀態、Eladrin 非預設 season 已由 rebind 測試覆蓋；pre-M 標準 Tiefling 與 Gith / Duergar racial spell 代表未做重啟快照比對，其 Build / State 語意由同一份 compile 與 validation 路徑保證。
- **季節選單標籤與 content 名稱不一致。** `M01MAncestryRoutePanel` 由 mode key 推導標籤，英文顯示 `eladrin season`、繁中顯示「季節形態」，但該 feature 的 content 名稱是 `Seasonal Aspect` / 「季節面貌」。純呈現瑕疵，不影響 mode 合法性或任何 Build / State 語意。
- **`feature_modes` 的 mode key 有兩套命名慣例。** Eladrin 用 slug `eladrin-season`，Armor Model / Eldritch Cannon 用自身 feature ref。default-deny 不受影響（key 只是不透明字串，兩者不衝突），但同一張 map 內有兩種寫法。統一成 feature ref 會連帶改動上一項的標籤 fallback，超出本 Subphase 範圍。

## Handoff

M01-M 已完成並關門。M01 **不是** full closeout。

M 之後是否再新增 M01 規則 Subphase，以及 Full M01 Integration & Closeout 的 Subphase ID，仍由使用者拍板。只有 final M01 closeout 完成後才回到 P2 — Room / Campaign / Session / Seat。

後續 Subphase 直接繼承 M 的三項 substrate，不得再造第二套：

- **Conditional movement**：條件式速度是 content metadata + `effective_movement()` 的 read-time 解析，永遠不寫進 immutable Build。
- **Feature mode**：任何「可切換的當前形態」都以 content `feature_mode` descriptor 宣告，由 Build 決定是否擁有、由 generic validator 以 default-deny 驗證，不再寫子系統專屬的驗證分支。
- **Race variant replacement group**：group / option 的選擇是 Build provenance（`race_variant_group_selections`），不從 resolved 數值反推。

M01-M 繼續遵守 M02 localization Definition of Done：新增、修改或首次 expose 的 user-visible system / rules content，必須在同一 Subphase 同步 `zh-TW` / `en`。
