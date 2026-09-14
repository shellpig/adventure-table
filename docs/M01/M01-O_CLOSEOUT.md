# M01-O Closeout Checklist

M01-O — XGE & TCE Feat Expansion closeout scope（對應 `實作規格.md` §8.2 第 1～17 條）：

- [x] **Inventory 完整且來源正確**：XGE 15 / TCE 15，共 30 個 Feats 全數由 Registry 解析；StableKey 唯一、pack provenance 為既有 `xge` / `tce`；`data/xge/feats-m01o.json`、`data/tce/feats-m01o.json` 與兩個 manifest 同步（pack 條目 266→281、401→416）。`scripts/verify_m01o_feat_inventory.py` 為 deterministic verifier。
- [x] **沿用同一套 Feat acquisition**：Variant Human、ASI → Feat、High-Level Create、Level Up 皆走 M01-K 既有 opportunity / prerequisite / nested-choice resolver；未建立 XGE/TCE 專用 Builder。
- [x] **ancestry / lineage / size prerequisite**：`m01o_prerequisites.py` 新增 ancestry、lineage、size、feature、proficiency、spellcasting atom 與 `any_of` compound；Variant Human 以 `variant_of` normalization 視為 Human；Half-Elf variant / Tiefling bloodline 保留 base ancestry；判定不依賴顯示名稱。
- [x] **既有 prerequisite atom 共用並擴充**：`{"type": "spellcasting"}` 改以 candidate Build 的最終 features 判定，Eldritch Knight / Arcane Trickster 可通過；同一擴充回饋給 PHB Elemental Adept / Spell Sniper / War Caster。
- [x] **Ability +1 為 structural choice**，受 20 上限與既有 ASI/feat compile 規則約束。
- [x] **技能／工具／語言／Expertise 結構化**：Prodigy、Skill Expert、Squat Nimbleness、Chef、Poisoner 沿用既有 proficiency / language / expertise primitive；Artificer Initiate 自選工匠工具並產生 `SpellcastingFocusFact` typed relation；Fey Teleportation 的 Sylvan 為正式 `language_grants`。
- [x] **既有 option pool 重用**：Fighting Initiate 用 Fighter style pool 並排除已擁有 style（雙向：class slot 也 disable feat 已給的 style，`pool_option_granted_by_feat`）；Eldritch Adept 用 canonical invocation pool，有 prerequisite 的 invocation 只有符合條件的 Warlock 可選；Metamagic Adept 兩個 distinct option。不複製第二份 catalog。
- [x] **Feat-linked retraining 版本化**：`on_any_level_up`（Eldritch Adept）／`on_asi_level_up`（Fighting Initiate、Metamagic Adept）policy，每次 Level Up 最多替換一項；Build Edit 不是 retraining 路徑；Version N / N+1 各自保留。
- [x] **Feat-granted spell access**：Drow High Magic、Fey Teleportation、Wood Elf Magic、Artificer Initiate、Fey / Shadow Touched、Telekinetic、Telepathic 皆以 `source_type="feat"` 的 `SpellAccessEntry` 保存 casting ability / uses / recharge；不污染 class Known / Prepared。
- [x] **選定能力值同時驅動 spellcasting ability**（Fey / Shadow Touched、Telekinetic、Telepathic）。
- [x] **static / derived substrate 接線**：Dragon Hide 走 Natural Armor AC candidate；Squat Nimbleness +5 ft 走 movement contribution；Infernal Constitution resistance / poisoned-save advantage 為 typed mechanics；Gunner firearms 為 `WeaponProficiencyCategoryFact`（不引用不存在的 firearm item）；Telepathic 60 ft 為 `TelepathyFact`（range、需可見、需共通語言、不賦予回覆）。三種 typed fact 住 `CharacterBuild.feat_static_facts`。
- [x] **Metamagic Adept 2 Sorcery Points**：獨立 resource `metamagic-adept-sorcery-points`，`stacking: separate`、`allowed_spend_tags: ["metamagic"]`。
- [x] **automation boundary 逐 Feat 分類**：30 個 Feats 各有 `automation`；deferred 類不改任何 derived 值；content / character domain 靜態掃描無 combat / trigger DSL 相依。
- [x] **Character presentation 雙語完整**：`zh-TW` / `en` 30 個 Feats name + desc、新 prerequisite atom 與 issue code 的 Builder 訊息（`m01kBuilderMessages.ts` 擴充）。
- [x] **Persistence / provenance**：8 個代表 Build 經 confirm → reload → server restart → reload，acquisition、spell link、resource、typed fact、content_sources、Version History 一致。
- [x] **Standalone 可用**：standalone Create → export → 另一 standalone import → re-export 相等，`feat_static_facts` 隨行；import boundary / schema inventory / ref walker gate 已登記新欄位。
- [x] **Downstream P2 / P3**：O-E2E-01～06 全部從 Room Character Workspace 起；`CharacterBuild` 新增 optional 欄位 `feat_static_facts`，全套 backend pytest（含 P2 / P3 suites）綠燈；Character identity 與 P3 sheet payload contract 未改。

## Verification evidence

2026-09-13 最終驗證，分支 `m01-o-implementation` HEAD `499c830`：

```text
cd apps/server
..\..\.venv\Scripts\python.exe -m pytest
1486 collected、exit 0：1447 passed、39 skipped、0 failed（skip 全為 `POSTGRES_URL` / `M03B_POSTGRES_URL` 未設的真 PostgreSQL migration gate；M01-O 無 Alembic migration，不受影響）

cd apps/web
npm test -- --run
75 test files / 368 tests passed

npm run build
tsc --noEmit clean；vite build 成功（既有 chunk-size 與 INEFFECTIVE_DYNAMIC_IMPORT 警告，非本次引入）

docker compose config
exit 0

ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1 npm run test:e2e:docker -- e2e/m01o-feats.spec.ts
6 passed (1.3m)
```

