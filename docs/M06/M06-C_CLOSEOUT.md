# M06-C — Compact Roll Result Projection for MCP wait · Closeout（含 M06 Phase 關門）

日期：2026-09-25　Branch：`feat/m06c-compact-roll-projection`（疊在 `feat/m06b-own-echo-suppression`、`feat/m06a-wait-timeout-cap` 上）　Worker：agy（C1）、指揮者（C2）

## 契約變更

- 2026-09-25 使用者拍板 C.1：精簡投影只移除骰子細節鍵（`raw_dice`、`kept_dice`、`base_modifier`、`flat_adjustment`、`source`）並加 `natural`，其餘鍵（含 Combat 的 `combat_id`、`action_id`、`attack_resolution` 等）原樣保留；`roll_request_id` 沒有對應正式 roll request 時 DM 的 `dc`／`outcome` 為 null。三份文件同步（commit `99e4d916`）。

## 驗收對應

測試檔：`apps/server/tests/test_m06c_compact_roll_projection.py`。

| 契約 | 證據 |
|---|---|
| C.1 精簡欄位 | `::test_compact_drops_dice_detail_and_adds_natural`（非戰鬥鍵集合恰為五鍵＋DM 兩鍵）、`::test_compact_keeps_combat_keys`（attack／initiative 型 payload 非骰子鍵全部保留）；`::test_mcp_wait_compacts_roll_resolved_for_dm_and_player`（真實 MCP） |
| C.2 DM 投影 | `::test_dm_outcome_matrix`（成功、失敗、`auto_fail`、無 DC）；`::test_mcp_wait_compacts_roll_resolved_for_dm_and_player`（`dc` 等於 request DC） |
| C.3 Player 投影 | `::test_mcp_wait_compacts_roll_resolved_for_dm_and_player`（AI Player 無 `dc`／`outcome` 鍵） |
| C.4 天然骰判斷 | `::test_natural_matches_kept_die`（`1d20`、`2d20kh1`、`2d20kl1`、天然 20／1；`1d6`、`1d200`、`2d20`、多顆保留骰、敵方投影已隱藏骰值 → None） |
| C.5 其他路徑不變 | `::test_mcp_pending_and_human_paths_keep_full_roll_payload`（`get_pending_events` 與 Human `/events` 完整）、`::test_mcp_combat_roll_projection_keeps_enemy_secrecy`（Monster 先攻擲骰經 MCP；Player 視角先敵方投影、精簡後不多出鍵）、`::test_mcp_wait_queries_roll_requests_once_per_page`（一頁兩筆只查一次） |
| C.6 回歸 | `test_p3e_*.py`、`test_p4e_*.py`、`test_p6*_mcp_*.py` 全綠；既有 `wait_for_event` payload 斷言無需修改 |

## 關門 gate（M06-C＝M06 Phase 關門）

- 全套 backend pytest（cwd `apps/server`，無 PG）：exit 0，2627 passed。
- 全套 backend pytest（`P4_POSTGRES_URL=…/adventure_table_p4f`）：2666 passed／39 skipped／1 failed——唯一失敗是 P6-E 既有測試 bug `test_p6e_postgres_migration.py::test_p6e_imports_status_and_sources_kind_checks`（SQL 字串少右括號，M06 未動該檔；見 M06-B closeout）。
- `docker compose config`：通過。
- **全套 Docker E2E**（`ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1 npm run test:e2e:docker -- --reporter=line`，帶參數故單趟 1 worker 跑完全部 project）：**140 tests：136 passed／4 skipped／0 failed**（12.2 分鐘），含 `p3e-mcp-browser-integration.spec.ts`；server-e2e／web-e2e 重建。M06 未動 `apps/web`，不需 `npm test`／`npm run build`。
- 本次 E2E 在最上層 branch 執行，涵蓋 M06-A～C（P6-F／P6-G 前例）。

## 指揮者審核修正摘要

- C1：`wait_for_event` 對必定存在的 `roll_request_id` 做 `try/except: pass` 吞錯並重複解析——抽成 `_compact_roll_results`，無 `roll.resolved` 時原 page 直接回傳；`compact_roll_resolved` 的 `total` 缺值補 `0`（假資料）改為直接讀取；還原 agy 替 p3e stub 加的 `model_copy`，只補 `events` 屬性。

## M06 Phase 關門證據（`測試指南.md` §4）

| 項目 | 證據 |
|---|---|
| 三個 Subphase focused test 對照 | [M06-A closeout](M06-A_CLOSEOUT.md)、[M06-B closeout](M06-B_CLOSEOUT.md)、本檔「驗收對應」 |
| backend 全套 | 2627 passed（無 PG）；2666 passed（真 PG，唯一失敗為既有 P6-E 測試 bug） |
| 真 PostgreSQL migration | `test_m06b_postgres_migration.py::test_m06b_real_postgres_upgrade_downgrade_upgrade`；e2e DB 實際升至 `0034_m06b_event_actor_stamp` |
| `p3e-mcp-browser-integration.spec.ts` | M06-B 關門單跑 1 passed；全套 E2E 內再次通過 |
| 合併前全套 Docker E2E | 136 passed／4 skipped／0 failed |
| Standalone 邊界 | `test_m03_import_boundary.py`、`test_m03d_schema_parity.py` 於各 Subphase 全套內通過 |
| 靜態審核 | 每步 diff 審核與 AST unused-import 掃描；修正見各 Subphase closeout |
| 人工驗收（非 gate） | 未執行；建議之後以網頁版 AI agent 主持一段含寫回的場景，觀察寫入後 `wait_for_event` 不再立刻帶回自己的 echo |

## 建議登記 `已知問題.md`（verifier 職權，未修改）

1. `test_p6e_postgres_migration.py::test_p6e_imports_status_and_sources_kind_checks` 的 SQL 語法錯誤，只在有 `P4_POSTGRES_URL` 時會跑到；已開獨立任務修正。
