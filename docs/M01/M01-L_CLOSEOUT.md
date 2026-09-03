# M01-L Closeout Checklist

M01-L — VGM & SCAG Remaining Race Expansion / Generic Race Mechanics closeout scope：

- [x] VGM remaining 10 個 full race（Bugbear / Firbolg / Goliath / Kenku / Kobold / Lizardfolk / Orc / Tabaxi / Triton / Yuan-ti Pureblood）10 / 10 accounted for，且 M01-D 的 Goblin / Hobgoblin / Aasimar identity 未被重做或複製。
- [x] SCAG remaining 2 個 subrace（Ghostwise Halfling / Deep Gnome (Svirfneblin)）2 / 2 accounted for，parent ref 分別為 `srd5.1:race:halfling` 與 `srd5.1:race:gnome`。
- [x] Expected inventory 為 machine-verifiable：`data/rules/dnd5e-2014/m01l-race-inventory.json` 逐 key 宣告 12 個 identity、legacy VGM race key 與 cross-pack 依賴，`validate_m01l_inventory()` 在 default registry load 時強制比對 key、name、kind、parent ref 與 pack 總量，漂移即 fail-fast。
- [x] Generic Race / Subrace movement grant 進入既有 `RaceVariantMovementGrant` 型別，Lizardfolk / Triton swim 30 與 Tabaxi climb 20 由 server compile，沒有第二套 `race_speed_*` persistence，也沒有 race name hardcode。
- [x] Signed racial ability modifier：Kobold STR −2 / Orc INT −2 正確套用；Point Buy 的 base 合法性先於種族修正判定，合法 base 8 + racial −2 得到 effective 6 而不觸發 `point_buy_score_out_of_range` / `point_buy_budget_exceeded`。
- [x] Review / Character Sheet 的 signed presentation 正確，不出現 `+-2` 這類格式。
- [x] Natural Armor 成為 Rules Layer primitive：`NaturalArmorData` typed descriptor + `calculate_armor_class()` 的 candidate 解析；未穿 body armor 時取 `10 + DEX` 與 Natural Armor candidates 的較大值，穿 body armor 時只走 worn-armor route，shield 與 Numeric Override 語意不變。
- [x] Natural Armor descriptor 對 `base < 1`、非 dexterity ability、缺欄位與未支援的額外欄位一律 fail-fast，Rules Layer 不依賴 race StableKey。
- [x] Firbolg / Triton / Yuan-ti 重用 M01-D 既有 racial spell substrate；`recharge_types` 成為 canonical 多值欄位，Firbolg 的「short or long rest」無損保存，legacy 單值 `rest_type` 只作為載入舊 JSON 時的 normalize input。
- [x] `SpellAccessEntry` 新不變式釘死：at-will ⇔ `uses_per_rest is None` 且 canonical recharge 為空；limited-use ⇔ `uses_per_rest` 有值且 recharge 至少一筆且無重複。違反組合與 legacy 衝突均 fail-fast。
- [x] Triton Lv1 / Lv3 / Lv5 spell access 依 Character Level 出現，Yuan-ti 的 at-will 與 limited-use 正確區分，`Animal Friendship` 的 snake-only 限制保留 structured metadata 而不假裝已 enforce。
- [x] 代表性 structural mechanics 真正進既有 substrate：Kenku Training 與 Lizardfolk Hunter's Lore 各 choose 2，fixed proficiency / language、natural weapon identity、damage resistance / immunity 與 limited-use resource metadata 均為 typed 或可查詢資料。
- [x] 選項守衛：少選、多選與偽造選項都由 server 產生 `invalid_choice_count` / `invalid_choice_option` 並拒絕。
- [x] Runtime automation boundary 成為 typed 契約：`runtime_execution` 收斂為封閉 Literal（`automatic_static` / `manual` / `deferred_roll` / `deferred_combat` / `deferred_reaction` / `deferred_rest` / `deferred_spatial`），12 個 identity 授予的每個 feature 都必須宣告，且帶 `natural_armor` / `racial_spell_access` 的 feature 必須是 `automatic_static`。UI 不對 deferred effect 宣稱自動執行。
- [x] `zh-TW` / `en` localization completeness 對 `vgm` / `scag` / `xge` 的 race / subrace / feature / spell / language 為 0 issues；movement、Natural Armor 與 ability bonus 等 mechanics 欄位維持 locale-neutral、不進 required policy。
- [x] Runtime 不依賴 authoring Markdown：`apps/server/app` 與 `apps/web/src` 全樹不得出現 `暫用規則資訊` / `種族_VGM` / `種族_SCAG`，且 server Dockerfile 沒有任何 `COPY` 帶 `docs`。
- [x] Direct High-Level Create / Level Up / Build Edit 三種 mode 對同一 Triton payload 產生一致的 racial spell 與 movement 結果，且比對走 composed service compiler。
- [x] Persistence：db + server 容器重啟後，四隻 M01-L 代表角色的 AC、速度、ability scores、racial spells、features 與 equipped inventory 完全一致。
- [x] P0 / P1 / M01-A～K regression 保持 green。

