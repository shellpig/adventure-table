# M01-K Closeout

M01-K — PHB Feat & Spell Catalog Expansion 已完成並關門。

> **狀態：Full Closeout Complete**
>
> 41 個 PHB 2014 non-SRD Feats 與 42 個 PHB relative-to-SRD missing Spells 已全部 materialize 進 `phb2014` runtime content。Feat structural mechanics、repeatable acquisition、prerequisite resolver、static derived values、spell catalog/access、雙語 description localization 與 browser/full-stack focused flows 均已驗收。

## Implemented Scope

- [x] `phb2014` Feat catalog 補齊 PHB 2014 相對 SRD Grappler 以外的 **41 / 41** 個 Feats；沒有新增 duplicate `phb2014:feat:grappler`。
- [x] `phb2014` Spell catalog 補齊 PHB relative-to-SRD missing **42 / 42** 個 Spells；M01-I / M01-J 已存在的 spell identities 被 reuse / enrich，沒有 duplicate StableKey。
- [x] Feat runtime data 進 `data/phb2014/` 並由 manifest 納管；runtime 不解析 `docs/暫用規則資訊/專長_PHB_非SRD內容.md` 或 `法術_PHB_非SRD內容.md`。
- [x] Variant Human 與 ASI -> Feat 使用同一 PHB Feat pool、同一 prerequisite / repeatability resolver，不做兩套 hardcode。
- [x] Feat acquisition 改為 acquisition-level persistence；repeatable Feat 每次取得有獨立 opportunity / nested selections，`feat_refs` 僅作 unique summary。
- [x] Elemental Adept repeatable contract 成立：多次 acquisition 不被 identity dedupe，且 damage-type choice 依 supplied rule 維持 cross-acquisition distinctness。
- [x] Non-repeatable Feat 再次取得會被 server blocking；UI option 若顯示則帶 structured disabled reason。
- [x] Ability minimum、armor proficiency、spellcasting、compound OR prerequisite 由單一 server resolver 判定；disabled reason / blocking issue 均送 locale-neutral `code + params`。
- [x] Actor / Athlete / Resilient / Skilled / Weapon Master / Magic Initiate / Martial Adept / Tough / Observant 等代表 structural mechanics 已進 Build / Rules Layer。
- [x] Martial Adept 透過 feat-granted entitlement 合法使用 canonical Battle Master Maneuver pool；沒有放寬無 entitlement 的 class-native gate。
- [x] Martial Adept superiority-die resource 與 Battle Master / Superior Technique 聚合到同一 `feature:superiority-dice` Current State resource。
- [x] Tough / Observant 的無條件 static derived values 進 Rules Layer 白名單：`max_hp`、`passive_perception`、`passive_investigation`；Numeric Override 維持最後絕對覆寫。
- [x] Feat automation classification 區分 `full`、`static_derived`、`deferred_*`，且 Medium Armor Master / Dual Wielder 落在 `deferred_equipment_conditional`。
- [x] Spell canonical metadata 補齊 level、school、casting time、range、components/material、duration、ritual、concentration、PHB class access、description、provenance。
- [x] Cross-source spell access provenance 保持乾淨：PHB spell identity 不把 TCE 等 later-source access 反寫成 PHB access。
- [x] Known caster、Wizard Spellbook、Prepared caster、Always Prepared / Granted dependency、High-Level Create、Level Up 均沿用既有 P1 spellcasting path。
- [x] M02 localization policy 已擴充到 `phb2014` Feat / Spell `data.desc.*`；缺 Feat 或 Spell description translation 會讓 completeness gate fail。
- [x] Character Sheet DTO / UI 新增 `passive_investigation`，並同步 `zh-TW` / `en` presentation。

## Machine-Verifiable Inventory

`scripts/verify_m01k_catalog.py` 驗證：

```text
PHB 2014 core Feats = 42
SRD 5.1 Grappler = 1
M01-K phb2014 non-SRD Feats = 41 / 41

PHB relative-to-SRD missing Spells = 42 / 42

Duplicate StableKeys = 0
```

Runtime manifest 由 `data/phb2014/manifest.json` 納管：

```text
feats-m01k-01..05       41 feat entries
spells-m01i             6 reused / enriched spell entries
spells-m01j             12 reused / enriched spell entries
spells-m01k-01..02      24 newly added spell entries
                         ---
                         42 spell entries
```

## Verification Evidence

2026-09-03 local closeout verification，branch `m01-k-phb-feat-spell-catalog`，受測 HEAD：

