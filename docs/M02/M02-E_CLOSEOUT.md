# M02-E Closeout — SRD 5.1 Description Localization

日期：2026-08-31  
分支：`m02-e-srd-descriptions`

## 結論

M02-E 已完成本分支核准的 SRD 5.1 description authoring scope：

- `spell.data.desc.*`
- `feature.data.desc.*`
- `condition.data.desc.*`

上述三個 canonical corpus 的繁體中文內容已以 StableKey + field path overlay 寫入 `data/srd5.1/locales/zh-TW/`；不修改 canonical mechanics data，也不建立第二份 mechanics dataset。

這份 closeout **取代本分支早期「required long-form count = 0」的錯誤 closeout 判定**。早期判定只依當時 current-surface required policy 得出零項，但使用者明確要求 M02-E 不要留下大量未翻譯英文，因此本分支將 spell / feature / condition 的 SRD description corpus 提前 author 完成，並新增獨立 gate 保證覆蓋完整。

這項擴充不代表把所有 hidden field 都改成 user-visible，也不修改 `currently_user_visible`；presentation policy 仍如實描述目前 UI surface。

## 已完成資料

### Spells

SRD 5.1 spell canonical `data.desc.*` 已完整翻譯，translation shard：

```text
data/srd5.1/locales/zh-TW/spell-desc-01.json
...
data/srd5.1/locales/zh-TW/spell-desc-42.json
```

保留：

- 原始段落索引 `data.desc.N`
- 骰式與傷害數值
- DC / 距離 / 時間 / 百分比 / 次數等 mechanics-sensitive token
- Markdown table row / column shape
- StableKey identity

包含但不限於 Teleport / Scrying / Reincarnate / Prismatic Spray / Prismatic Wall / True Polymorph / Wish 等具有表格或大量條件的長文。

### Conditions

SRD 5.1 condition canonical `data.desc.*` 已完整翻譯：

```text
data/srd5.1/locales/zh-TW/condition-desc.json
```

包含 Blinded / Charmed / Grappled / Paralyzed / Petrified / Restrained / Stunned / Unconscious / Exhaustion 等全部 canonical condition entries。

### Features

SRD 5.1 feature canonical `data.desc.*` 已依職業完整翻譯：

```text
data/srd5.1/locales/zh-TW/feature-desc-01.json  # Barbarian
data/srd5.1/locales/zh-TW/feature-desc-02.json  # Bard
data/srd5.1/locales/zh-TW/feature-desc-03.json  # Cleric
data/srd5.1/locales/zh-TW/feature-desc-04.json  # Druid
data/srd5.1/locales/zh-TW/feature-desc-05.json  # Fighter
data/srd5.1/locales/zh-TW/feature-desc-06.json  # Monk
data/srd5.1/locales/zh-TW/feature-desc-07.json  # Paladin
data/srd5.1/locales/zh-TW/feature-desc-08.json  # Ranger
data/srd5.1/locales/zh-TW/feature-desc-09.json  # Rogue
data/srd5.1/locales/zh-TW/feature-desc-10.json  # Sorcerer
data/srd5.1/locales/zh-TW/feature-desc-11.json  # Warlock
data/srd5.1/locales/zh-TW/feature-desc-12.json  # Wizard
```

重複 progression StableKey（ASI、Extra Attack、Domain/Origin/Archetype improvement、Mystic Arcanum 等）仍各自有完整 translation field；沒有用 runtime alias 或 summary text 取代 canonical field coverage。

Warlock 的 Eldritch Invocations 亦逐 StableKey author，不只翻 `Eldritch Invocations` 總說明。

## 明確不納入本次 bulk authoring

以下 long-form 仍依 M02-C field policy 延後：

```text
background.data.feature.desc
item.data.desc.*
```

原因：這些欄位目前仍沒有對應 product surface；尤其 `items.json` 長文體量很大，提前全部翻譯會重建先前已明確排除的 translation / review debt。

因此：

