# P4-A Closeout Checklist

P4-A — Monster & Combatant Foundation closeout scope。編號對應 [實作規格](實作規格.md) 的「完成後必須為真」。

- [x] 1. Template / Instance / Combatant 三個概念分開。Template 是 `monster_templates.rules` 與 SRD content entry（可重用規則）；Instance 是 `monster_instances`（`current_hp`、`temp_hp`、`conditions`、`effects`、`combat_status`、`initiative`、`reaction_available`、`resources`、`visibility`、`position_note`）；Combatant 是 `app.domain.combat.CombatantState`，由 `monster_instance_to_combatant()` adapter 從 Instance 組出，不直接暴露 DB row。
- [x] 2. SRD 5.1 Monster corpus 進正式 content pipeline。`data/srd5.1/monsters.json` 由 `app.content.p4a_import_monsters` 從 pinned source materialize：`5e-bits/5e-database@ce47a18dfeb3e41a1b2a2dfe00a25761c3c3a4f1` / `src/2014/en/5e-SRD-Monsters.json`，blob sha `4193e12e8be65e3c97da4787f5591233c4333111` 寫進 `manifest.json` 的 `provenance.monster_corpus`，並帶 `expected_monster_count=334` / `expected_beast_count=87`。`validate_p4a_monster_inventory()` 在 `load_default_content_registry()` 對兩個 count 做 exact gate；多一筆、少一筆、duplicate index 都 fail。runtime 不抓 GitHub。
- [x] 2a. `zh-TW` / `en` label coverage 同步交付。`data/localization/localizable-fields.json` 把 Monster `name` 與 `special_abilities / actions / bonus_actions / reactions / legendary_actions` 的 `*.name` 列為 `currently_user_visible` 且 `required_locales=["zh-TW","en"]`；`data/srd5.1/locales/zh-TW/monster.json` 由 `scripts/build_p4a_monster_locale.py` 產生，1837 個必要 label 全數有 explicit zh-TW（`p4a-monster-zh-tw-report.json` `missing_count=0`）。`test_monster_english_is_complete_but_zh_tw_fallback_is_not` 證明 English fallback 不會被算成 zh-TW 完成。long-form `desc` 尚未 expose 給 Human UI / MCP，維持 canonical English，依規格延後到首次 user-visible exposure 的 Subphase。
- [x] 3. Template 核心欄位。`MonsterData`（typed schema，`extra=forbid`）承載 name / size / type / AC / HP average + `hit_points_roll` / speed / 六項 ability，SRD 有資料時承載 proficiencies（saves + skills）/ resistances / immunities / vulnerabilities / condition immunities / senses / languages / CR / XP。`monster_to_reusable_rules()` 把它 normalize 成 template rules。
- [x] 4. Combat 能力。`traits`（special abilities）/ `actions` / `bonus_actions` / `reactions` / `legendary_actions` / spellcasting（`MonsterSpellcastingData`：ability、DC、modifier、slots、spells）全部保留在 typed schema 與 template rules；Multiattack、Recharge（`usage`）、Legendary Action 為 upstream 結構直通。
- [x] 5. 可靠結構化的資料結構化，複雜能力保留 description。`normalize_monster_action()` 對每個 action 加上 canonical `MonsterAction` 欄位：`kind`（attack / save / utility / other）、`attack_kind`（`melee_weapon` / `ranged_weapon` / `melee_spell` / `ranged_spell`）、`attack_bonus`、`damage_parts[]`、`save_ability` / `save_dc`、`reach` / `range_normal` / `range_long` / `target`、`automation_level`（structured / partial / dm_adjudication）；upstream 欄位以 `extra=allow` 原樣保留，`desc` 不丟。334 隻全數 normalize 通過：actions 分布 structured 412 / partial 432 / dm_adjudication 108；`attack_kind` melee_weapon 468 / ranged_weapon 58 / melee_spell 4 / ranged_spell 3。沒有 generic effect DSL。
- [x] 6. Monster Instance live state。`monster_instances` 欄位見第 1 條；DB CheckConstraint 鎖 `current_hp >= 0`、`temp_hp >= 0`、`combat_status ∈ {active, down, dead, removed}`、`visibility ∈ {public, hidden}`、`template_key` 與 `custom_template_id` 互斥。`MonsterRepository.update_live_state()` 是唯一 live-state 寫入口。
- [x] 7. Quick Enemy。`create_quick_enemy()` 只要 Name / AC / HP / Speed 即可建立 `template_key=None` 的 Instance；不帶 attack 可存在；帶 `{"name": "Club", "attack_bonus": 4, "damage": "1d6+2"}` 時經 `normalize_monster_action()` 寫進 `rules_snapshot["actions"]`，未指定 `attack_kind` 預設 `melee_weapon`，落在 `automation_level="structured"`，DM projection 可直接看到，P4-C resolver 與 SRD monster action 走同一個 shape。
- [x] 8. Save as Monster Template 不帶 instance state。`save_instance_as_template()` 只複製 `rules_snapshot`；`current_hp` / `initiative` / `reaction_available` / `conditions` / `resources` 是獨立欄位不在 rules 內。`test_save_as_template_copies_rules_but_not_live_state` 從打到剩 3 HP、initiative 21、reaction 已用的 instance 存成 template，再 spawn 出來是滿血、無 initiative、reaction 可用。
- [x] 9. NPC 與 Monster 不合併。本 Subphase 沒有動 NPC；`monster_instances` 沒有 NPC 欄位，也沒有把 Monster 轉成故事角色的路徑。
- [x] 10. DM full view / Player safe view 從本 Subphase起分開。`project_combatant(state, audience=, enemy=)` 是唯一 projector：DM 拿完整 state；Player 對友方拿完整機械數值但去掉 `dm_notes`；Player 對敵方走固定 allowlist（id / kind / name / combat_status / `injury_level` / public conditions / public effects / initiative），exact HP、AC、`resources`、hidden conditions、`reaction_available`、`position_note` **key 不存在**而不是 value=null；`visibility=hidden` 的敵人對 Player 回 `None`。`injury_level` 由 current / max HP 即時算，不另存 truth。AC / description / position note 需各自顯式 reveal flag，且 reveal 一項不會連帶解鎖其他項。
- [x] 11. 不建立 round / turn lifecycle、Attack resolve UI 或 geometry。本 Subphase 沒有 Combat table、CombatService、REST route、MCP tool 或前端改動；`initiative` 只是 Instance 上的 nullable 欄位，沒有 order 計算。
- [x] 12. Standalone 不載入 Monster / Combat schema 或 route；Character Core 不 import Combat。`0022_p4a_monster_instances` 接在 `0021_m04b_ai_oauth` 之後落在 web track，character track head 仍是 `0015_character_state_revision`；`test_standalone_character_migration_does_not_create_p4a_combat_schema` 對 standalone SQLite 跑 migration 後斷言 `monster_templates` / `monster_instances` 不存在；`test_standalone_exposes_no_combat_api_routes` 掃 standalone OpenAPI；`test_character_core_does_not_import_combat_modules` 靜態掃 `app/domain/character*`。`tests/test_m03_import_boundary.py` 的 `FORBIDDEN_MODULE_RE` 已加入 `combat(s)` 與 `monster` / `monsters` / `monster_*` module segment，並補正反例 fixture，`app.content.p4a_monsters` 這類 content module 不被誤判。Monster Template content（`monsters.json` + zh-TW shard）進共用 ContentRegistry，Standalone 可讀 content 但沒有 Instance / Combat persistence。

