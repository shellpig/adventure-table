# M01-I Closeout

M01-I — TCE Optional Class Features & Fighting Styles 已完成並關門。

> **狀態：Full Closeout Complete**
>
> 2026-09-02 已補齊 `docs/M01/測試指南.md` 的 M01-I browser/full-stack E2E gate。M01-I 可作為 M01-J 開工前的完整關門證據。

## Implemented Scope

- [x] Optional Class Feature 使用 typed / data-driven semantics，支援 `addition`、`replacement`、`expanded_choice`、`retraining`，不把 TCE 規則只塞成 description。
- [x] Machine-verifiable Optional Class Feature inventory 已建立；Artificer 由 M01-G/H 負責，其餘 PHB classes 共 **42 / 42** 個 maintained M01-I feature identities fully accounted for。
- [x] Fighting Style 使用單一 mechanical StableKey identity跨職業引用，不為 Fighter / Paladin / Ranger複製三份內容。
- [x] Fighting Style relation exact gate：Fighter 5、Paladin 3、Ranger 3，並由 server依 class / level / enabled content derive legal pool。
- [x] Blessed Warrior nested choice：exactly 2 legal Cleric cantrips、casting ability = CHA。
- [x] Druidic Warrior nested choice：exactly 2 legal Druid cantrips、casting ability = WIS。
- [x] Superior Technique nested choice：exactly 1 legal Battle Master Maneuver；PHB + TCE maneuver expansion由同一 generic feature-pool machinery處理。
- [x] Nested selection stale-branch policy：切換 Fighting Style後，失效 child selection不會進 final Build。
- [x] Ranger replacement chain使用 generic replacement resolver；Deft Explorer / Favored Foe / Primal Awareness / Nature's Veil代表矩陣證明被替換 base grant真的從 final `feature_refs`移除，不只是 UI hide。
- [x] Expanded option pool覆蓋 Fighting Style、Battle Master Maneuver、Metamagic、Pact Boon / Eldritch Invocation與 class spell access，並重新套 prerequisites / class-level legality。
- [x] Expanded spell access只增加 selectable / prepareable eligibility；不會因 TCE expansion自動寫成 Known / Prepared。
- [x] M01-I 所需 spell content integrity已關門；expanded spell audit目前為 missing 0 / ambiguous 0。為 TCE class-list expansion補入 6 個原 PHB 2014 spell entries，不將它們偽裝成 TCE spell identity。
- [x] Bardic / Cantrip / Martial / Sorcerous / Eldritch Versatility等 retraining仍走既有 immutable Build Version workflow；M01-I沒有建立第二套 persistence/version system。
- [x] Retraining只在對應 Optional Class Feature真的已採用時出現，不因角色單純達到 minimum level就免費取得 retraining permission。
- [x] Cantrip retraining以 owning class StableKey + spell StableKey共同定位；multiclass角色即使兩個職業知道同一 cantrip，也不會換錯來源。
- [x] Pact / Invocation等 feature-pool prerequisite在 final Build、retraining之後再次驗證，不能因 base Build舊 prerequisite曾存在而留下 illegal option。
- [x] Generic pool uniqueness gate會阻止不同 choice slot重複取得同一 mechanical Style / Maneuver / Metamagic / Invocation等 option；retraining `from`控制欄位不被誤判為第二次取得。
- [x] Selected/granted feature provenance使用 `CharacterBuild.feature_grant_sources`保存；provenance feature必須仍存在於 final `feature_refs`，且 source / feature content refs必須可 resolve。
- [x] M01-I新增 rules presentation與 Builder synthetic labels已接現有 M02 localization pipeline；zh-TW / en切換不改 StableKey、Draft selection或 final Build identity。
- [x] P1 Builder lifecycle仍沿用既有 atomic/idempotent Confirm、Review、Cancel與 versioning contract；M01-I service integration只切換到 M01-I compiler wrapper，沒有重寫 P1 persistence workflow。

## Machine-Verifiable Inventory

Optional Feature maintained inventory：

```text
Barbarian  2
Bard       3
Cleric     4
Druid      3
Fighter    3
Monk       4
Paladin    4
Ranger     8
Rogue      1
Sorcerer   4
Warlock    4
Wizard     2
----------------
Total     42
```

Fighting Style exact relations：

```text
Fighter
- Blind Fighting
- Interception
- Superior Technique
- Thrown Weapon Fighting
- Unarmed Fighting

Paladin
- Blind Fighting
- Blessed Warrior
- Interception

Ranger
- Blind Fighting
- Druidic Warrior
- Thrown Weapon Fighting
```

The maintained inventory is keyed by StableKey / relation data, never translated display name.

## Verification Evidence

2026-09-01 GitHub Actions，branch `m01-i-tce-optional-class-features`，受測 code HEAD：

```text
a7f84920a6a62eb13ae01ee7003b9c4a3b821a42
```

```text
GitHub Actions — M01-I Non-E2E Regression #9
Run: 33515773964
Conclusion: success

M01-I manifest shard audit
M01_I_UNMANIFESTED_SHARDS []

Expanded spell inventory audit
M01_I_EXPANDED_SPELL_MISSING_COUNT 0
M01_I_EXPANDED_SPELL_MISSING []
M01_I_EXPANDED_SPELL_MISSING_BY_FEATURE {}
M01_I_EXPANDED_SPELL_AMBIGUOUS {}

Backend pytest
398 passed, 1 warning in 69.66s

Localization authoring unit tests
Ran 13 tests
OK

Fresh SQLite migration
alembic upgrade head
passed through 0006_character_archive

Frontend Vitest
16 test files passed
80 tests passed

TypeScript / Vite
npm run build
passed

Docker Compose
compose-config job
passed
```