- spell / feature / condition description：M02-E 明確提前 author 完成。
- item / background hidden description：仍由首次 expose 該欄位的 Subphase 處理。
- Monster / Beast：仍依既有 roadmap 延後 P4-A，不在 M02 建立 monster-specific translation corpus。

## Automated authoring gates

`apps/server/tests/test_m02e_description_scope.py` 已由早期零 scope regression 改為實際 description corpus gate。

測試會直接讀 canonical：

```text
data/srd5.1/spells.json
data/srd5.1/features.json
data/srd5.1/conditions.json
```

再逐一枚舉每個：

```text
<StableKey>::data.desc.N
```

並要求 zh-TW shards 滿足：

1. **Exact field coverage**
   - 每個 canonical description path 都必須有 zh-TW field。
   - canonical 非空字串不得翻成空字串。

2. **English leakage gate**
   - canonical human-language description 不得直接以相同英文原文出貨。
   - 翻譯內容必須含中文文字。
   - 純 Markdown separator / 空字串等沒有語言的結構列不誤判。

3. **Mechanics fidelity gate**
   - dice token，例如 `2d8`、`10d10`
   - signed modifier，例如 `+2`、`-4`
   - Arabic numeric token，例如距離、DC、等級、次數、百分比
   - canonical 中出現的上述 token 必須仍存在於翻譯。

4. **Markdown table shape gate**
   - canonical table row 必須仍是 table row。
   - pipe / column 數不得改變。

這些 gate 不 hard-code description 數量；canonical 新增任何 spell / feature / condition `data.desc.*` 後，若沒有同步 zh-TW，測試會自動失敗。

## Runtime / identity 邊界

M02-E 沒有改變：

- StableKey
- content refs
- Builder choice IDs
- CharacterBuild
- CharacterState
- Draft revision
- spell / feature mechanics

Localization 仍只是 presentation overlay。

英文模式仍讀 canonical English；`zh-TW` 模式由 existing `ContentLocalizationCatalog` / shard loader 套用繁中 overlay。切換 locale 不需要重建角色或改寫任何 character state。

## CI 狀態

PR #29 的 GitHub Actions 目前仍受外部 runner / Actions 執行問題阻塞。

最近一次本分支 workflow：

```text
run: 33352945719
workflow: P1 Full Regression
conclusion: failure
job: p1-full-regression
steps: none returned
```

該 run 在任何 workflow step 執行前即結束，沒有 pytest / frontend / Playwright step result，也沒有可用 test failure log。

因此本文件**不宣稱 CI tests passed**。目前可確認的是：

- translation data、authoring gate 與 closeout 均已寫入 branch；
- Actions run 沒有執行測試步驟；
- 這不是已取得 assertion failure 的 M02-E test failure。

待 GitHub Actions 可正常啟動 runner 後，PR #29 必須以現有 branch head 重跑完整 regression；若 M02-E gate 回報漏 field / mechanics token，需在 merge 前修正。

## M02-E Definition of Done

- [x] SRD spell `data.desc.*` zh-TW authoring 完成。
- [x] SRD condition `data.desc.*` zh-TW authoring 完成。
- [x] SRD feature `data.desc.*` zh-TW authoring完成，12 個職業逐 StableKey 覆蓋。
- [x] 不修改 canonical mechanics / identity。
- [x] 加入 canonical-driven exact coverage gate。
- [x] 加入 English leakage gate。
- [x] 加入 mechanics-sensitive token gate。
- [x] 加入 Markdown table structure gate。
- [x] 保持 item / background hidden long-form deferred boundary。
- [x] 舊的 zero-scope closeout 已淘汰並由本文件取代。
- [ ] GitHub Actions full regression 實際執行並取得 test-step 結果；目前為外部 runner / Actions blocker，非 branch scope 遺漏。

## 下一步

M02-E coding / authoring scope 到此結束。

下一個正式 Subphase：

```text
M02-F — PHB / SCAG / GoS Localization
```

M02-F **尚未開始**。本分支與 PR #29 不應在本任務中 merge 到 `main`。