## Static review findings 與處理

分支上兩輪 review 提出的問題與結果：

| # | Finding | 處理 |
|---|---|---|
| R1 | Quick Enemy attack 存在 `rules_snapshot["attacks"]`，adapter 只讀 `actions`，DM projection 看不到 | `c3904431`：quick attack 改寫進 `actions` 並走 `normalize_monster_action()` |
| R2 | 沒有開發設計方針 4.1 的 canonical `MonsterAction` / `automation_level` | `c3904431`：新增 `MonsterAction` / `DamagePart`，所有 SRD action 與 quick attack 共用 |
| R3 | 測試指南 A.2 缺「同一 Template 的 Instance A / B 互不影響」 | `c3904431`：`test_goblin_template_instances_keep_independent_live_state` |
| R4 | `test_m03_import_boundary.py` 未擴充 combat / monster module segment | `c3904431`：regex 與 fixture 同步擴充 |
| R5 | Quick Enemy attack 被判 `partial`（無 desc 推不出 `attack_kind`） | `fadb175c`：repository 對 quick attack 預設 `melee_weapon`，測試改鎖 `structured` |
| R6 | `attack_kind` 只有 `melee / ranged / spell / other`，與設計契約四值不符 | `fadb175c`：改為 `melee_weapon / ranged_weapon / melee_spell / ranged_spell`，無法辨識時 `None` |
| R7 | migration `0022` 沒有真 PostgreSQL 證據，`p4a-non-e2e.yml` 沒有 postgres job | `fadb175c` / `163661cd`：新增 `postgres-migrations` job（postgres:17，同時供給 `P4_` / `P3_` / `P2_` / `M03C_POSTGRES_URL`），JUnit 0-skip assert + artifact |
| R8 | `_attack_kind` 留有 `melee` / `ranged` 舊值轉換死碼；`p4a_inventory.py` 註解仍說 corpus 尚未 check-in；PG 只測 upgrade | `19c76b1e`：移除死碼、改寫註解為「srd5.1 pack 可被停用」的真實理由、補 PG downgrade round-trip |

## Verification evidence