Backend唯一 warning為 FastAPI / Starlette TestClient 的 `httpx` deprecation warning；GitHub hosted Actions另有 action runtime Node 20 deprecation提示。兩者均未影響 M01-I correctness。

2026-09-02 local closeout verification，branch `m01-i-tce-optional-class-features`，受測 base HEAD：

```text
f08964f fix(m01-i): resolve overlay entries by stable key
```

本 closeout commit 另修正 M01-I E2E spec 的兩個 selector / fixture label 問題：

1. `getByRole('button', { name: /Class/ })` 會同時匹配 Class step 與 Optional Class Feature combobox toggle；改為明確點擊 `Class Level-by-level rail`。
2. Superior Technique nested maneuver 的 UI label 為 `Maneuver: Ambush`；測試不再用裸 `Ambush`。

Local closeout commands：

```text
M01-I manifest shard audit
M01_I_UNMANIFESTED_SHARDS []

Expanded spell inventory audit
M01_I_EXPANDED_SPELL_MISSING_COUNT 0
M01_I_EXPANDED_SPELL_MISSING []
M01_I_EXPANDED_SPELL_MISSING_BY_FEATURE {}
M01_I_EXPANDED_SPELL_AMBIGUOUS {}

M01-I backend pytest
14 passed

Backend pytest
399 passed, 1 warning in 108.04s

M01-I localization Vitest
1 test file passed
4 tests passed

Frontend Vitest
16 test files passed
80 tests passed

TypeScript / Vite
npm run build
passed

Localization authoring unit tests
Ran 13 tests
OK

Docker Compose
docker compose config
passed

Clean full-stack readiness
/ready passed
web root passed
seed_p0_fighter_wizard passed
```

M01-I mandatory browser/full-stack E2E gate：

```text
npm run test:e2e -- m01i-optional-features.spec.ts
5 passed in 39.1s

1. Fighter + TCE Fighting Style + Superior Technique nested maneuver
2. Paladin + Blessed Warrior + two Cleric cantrips with Charisma
3. Ranger + Druidic Warrior + two Druid cantrips with Wisdom
4. Ranger replacement flow removing represented base grants from final Build
5. Existing Fighter Level Up + Martial Versatility + Version History
```

Full browser regression on clean Docker full stack：

```text
npm run test:e2e
58 passed in 3.3m
```

## Regression Findings Fixed During Gate

Non-E2E closeout過程實際抓到並修正下列問題，而不是只新增 happy-path tests：

1. `Additional Cleric Spells` 等 expanded spell access最初引用未安裝 PHB spell，registry fail-fast。新增全量差集 audit後一次定位 6 個缺口並補正式 PHB identities；最終 missing / ambiguous皆為 0。
2. Multiclass角色同一 cantrip可由不同 class來源 Known；原 retraining只比 spell key可能改錯來源，現改為 class source isolation。
3. Versatility本身是 Optional Class Feature；原流程只看 level gate可能在未採用 feature時開 retraining，現要求 feature active。
4. Pact Boon retraining後，舊 Pact prerequisite的 Invocation可能因 pre-retraining eligibility而殘留；現於 final Build重新驗 dependency。
5. 不同 choice slot原本只各自防 duplicate，可能重複取得同一 Fighting Style / Maneuver等 mechanical option；現加入 generic cross-slot uniqueness gate。
6. `feature_grant_sources`初版缺 final reference/invariant validation；現要求 provenance唯一、feature仍存在於 final Build、所有 content refs可 resolve。
7. Branch上的 Builder service曾偏離 current P1 lifecycle contract，造成 Review / Confirm / Cancel regression；已恢復 main 的既有 atomic/idempotent lifecycle，M01-I只保留 compiler integration。修復後 backend由 15 failures收斂到既有 M01-G obsolete assertion。
8. M01-G舊測試假設 TCE pack永遠沒有 SpellEntry，與 M01-I正式 spell content衝突；更新為真正的 Artificer legality regression：TCE spell可存在，但只有合法 Artificer spell會進其 available pool。

## Static Review

Closeout checkpoint前重新檢查 `main...m01-i-tce-optional-class-features`：

- branch為 **ahead-only**：ahead 59 / behind 0；merge base即 current main。
- `service.py`相對 main只剩 M01-I compiler import / invocation整合，沒有保留先前誤帶入的 P1 lifecycle rewrite。
- M01-I規則集中在 content relation、generic optional-feature runtime/compiler/validation/provenance與對應 tests；沒有 Ranger-only / FightingStyle-only persistence system。
- Fighting Style、Maneuver、Metamagic、Invocation、Pact option都以 StableKey / pool relation作 identity，display name與 locale不參與 legality/dedupe。
- Replacement / retraining的 final legality不是靠 Frontend hide；server compiler / validation負責 final Build invariant。
- Additional Spells保留「access expansion」語意，不等同 automatic Known / Prepared grants。
- 新增 PHB spell gaps保留 PHB source identity；TCE只透過 optional-feature overlay增加 class eligibility。
- M01-I沒有提前建立 Combat trigger、Reaction、Bonus Action、Rest或 Magic Item runtime。

目前未發現剩餘 blocking static-review issue。

## Explicit Boundary

M01-I本階段仍明確不做：

- Combat trigger / Reaction / Bonus Action timing engine。
- Rest engine。
- arbitrary feature patch DSL。
- TCE Magic Items。
- M01-J subclass expansion內容。

## Current Handoff

**Code / static review / non-E2E gate：完成。**

**M01-I browser/full-stack E2E gate：完成。**

**M01-I full closeout：完成。下一個可開工 Subphase 是 M01-J — 2014 Class Subclass Expansion。**