## Verification evidence

2026-09-03 最終驗證，分支 `feat/m01-l-vgm-scag-races` HEAD `9885cb0`：

```text
cd apps/server
..\..\.venv\Scripts\python.exe -m pytest
588 passed（exit 0）

cd apps/web
npx vitest run
18 test files / 88 tests passed

npx tsc --noEmit
TypeScript clean

npm run test:e2e:docker
81 passed, 1 skipped (6.0m)
```

Playwright 走 `npm run test:e2e:docker`，對容器化的 server / web 執行；唯一 skip 為既有的 `KI-M01J-001`（`test.fixme()`），與 M01-L 無關。

M01-L 專屬後端覆蓋集中在 `apps/server/tests/test_m01l_races.py`（15 個測試），瀏覽器覆蓋為 `apps/web/e2e/m01l-races.spec.ts`（FC-E2E-21，4 條真後端 flow）。

## M01-L Closeout Evidence

```text
VGM remaining inventory: 10 / 10
SCAG remaining subraces: 2 / 2
Duplicate prior identities: 0（Goblin / Hobgoblin / Aasimar 與 Half-Elf variants 未被重建；registry load gate 比對 pack 全集）
Generic movement matrix: PASS（Lizardfolk walk 30 + swim 30、Tabaxi walk 30 + climb 20、Triton walk 30 + swim 30、Wood Elf walk 35）
Negative racial modifier matrix: PASS（Kobold base STR 8 → effective 6、Orc INT −2；Point Buy base legality 不受種族修正影響）
Natural Armor matrix: PASS（無甲 15、+shield 17、chain mail 16、chain mail + shield 18、Numeric Override 22；malformed descriptor fail-fast）
Racial spell / multi-rest recharge: PASS（Firbolg short_rest + long_rest 無損；Triton Lv1/3/5 gate；Yuan-ti at-will 與 limited-use 區分；legacy rest_type normalize）
Structural choice matrix: PASS（Kenku Training 與 Hunter's Lore 各 2 / 2；wrong-count / forged option 由 server 拒絕）
Deferred classification: PASS（12 scope features 全數宣告封閉 Literal；automatic payload 必為 automatic_static）
Localization completeness: PASS（vgm / scag / xge × zh-TW / en，0 issues）
Runtime without docs: PASS（靜態依賴掃描 + server image 不含 docs/ 仍完成 registry load、startup 與 Builder flow）
Focused E2E: 4 / 4（FC-E2E-21）
Restart persistence: PASS（db + server 重啟後 4 隻代表角色快照完全一致）
Human smoke: 未執行（見「已知限制」）
P0/P1/M01-A～K regression: PASS（後端 588、前端 88、Playwright 81）
```

Restart persistence dataset 使用 FC-E2E-21 建立的四隻角色：Lizardfolk（裝備 shield，AC 17）、Kobold（negative modifier，STR 6）、Triton（racial spell，Fog Cloud + Gust of Wind）、Deep Gnome（SCAG subrace，INT 14 / walk 25）。