分支 `p4-a-monster-combatant-foundation`，最終 code SHA `19c76b1e`。本 closeout 文件、`PROJECT_BRIEF.md` 與 P4 三份文件的合併規則修正為其後的 docs-only commit，不動產品碼與測試。依使用者 2026-09-15 拍板，P4 每個 Subphase 關門後各自合併回 `main`（見 [實作規格](實作規格.md) 第 11 條），P4-A 於同日以 `--no-ff` 合併。

```text
Alembic heads（apps/server: alembic heads）
  0015_character_state_revision (character) (head)
  0022_p4a_monster_instances (web) (head)
  0022 接在 0021_m04b_ai_oauth 之後，character track 未變。

Backend pytest（全套，執行於 19c76b1e 工作樹，cwd apps/server，..\..\.venv\Scripts\python.exe）
  exit 0；skip 全為 PostgreSQL env-gated（M03B / M03C / P2 / P3 / P4-A），本機未設對應 URL
  GitHub backend job（19c76b1e run 34919130863）：1505 passed / 43 skipped（多出的 1 skip 為新增的 PG downgrade test 在無 PG 的 backend job）

Focused P4-A backend（執行於 19c76b1e，本機）
  tests/test_p4a_monster_schema.py 3
  tests/test_p4a_import_monsters.py 6
  tests/test_p4a_monster_registry.py 6
  tests/test_p4a_monster_localization.py 4
  tests/test_p4a_locale_shards.py 3
  tests/test_p4a_monster_template_normalization.py 8
  tests/test_p4a_monster_persistence.py 9
  tests/test_p4a_monster_combatant_adapter.py 5
  tests/test_p4a_combatant_projection.py 10
  tests/test_p4a_monster_migration.py 2
  tests/test_p4a_standalone_combat_boundary.py 3
  tests/test_p4a_postgres_migration.py 3（本機以 docker postgres 上的一次性 scratch DB
    adventure_table_p4a_scratch 執行 3 passed，跑完即 drop；未觸碰 daily adventure_table）
  加 tests/test_m03_import_boundary.py 5
  合計 67 tests：本機無 P4_POSTGRES_URL 的一輪 64 passed / 3 skipped，
  PG 3 支另以上述 scratch DB 執行 3 passed

PostgreSQL migration gate（GitHub, P4-A Non-E2E Regression / postgres-migrations）
  163661cd run 34913123592：tests=26 passed=26 skipped=0 failures=0 errors=0
    涵蓋 test_p4a_postgres_migration（0021 → 0022、heads）＋ P3 / P2 / M03C legacy PG suites
  19c76b1e run 34919130863：tests=27 passed=27 skipped=0 failures=0 errors=0（加入 downgrade round-trip）

Monster corpus / locale 證據
  data/srd5.1/monsters.json：334 entries，type=beast 87
  manifest provenance.monster_corpus.upstream_blob_sha = 4193e12e8be65e3c97da4787f5591233c4333111
  data/localization/p4a-monster-zh-tw-report.json：required_label_count 1837 / translated 1837 / missing 0
  workflow P4-A Monster Corpus run 34855394977 @ 5bd4106f success（re-materialize 無 diff）
  workflow P4-A Monster Localization run 34855394833 @ 5bd4106f success（re-author 無 diff）

Frontend unit / build
  本 Subphase 未動 apps/web；GitHub frontend job（19c76b1e run 34919130863）381 tests passed、vite build success

docker compose config
  exit 0（本機）；GitHub compose-config job success

E2E（Subphase 關門本身不需要：backend-only diff；以下為合併回 main 的 gate）
  本機 npm run test:e2e:docker（ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1，
  走 U01-A 的 adventure_table_e2e + server-e2e / web-e2e，rebuild server + web image）
  執行於 19c76b1e 工作樹（僅多本 closeout 的 docs 變更）：
    主套件 127 tests：123 passed / 4 skipped（9.9m）
    disabled-pack 套件 7 tests：7 passed
  exit 0

GitHub Actions @ 19c76b1e
  P4-A Non-E2E Regression run 34919130863：backend / postgres-migrations / frontend / compose-config 全 success
  P4-A Monster Corpus run 34919130941：success（p4a_inventory.py 註解變動觸發，re-materialize 無 diff、未產生 auto-commit）
```

## 已知限制 / 留給後續 Subphase

- `automation_level` 只是 normalize 時的靜態分類，P4-C 才決定 `structured` 直接 resolve、`partial` 帶 hint、`dm_adjudication` 停給 DM 的實際行為。
- `attack_kind=None` 的 419 個 action（Multiattack、save-based、utility 等）與 108 個 `dm_adjudication` action 依規格保留 description，由 DM adjudication；不會為了它們建 DSL。
- Monster long-form `desc` 尚無 zh-TW；第一個 expose 它的 Subphase（預期 P4-E stat block UI 或 MCP context）必須同 Subphase 補齊。
- `monster_instances` 目前只有 repository，沒有 REST / MCP 入口；「猜 instance id 也拿不到 full view」在 P4-A 只能在 projector 層驗證，route 層驗證留給 P4-B / P4-E 接線時。
