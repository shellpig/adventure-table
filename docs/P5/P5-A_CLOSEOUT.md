# P5-A — Battle Map & Spatial Foundation · Closeout

日期：2026-09-27　Branch：`feat/p5a-battle-map-spatial-foundation`　Worker：Muse（A1、A2，在自己的 Linux 環境跑綠後推送）、指揮者（驗收、修正、關門）

## 範圍

Backend only。Battle Map Definition（Blank／Image、Wall／Door／Terrain／Drawing、Owner／DM authority、revision）、`room_assets` 新增 `battle_map_image`、`combats.mode` 放寬 `tactical`、spatial primitives（footprint／bounds／blocked／跨牆）、Combat board runtime（凍結 baseline、runtime door、positions）、Tactical start（`POST .../combat/tactical/start`）、placement 與 initiative gate、board read／image route、Player secrecy projection（含修正 P4 既有的 hidden monster entry 洩漏）。Human Tactical UI、Map editor UI、MCP Tactical tools 屬 P5-F；movement 屬 P5-B。Migration：`0035_p5a_combat_mode_tactical`、`0036_p5a_battle_maps`、`0037_p5a_combat_board_positions`。

## 驗收對應

| 契約（測試指南） | 證據（`apps/server/tests/`） |
|---|---|
| A.1 Map Definition | `test_p5a_battle_maps.py`（blank／image 建立、grid 欄位、objects roundtrip 含 id 保留、Door 四狀態、MEMBER 與跨 Room 404 零副作用、revision conflict、縮小出界 409、無效幾何原子拒絕）；`test_p5a_room_asset_battle_map.py`（`battle_map_image` 上傳、非 png／jpeg／webp 與 >20 MiB 拒絕且無 orphan、被引用 asset 刪除 409、Room hard delete 清 metadata＋檔案）；`test_p5a_battle_map_projection.py`、`::test_player_projection_omits_hidden_geometry` |
| A.2 Definition vs runtime | `test_p5a_board_runtime.py::test_door_update_bumps_runtime_revision_not_map`、`::test_definition_edit_after_start_does_not_drift_board`、`::test_end_combat_retains_board_and_positions`；`test_p5a_tactical_start.py::test_tactical_start_freezes_map_baseline` |
| A.3 Footprint／placement | `test_p5a_spatial_footprint.py`（size table、邊界、blocked、overlap、跨牆）；`test_p5a_board_runtime.py::test_placement_validation_rejects_with_generic_code`、`::test_hidden_blocker_uses_same_generic_code`、`::test_placement_retry_with_same_key_does_not_duplicate` |
| A.4 Tactical start gate | `test_p5a_board_runtime.py::test_initiative_gate_requires_all_placed`、`::test_running_gate_and_mid_combat_entrant`、`::test_request_initiative_gate_rejects_unplaced_tactical_entry`、`::test_reorder_running_gate_rejects_unplaced_mid_combat_entrant`、`::test_player_places_own_character_dm_places_anything`；`test_p5a_tactical_start.py::test_quick_start_still_works_alongside` |
| A.5 Secrecy | `test_p5a_board_secrecy.py`（Player combat view／detail 省略 hidden monster、board 省略其 position、placement event `dm_only`、hidden door 事件 revealed 前 `dm_only`、current turn 為 hidden 時對 Player 為 null、MCP `combat_get_active` 同一 projection） |
| A.6 Standalone boundary | `test_m03_import_boundary.py`（regex 加 `battle_maps?|combat_boards?|spatial|tactical`）、`test_m03d_schema_parity.py`（八張新表） |
| A.7 Mode migration | `test_p5a_postgres_migration.py::test_p5a_postgres_migration`（`0034`→head 既有 quick row 與 P6 資料不變、tactical row 可寫、有 tactical row 時 downgrade 拒絕）、`::test_p5a_postgres_board_tables_migration` |

## 關門 gate

- 全套 backend pytest（`P4_POSTGRES_URL=…/adventure_table_p4`）：exit 0、0 failed（修正前於 `0437ff6e` 執行）；修正後 `test_p5a_*.py`＋code quality／M03 boundary／schema parity：100 passed。
- `docker compose config`：通過。未動 `apps/web`，不需 `npm test`／`npm run build`。
- **全套 Docker E2E**（`ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1 npm run test:e2e:docker`，`0437ff6e`）：`parallel` 102 passed／3 skipped／2 failed（`p1f-character-creation`、`p1g-level-up`）；script 在第一趟失敗後停止，另補跑 `baseline-room` 30 passed／1 skipped、`serial-restart` 2 passed；`p1g` 單跑 passed。`p1f` 為 `main` 上既有穩定失敗（見 P6-D closeout），與 P5-A 無關。M03-C xge-less subset 趟未執行（P5-A 未動 content pack）。

## 指揮者審核修正

- A1：Player projection 把 hidden door 轉成的 wall 附加在 public walls 之後，順序可推斷門的位置——交 Muse 在 A2 改為依座標排序並補 `test_player_walls_sorted_and_source_independent`。
- A2：board projection 對**所有人**（含 DM）把未揭露的 hidden door 轉成牆，DM 拿不到 door id、無法揭露或改狀態，違反設計 §5.4——改為只對 Player 轉換，並把 `test_tactical_start_freezes_map_baseline` 的 DM 斷言改成「DM 看到帶 id 的門」。
- 補測試：`test_placement_retry_with_same_key_does_not_duplicate`（A.3 retry）、`test_definition_edit_after_start_does_not_drift_board`（A.2 開戰後編輯 Definition）。
- 設計方針 §11(a) 原寫「一律經 `TableEventService.append_event`」有誤（P4 combat persistence 直接用 `event_repository.append(..., expected_actor_binding=...)`），已於 `main@d98e9dd7` 更正並 merge 進本 branch。

## 已知限制

- 事件 payload 的 hidden monster 過濾以固定 key 名單（`event_projection._ID_KEYS`／`_ID_LIST_KEYS`）比對；未來事件若用名單外的 key 放 entry id，不會被擋也不會報錯。新增 combat 事件時須同步檢查名單。
- Player 過濾依「目前」hidden 集合判斷：monster 揭露後，其過去的事件對 Player 恢復完整內容。
- DM board view 的 wall 不帶 visibility 標記，DM UI 無法區分 hidden wall；P5-F 做 Tactical UI 時補。
- Quick Enemy 現在會在 `rules_snapshot` 寫入預設 `size: "medium"`（placement 需要 size）。
- Muse 的最終報告因其網站連線問題未能讀取；交付以 commit、本機測試與上述審核為準。