## 關門過程中修正的問題

1. **`scag:subrace:deep-gnome` inventory name mismatch**：inventory gate 宣告 `Deep Gnome`，runtime canonical 名稱是 `Deep Gnome (Svirfneblin)`，導致 default registry load 直接拋 `ContentValidationError`，M01-L 後端測試 9 個全數無法執行。已將 inventory 對齊 runtime canonical 名稱。

2. **SCAG Half-Elf feature 的 orphan zh-TW overlay**：`half-elf-fleet-of-foot`、`half-elf-swimming-speed`、`half-elf-drow-magic` 三個 feature 在 M01-E 之後改以 typed `movement` / `racial_spell_access` 表達，canonical `data.desc` 已不存在，但 zh-TW overlay 仍宣告 `data.desc.0`，觸發 `references unknown field`。已補回三則 canonical 英文 description，兩語齊全，typed mechanics 不變。

3. **`runtime_execution` 未 typed 且四筆缺標**：該欄位原本只是 free-form data key，`firbolg-magic`、`lizardfolk-natural-armor`、`control-air-and-water`、`yuan-ti-innate-spellcasting` 四個 server 真的會自動套用的 feature 完全沒有分類。已收斂為封閉 Literal 並補標為 `automatic_static`，L8 的 automation boundary 因此可 machine-check。

## Boundary

- 不做 Tiefling、不做 `mtf` pack；SCAG Tiefling variants 與 MTF planar races 全部留 M01-M。
- 不建立 generic Combat trigger engine、Rest transaction / auto-recovery 或完整 natural-weapon attack engine。Bugbear Surprise Attack、Firbolg Hidden Step、Goliath Stone's Endurance、Kobold Pack Tactics、Lizardfolk Hungry Jaws、Orc Aggressive、Tabaxi Feline Agility 等只保存 trigger / formula / resource / classification。
- 不建立 arbitrary Natural Armor predicate DSL；`NaturalArmorData.ability` 目前只接受 dexterity，其餘 formula 在 content 邊界即拒絕。
- 不把 `docs/暫用規則資訊/` 放進 runtime dependency graph。
- 不為 signed racial modifier 或 Natural Armor 做既有 Build 的 bulk rewrite。

## 已知限制

- **Human smoke 未執行。** 測試指南 L.10 要求實際手動建立四隻角色（secondary movement + Natural Armor、negative racial modifier、racial spell、SCAG subrace）。等價路徑已由 FC-E2E-21 的四條真後端瀏覽器 flow 與重啟後的快照比對覆蓋，但那是自動化執行，不等於人工操作確認。此項留給專案 owner。
- **Movement regression control 不在 M01-L 測試檔內。** 測試指南 L.3 列出的 Aquatic Half-Elf swim 30、Wood Half-Elf walk 35 與 Dhampir walk 35 + climb 35 三個 control 仍留在 `test_m01e_half_elf_variants.py::test_variant_movement_compiles_to_explicit_modes` 與 `test_m01f_closeout.py`，對同一 resolver 斷言且全綠；M01-L 的 movement matrix 在該測試以註解指向這兩處，不複製第二套 harness。若日後要求 L matrix 自足，再補。

## Handoff

M01-L 已完成並關門。下一個可開工 Subphase：**M01-M — MTF Planar Race Expansion & Tiefling Bloodline / Variant System**。

M01-M 直接繼承 L 的三項 substrate，不得再造第二套：generic movement grant（Sea Elf swim 30、Winged conditional movement）、`SpellAccessEntry` 的 canonical recharge 不變式（M 只加 optional `cast_at_level` / `waive_components`，不再動 recharge），以及 `runtime_execution` 的封閉分類。

M01-M 繼續遵守 M02 localization Definition of Done：新增、修改或首次 expose 的 user-visible system / rules content，必須在同一 Subphase 同步 `zh-TW` / `en`。

M01-M 之後是否再新增 M01 規則 Subphase，以及 Full M01 Integration & Closeout 的 Subphase ID，仍由使用者拍板。
