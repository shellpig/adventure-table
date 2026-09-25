# M06-B — Own-Write Echo Suppression in wait_for_event · Closeout

日期：2026-09-25　Branch：`feat/m06b-own-echo-suppression`（疊在 `feat/m06a-wait-timeout-cap` 上）　Worker：agy（B1、B2a、B2b）、指揮者（B3、B4）

## 驗收對應

測試檔：`apps/server/tests/test_m06b_own_echo_suppression.py`（蓋章、service 層、文字）、`test_m06b_mcp_echo_integration.py`（production facade 經 HTTP `/mcp`）、`test_m06b_postgres_migration.py`。

| 契約 | 證據 |
|---|---|
| B.1 自己的 echo 不喚醒 | `test_m06b_mcp_echo_integration.py::test_mcp_dm_echoes_do_not_wake_wait`（真實 `set_stage_text`／`post_narration`／`world_create_entry`／`world_set_current_context`／`request_check` 後 `events == []`、cursor＝5，Human dialogue 後只回該句）；`test_m06b_own_echo_suppression.py::test_list_after_suppress_own_skips_ai_dm_echoes_and_advances_cursor`、`::test_wait_suppress_own_keeps_waiting_past_own_echoes_until_timeout`、`::test_wait_suppress_own_wakes_on_player_dialogue_after_own_echoes` |
| B.2 其他人的事件照常喚醒 | `::test_mcp_other_actor_writes_wake_ai_dm`（AI Player、Human dialogue、Human 擲骰結果）；`::test_other_actor_events_are_returned` |
| B.3 非白名單事件照送 | `::test_mcp_combat_events_not_suppressed`（MCP 開 Quick Combat、先攻、推進回合）；`::test_non_whitelisted_own_events_are_returned`（`combat.*`、戰鬥 `roll.requested`、`roll.resolved`、`pending_action.*`、`controller.changed`、`session.*`） |
| B.4 `include_own=true` | `::test_mcp_include_own_returns_dm_echoes`；`::test_include_own_equivalent_to_unsuppressed` |
| B.5 補帳路徑與人類 UI 不變 | `::test_mcp_get_pending_events_and_human_events_include_dm_echoes`；`::test_human_and_pending_paths_unchanged` |
| B.6 身分判斷跨 controller | `::test_previous_controller_echoes_not_own_after_regrant`、`::test_human_dm_writes_never_own_for_ai`、`::test_legacy_null_stamp_events_are_returned`；蓋章 `::test_ai_append_stamps_grant_and_generation`、`::test_human_append_leaves_stamp_null`、`::test_system_append_without_binding_leaves_stamp_null`、`::test_idempotent_replay_returns_original_stamp` |
| B.7 白名單前提 | `test_m06b_mcp_echo_integration.py::test_whitelisted_tool_results_cover_event_payload`（17 個由 MCP 工具產生的白名單種類參數化） |
| B.8 AI 會讀到的說明 | `test_m06b_own_echo_suppression.py::test_wait_for_event_texts_explain_own_echo_suppression`（tool description 與 guide，en／zh-TW） |
| B.9 秘密與 DTO | `::test_mcp_player_wait_gets_no_extra_secrets`、`::test_player_visibility_unchanged_by_suppression`、`::test_table_event_json_has_no_stamp_fields`（`TableEvent`、`list_after`、REST `/events`） |
| B.10 Migration 與回歸 | `test_m06b_postgres_migration.py::test_m06b_real_postgres_upgrade_downgrade_upgrade`（真 PostgreSQL：upgrade heads、downgrade 一步、再 upgrade，舊事件可讀）；`test_migration_heads.py`、`test_m03_import_boundary.py`、`test_m03d_schema_parity.py` |

## 關門 gate

- 全套 backend pytest（cwd `apps/server`，無 PG）：exit 0，2602 passed。
- 全套 backend pytest（`P4_POSTGRES_URL=…/adventure_table_p4f`）：2642 passed／39 skipped／1 failed——唯一失敗 `test_p6e_postgres_migration.py::test_p6e_imports_status_and_sources_kind_checks` 是 P6-E 既有測試 bug（SQL 字串少右括號），本 branch 未動該檔；已開 chip 另修。
- `docker compose config`：通過。
- E2E（Docker，`ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1`）：`p3e-mcp-browser-integration.spec.ts` 1 passed；server-e2e 已重建，e2e DB 升至 `0034_m06b_event_actor_stamp`。
- 全套 E2E：M06-C 關門後在最上層 branch 一次執行，涵蓋 A～C。

## 指揮者審核修正摘要

- B1：migration revision id 33 字元超出 PostgreSQL `alembic_version.version_num` VARCHAR(32)，改為 `0034_m06b_event_actor_stamp`；`StoredTableEvent` 新欄位去掉預設值。
- B2a：刪除 `inspect.signature` 偵測 stub 的分支；重寫 `wait_after` 抑制迴圈的 deadline 計算；M06-A 測試 stub 補 `suppress_own`、timeout 斷言改 approx。
- B2b：修正 `app.state` 快取清除漏項造成的 xdist 跨測試污染；fixture 還原而非清空 `dependency_overrides`。

## 觀察到但不屬 M06-B 的事項

1. `test_p6e_postgres_migration.py::test_p6e_imports_status_and_sources_kind_checks` 既有 SQL 語法錯誤，只在有 `P4_POSTGRES_URL` 時會跑到（見上）。
2. 預設 `wait_for_event` 現在走抑制迴圈，逾時時 notifier 收到的是 deadline 剩餘秒數（略小於要求值），行為上仍等滿上限。
