# M07-A — Room Monster Library · Closeout

日期：2026-10-03　Branch：`feat/m07a-room-monster-library`（自 `main@bdd3ee0a`）　Worker：agy（A1、A2）、指揮者（A3）

Commit：A1 `cb6324a6`、A2 `5d8acdfb`、A3 `fa0e536b`（補兩個驗收測試），以及合併前修正（列表搜尋競態）。

## 驗收對應

Backend 測試在 `apps/server/tests/`，前端測試在 `apps/web/src/`，E2E 在 `apps/web/e2e/`。

| 契約 | 證據 |
|---|---|
| A.1 無 Session 管理庫；內建唯讀；複製成自訂；從零建立 | `test_m07a_library_lifecycle.py`：`test_monster_library_no_session_needed`、`test_monster_library_builtin_read_only_and_desc_presentation`、`test_copy_builtin_to_custom_without_name`／`_with_custom_name`、`test_create_custom_monster_from_zero`、`test_copy_custom_template` |
| A.1 Quick Enemy 存成模板只存規則 | `test_save_from_quick_enemy_instance_rules_only` |
| A.1 只改 AC 保留其他能力 | `test_patch_only_armor_class_preserves_everything_else`。A3 改用 Cult Fanatic（同時有 Multiattack 與 Spellcasting），並斷言 AC 以外的 rules 完全相同 |
| A.1 雙語名稱／能力名稱；內建 desc 以英文原文標示且不入搜尋 | `test_monster_library_search_and_desc_exclusion`、內建呈現測試（`ability_names` 含 reactions／legendary actions）<br>前端：`monsterLibraryCopy.test.ts`（SRD size／type／alignment 雙語、自訂值照原文）<br>E2E：`m07a-monster-library.spec.ts` zh-TW 案例（中文名稱與能力名稱、desc 英文＋「英文原文」標示、desc 字詞搜尋不命中）<br>`data/` 本 Subphase 零改動，zh-TW locale 檔沒有寫入英文 desc |
| A.2 migration（空表、seeded rows 按 Campaign 回填 Room，id／rules／來源與 Instance 快照不變） | `test_m07a_migration_and_references.py`：`test_sqlite_migration_0041_empty_table`、`test_sqlite_migration_0041_seeded_campaign_bound_rows`、`test_postgres_migration_0041`（真 PG）<br>`test_p4a_postgres_migration.py::test_p4a_schema_survives_full_postgres_upgrade_to_heads`：升到 heads 時檢查 Room scope 與 `RESTRICT` |
| A.2 跨 Room 拒絕 | `test_multi_room_isolation`、`test_m07a_authorization_and_mcp.py::test_create_instance_from_custom_template_cross_room_rejected` |
| A.2 各種引用阻擋刪除 | `test_references_block_delete_matrix`、`test_mutation_history_blocks_template_delete`（世界異動歷史） |
| A.2 封存不出現在新增選單；一般建怪與新引用都拒絕；Human 仍可讀、可複製 | `test_archive_lifecycle_and_p6_references` |
| A.2 Room Hard Delete | `test_room_hard_delete_cleans_instances_and_templates` |
| A.2 新增 `custom:` 參照 × 刪除競爭（真 PG、兩條 connection） | `test_postgres_race_add_p6_ref_vs_delete_template` |
| A.2 stale revision 零副作用 | `test_stale_expected_revision_zero_side_effects` |
| A.3 Human／AI DM 由最新版建 Instance；target Campaign 同 Room | `test_human_and_ai_dm_create_instance_from_custom_template_same_room` |
| A.3 改模板不影響既有 Instance | `test_editing_template_does_not_mutate_existing_instance` |
| A.3 AI 不能存入庫；AI token 不能代替 Room access | `test_ai_cannot_save_to_library_and_ai_token_rejected_on_rest` |
| A.3 Player、pre-session、revoked、taken-back grant 不能查庫 | `test_ai_read_grants_access_control` |
| A.3 Owner 坐 Player Seat 仍可管理；只有 Room DM authority、不坐 DM Seat 也可管理 | `test_human_room_authority_matrix` |
| A.3 Member 即使控制 DM Seat 仍不可管理 | `test_member_controlling_dm_seat_still_lacks_library_authority`（A3 新增） |
| REST／MCP：`content_key` 同時接受內建 key 與 `custom:<uuid>`；舊 SRD 呼叫可用 | `test_m07a_authorization_and_mcp.py` 的 MCP dispatch／REST 案例<br>`test_p4e_mcp_combat_lifecycle.py`、`test_m04c_tool_descriptions.py` 回歸 |
| Browser 兩 locale：建立、複製、改 AC、封存、引用中刪除錯誤、refresh；Member 直貼 URL 拿不到資料 | `m07a-monster-library.spec.ts` 三個案例 |
| UI：owner／dm 才有入口；送出中按鈕停用；`expected_revision` | `RoomWorkspacePage.test.ts`、`RoomMonsterLibraryPage.test.tsx`、`SessionCombatDmControls.test.tsx`、`SessionCombatMonsterControls.test.tsx`、`api/monsterLibrary.test.ts` |

## 關門 gate

全部在本機 HEAD `5d8acdfb` ＋ A3 測試上跑：