E2E 走容器化 `web` / `server`（KI-ENV-001 規避路徑），reset 前已確認 DB 只有 P0 fixture 與前次 E2E 殘留角色，並以 `pg_dump` 備份。

合併回 `main` 前於 `56310b0` 執行全套 E2E：

```text
ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1 npm run test:e2e:docker
127 total：120 passed, 3 failed, 4 skipped (10.1m)

ADVENTURE_TABLE_MCP_PUBLIC_ORIGIN= ... npm run test:e2e:docker -- e2e/m04c-ai-join-kit.spec.ts
5 passed
```

3 個 failed 全在 `m04c-ai-join-kit.spec.ts`，原因是本機 `.env` 帶著 M04-B 真實 ChatGPT 測試留下的 `ADVENTURE_TABLE_MCP_PUBLIC_ORIGIN`，compose 轉給 server 後 `/api/mcp/public-origin` 回傳 Tailscale origin，而該 spec 斷言「尚未設定公網入口」狀態（M04-C closeout 的 E2E 證據來自未設此變數的 CI）。把變數清空重跑 5 / 5 通過，與 M01-O 無關。4 個 skipped 為既有靜態 gate：`character-sheet` visual smoke、`KI-M01J-001` fixme、`m03c` 兩條 xge-less 專用案例。

M01-O backend 覆蓋為 7 個測試檔（`tests/test_m01o_*.py`）共 50 個測試，加上 `scripts/verify_m01o_feat_inventory.py`；各契約與測試的逐條對照見 `測試指南.md` §10.14。瀏覽器覆蓋為 `apps/web/e2e/m01o-feats.spec.ts`（O-E2E-01～06，FC-E2E-23），共用 helper `e2e/support/builderUi.ts`。前端單元測試新增 `src/i18n/m01oBuilderMessages.test.ts`。

## M01-O Closeout Evidence

```text
Scope / expected inventory: XGE 15/15 + TCE 15/15 = 30/30
Content / schema validation: PASS（verifier：StableKey 唯一、pack provenance、prerequisite / automation / choice kind 白名單、dangling ref、manifest count、spell selector 候選、zh-TW / en 不走 fallback；`feat_static_facts` 已登記於 M03 schema inventory / ref walker）
Domain legality / calculations: PASS（ancestry / lineage / size / spellcasting 正反例、nested choices、option pools、Natural Armor / speed / typed facts、Metamagic 限制）
Persistence / versioning: PASS（Create / Level Up retraining / Version History；Build Edit 非 retraining 路徑）
Localization completeness: PASS（zh-TW / en 30 Feats + 新 prerequisite / issue 訊息）
Runtime without docs: PASS（`test_runtime_does_not_read_reference_markdown`：`app/` 無 docs 引用；content root 複製到 tmp_path 後 Registry / Builder / localization 正常）
Focused API integration: PASS（`test_m01o_retraining.py` 走 Room-scoped HTTP：Create / Level Up / Version draft / History）
Focused Playwright: 6 / 6（O-E2E-01～06，容器化 web / server）
Restart persistence: PASS（8 個代表 Build 經 `rebind_http` 重啟）
Human smoke: PASS（2026-09-14 由使用者真人執行 10.12 三類代表 Feat：racial prerequisite / 多段 nested / spell-option pool，含 disabled reason、choice 順序、Review 與 Sheet 呈現，以及 deferred Combat 效果未被 UI 誤導為自動套用；O-E2E-01 / 02 / 05 / 06 另有真實瀏覽器覆蓋。過程發現 Builder 側欄「已解析授予項目」的 `feat` kind 標籤在 zh-TW 顯示 raw `FEAT`，已由 `f3a7b18` 補 `builder.grant.feat` 並統一 summary / review 的 `GRANT_KIND_KEYS`）
M03 standalone compatibility: PASS（standalone round trip、import boundary、schema inventory、ref walker）
Downstream P compatibility: P2 PASS（O-E2E 全走 Room Character Workspace；全套 pytest 含 P2 suites）；P3 PASS（全套 pytest 含 P3 suites；Character identity / sheet payload contract 未改，新欄位為 optional）
Existing focused regression: PASS（m01i / m01k / m01l / m01m / m03 import boundary / m03b 皆綠）
Known manual/deferred effects: 15 個 deferred Feats — Bountiful Luck / Second Chance / Fade Away（reaction）、Dragon Fear / Crusher / Slasher / Telekinetic push / Dwarven Fortitude / Orcish Fury / Gunner Loading 與近身遠程（combat）、Elven Accuracy / Flames of Phlegethos / Piercer（roll）、Poisoner crafting（inventory）、Chef（rest）。皆保存 identity / usage / recharge / description，UI 不聲稱自動套用；等 P4+ 對應 substrate
```

## 關門過程中修正的問題

1. **docs-free 測試直接改名真實 repo 目錄。** 首版 `test_runtime_does_not_read_reference_markdown` 會 rename `docs/暫用規則資訊`，測試中斷或 OneDrive 權限錯誤都會讓 working tree 留下改名後的目錄。已改為把 content root 複製到 `tmp_path` 並以 `ADVENTURE_TABLE_CONTENT_ROOT` 指向，fixture 完整隔離。
2. **class spell 污染測試斷言不足。** `test_feat_spell_access_does_not_pollute_class_known_or_prepared_lists` 原本只驗 class entries 的 `source_key`，若 feat spell 被誤寫成 class entry 測不到。已補 class 來源 `spell_key` 集合與 baseline 完全相等。