```text
468402a test(m01-k): sync character sheet fixture
```

Catalog / build / backend：

```text
python scripts/verify_m01k_catalog.py
M01-K catalog verified: 41 PHB non-SRD feats, 42 PHB non-SRD spells

apps/web npm run build
tsc --noEmit && vite build
passed

M01-K focused backend pytest
105 passed, 1 warning in 98.98s

Full backend pytest
573 passed, 1 warning in 261.48s

Web Vitest
17 files passed
86 tests passed
```

Browser / full-stack E2E 使用 `npm run test:e2e:docker`，避免 Windows Vite dev server 已知問題（見 `已知問題.md` KI-ENV-001）：

```text
M01-K focused Docker Playwright
6 passed in 1.3m

Full Docker Playwright
77 passed, 1 skipped in 6.5m
```

M01-K 專屬後端測試檔：

```text
test_m01k_automation_boundary.py   automation classification / static target whitelist / runtime boundary
test_m01k_feat_paths.py            Variant Human / ASI path equivalence
test_m01k_feat_prerequisites.py    ability / armor / spellcasting / OR prerequisites, repeatability
test_m01k_feat_structural.py       structural grants, Martial Adept, Tough / Observant
test_m01k_http_persistence.py      HTTP lifecycle, restart / reload persistence, version history
test_m01k_localization.py          policy coverage, negative completeness proof, runtime without docs
test_m01k_spell_builder.py         known / spellbook / prepared / granted spell paths
test_m01k_spell_catalog.py         42 spell inventory, metadata, provenance
```

M01-K browser flow：

```text
apps/web/e2e/m01k-phb-feats-and-spells.spec.ts

1. Variant Human + PHB feat with nested choice
2. non-repeatable feat disabled at next opportunity
3. ASI -> PHB Feat during Level Up
4. two Elemental Adept acquisitions + PHB spellbook spell
5. non-Fighter Martial Adept maneuver entitlement
6. PHB-only spells through class and cross-source access
```

Additional review probe：

```text
War Caster unlocked by Eldritch Knight subclass spellcasting
War Caster unlocked after earlier Magic Initiate feat spell access
```

Both compiled cleanly with expected feat acquisitions.

## Regression Findings Fixed During Gate

關門與 review 過程中修正或補強的項目：

1. `passive_investigation` 已加入 server / frontend `CharacterSheetDTO`，並補齊 `CharacterSheetPage.test.tsx` fixture；`npm run build` 恢復 green。
2. Feat choice enrichment 依 submitted order 拆分，避免 `draft:selection` placeholder 與 live structural choice 使用相同 `choice_id` 時被錯分回 foundation bucket。
3. Repeatable Feat 與 source-granted option pools 的 acquisition / nested choice identity 修正，避免合法 repeatable acquisition 被 StableKey 去重吃掉。
4. SearchableSelect 可顯示 `phb2014` Feat / Spell localized description，避免 detail fallback flicker。
5. Lucky resource metadata、Spell Sniper automation boundary、material component metadata 與 catalog structural verifier 均已補強。
6. M01-J Aberrant Mind spell replacement E2E label 已補成明確指名，避免與 M01-K spell catalog 擴充後的選項碰撞。

## Explicit Boundary

M01-K 明確不做：

- 完整 Roll Engine。
- Combat / Reaction Engine。
- 完整 Spell Engine。
- Rest transaction。
- 2024 Feats / Spells。
- 其他書籍尚未拍板的 Feat / Spell catalog。
- TCE Magic Items。
- Full M01 Integration & Closeout。

Combat / Roll / Reaction / Rest / equipment-conditional 效果只保存 identity、description、必要 structural metadata 與 deferred automation classification，不假裝已自動執行。

## Known Issues

M01-K 沒有新增已知問題。

既有專案已知問題仍在根目錄 `已知問題.md`：

- **KI-M01J-001**：M01-J 直創／逐級升等等價 E2E 曾因 harness 不穩被 park；目前完整 Docker Playwright 中同名測試已執行並通過。
- **KI-ENV-001**：Windows Vite dev server 不適合作為完整 Playwright 路徑；完整 E2E 使用 Docker web server。

## Current Handoff

**Code / static review / non-E2E gate：完成。**

**Browser / full-stack E2E gate：完成。**

**M01-K closeout：完成。M01 尚未 full closeout；K 後是否還有新 M01 規則 Subphase、以及 Full M01 Integration & Closeout 的 Subphase ID 仍由使用者後續拍板。**