- **全套 backend pytest**（`P4_POSTGRES_URL=…/adventure_table_p4`）：exit 0，3,114 passed、39 skipped、0 failed。39 個 skip 都是 P2／P3／M03B／M03C 專屬 PG job 的既有環境條件；M07-A 與 P4／P5 的 PG 測試全部實跑。
- **A3 新增測試後**：`test_m07a_*`＋code quality 帶 PG 重跑，全過。
- **Frontend**：`npm test -- --run` 117 files、926 passed；`npm run build` 通過。
- **`docker compose config`**：預設與 `--profile e2e` 都通過。
- **受影響 E2E**（Docker，`adventure_table_e2e`），分三個 project 跑，共 17 passed、0 failed：
  - `parallel`：m07a、p2a、p4e、p5f、p5g-tactical-full-journey、p6a、p6g-adventure-journey、p6g-empty-campaign，13 passed。
  - `serial-restart`：p4f-full-combat-journey，1 passed。
  - `baseline-room`：m02h-bilingual-site-smoke，3 passed。
  - 選這些 spec 的理由：Session 戰鬥 DM 控制與 Monster 控制，以及 Workspace 入口按鈕。
- **M03 boundary／schema parity**：已含在全套 backend 中。新增的多人 package 已加進 forbidden regex 並附 negative assertion；Standalone 仍只升 `character@head`。
- **合併前全套 Docker E2E**（`npm run test:e2e:docker` 無參數，2026-10-03）：
  - **第 1 次**：`parallel` 這趟 107 passed、3 failed、3 skipped，script 隨即中止。
    - m07a zh-TW 案例失敗，是真的缺陷：負載下，頁面初次載入的「全部列表」回應比後送的搜尋回應更晚回來，把搜尋結果蓋掉。已修，`RoomMonsterLibraryPage.tsx` 加請求序號，只採用最新請求的回應。
    - 另外 2 個失敗是 p1f、p1g。
  - **第 2 次（含修正）**：`parallel` 這趟 106 passed、4 failed、3 skipped，script 中止。m07a 這次通過。4 個失敗：
    - m01e ×2：worker 以 0xC0000409 崩潰，即 KI-ENV-002，測試本體沒有執行。
    - p1f：KI-P1F-001 的症狀。
    - p5f：等戰術地圖 radio 逾時；這個 spec 在 A3 的受影響 E2E 是通過的。
  - **依 KI-ENV-002 的做法手動補跑**：
    - 單獨重跑 m01e、p1f、p5f：6 passed。
    - `baseline-room`：30 passed、1 skipped。
    - `serial-restart`：2 passed。
    - 關掉 xge 的 m03c：7 passed。
  - **合計**：各 spec 都至少完整通過一次，0 個未解失敗。p1f 這次單獨重跑通過，與 KI-P1F-001「單跑也穩定失敗」的記載不同，建議 verifier 更新該條。

## 指揮者審核修正摘要

詳見 [A1](M07-A_steps/A1.md)、[A2](M07-A_steps/A2.md)。

- **A1**：退回 10 項，全由 agy 完成，主要是：
  - PG seed 缺欄位。
  - 移除提前做的 M07-C 程式。
  - 補 world mutation 引用掃描。
  - delete／copy 補 `expected_revision`。
  - 移除編造的預設值。
  - 建怪合併為單一實作。
  - 內建 SRD 建怪流程改回原樣。
  - typed traits。
  
  指揮者另外清掉未用 import，並把 P4-A PG heads 檢查改成 Room scope。
- **A2**：兩輪共 11 項，全由 agy 完成，主要是：
  - 列表分頁。
  - 不再吞錯。
  - 移除 `'-'` 佔位。
  - locale 名稱與能力名稱改走單一呈現 helper（後端一起改）。
  - SRD size／type／alignment 補雙語。
  - 修正兩個 E2E 腳本錯誤。
- **合併前**：指揮者修正怪物庫列表的搜尋競態（舊回應覆蓋搜尋結果），unit 926 passed、build 通過，全套 E2E 中 m07a 通過。
- **A3**：補兩個驗收測試。
  - 只改 AC 的測試改用同時有 Multiattack 與 Spellcasting 的怪物。
  - 新增：Member 控制 DM Seat 仍不可管理怪物庫。

## 已知限制與交接

- 測試指南 A.2 的「地圖既有配置載入才可用封存模板建立 Instance」要等 M07-C 的預配置存在才能驗；契約已列在 M07-C C.1／C.2。A 只驗了反面：一般建怪入口與新增引用都拒絕封存模板。
- `test_ai_read_grants_access_control` 的 taken-back 案例，是用「grant 不是 Seat 目前的綁定」模擬 Take Back 後的狀態，不是走真的 take-back route；revoked 案例則是直接用 revoked grant。
- 前端專案沒有 jsdom／Testing Library，頁面單元測試沿用既有的 static markup＋原始碼斷言做法（同 `RoomAdventuresPage.test.tsx`）。「409 衝突時保留表單」只有原始碼層級的證據，E2E 沒有覆蓋；送出中停用、`expected_revision`、封存、引用中刪除等流程則由 E2E 實際操作驗證。
- 內建 Monster 能力 `desc` 在 zh-TW 顯示英文原文，屬 AGENTS 守則 7 的既有例外，翻譯欠帳已在 `已知問題.md` 登記，本 Subphase 不新增條目。
