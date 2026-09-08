# P2-F Closeout Checklist

P2-F — Full P2 Integration & Closeout scope。編號對應 [實作規格](實作規格.md)「P2-F 關門條件」的 21 條。

P2-F 不新增產品行為。這個 Subphase 的工作是把 P2-A～P2-E 累積下來的整合、隔離、遷移、併發與 browser 層缺口補完，並確認整條 Room → Campaign → Roster → Seat → Lobby → Session 的路徑在真後端與真瀏覽器上成立。

## Migration

- [x] 1. Fresh Web PostgreSQL 升到 `heads` 成功；standalone fresh / legacy SQLite 只升 `character@head`。`test_p2a_postgres_migration.py::test_fresh_web_postgres_upgrade_heads_and_readiness` 在 CI `postgres-migrations` job 對真 PostgreSQL 執行；SQLite 側由 `test_m03d_migration_sqlite.py` 與 `test_m03d_sqlite_fk.py` 覆蓋。
- [x] 2. `0008_m03c_import_records` legacy Web DB 升到 P2 heads 成功且既有 Character / Draft 不 silent loss。`test_p2a_postgres_migration.py::test_legacy_m03_postgres_upgrade_heads_preserves_character_payloads` 在升級前後比對 payload，不只比對 row count。
- [x] 3. 既有 M03 migration tests 已 multi-head-aware，standalone schema parity 使用 Character allowlist 且不受 test import 順序影響。`test_m03d_schema_parity.py::test_sqlite_character_migration_schema_matches_character_metadata` 以 `FORBIDDEN_MULTIPLAYER_TABLES` 明列禁止表；`test_p2a_migration_tracks.py` 鎖住 `WEB_REVISIONS` / character track 的分離。**P2-F 新增**：`test_m03c_migration.py` 進 CI `postgres-migrations` job（同一次改動補上 `M03C_POSTGRES_URL`），先前它在本機恆 skip，等於沒有真 PostgreSQL 證據。
- [x] 4. `P2 Non-E2E` workflow 在 exact final SHA 提供 PostgreSQL migration / persistence / concurrency evidence。run id 見下方 Verification evidence；`test_p2a_workflow_contract.py::test_p2f_final_non_e2e_workflow_closes_postgres_and_standalone_gates` 是這條的靜態 gate——workflow 若把 `test_p2f_postgres_seat_selection.py`、`test_m03c_migration.py` 或 `windows-standalone` job 拿掉，這條測試會紅。

## Web journeys

- [x] 5. Homepage → Create Room → Enter → Character Workshop → Create Draft → reload → Confirm → Sheet / Version History 全程 Room-scoped。整套 E2E 已經跑在 `roomTest` fixture 上（`/api/characters` 一律改寫成 `/api/rooms/{id}/characters`），Journey 1 因此由 `character-builder.spec.ts`、`p1f-character-creation.spec.ts`、`p1g-level-up.spec.ts` 與 `p2a-room-bootstrap.spec.ts::P2-B Workshop helper navigates through the authenticated Room namespace` 共同覆蓋。
- [x] 6. target Room Import 走 P2-A exporter 改版前封存的真實 legacy `unstable` fixture → Preview → Import → Export v1。`m03c-character-import.spec.ts`（含 xge-less 第二輪）配合 `test_p2a_legacy_fixture.py` 與 `test_p2a_character_json_v1.py`。
- [x] 7. Standalone Create / Import / Sheet / Level Up / Export 仍可用，且沒有 Room UI / router / dependency / multiplayer tables。`test_m03g_roundtrip.py`、`test_m03g_standalone_runtime.py`、`test_m03g_import_edges.py`、`test_p2a_standalone_room_boundary.py`；capability 面由 `test_m03e_capabilities.py::test_standalone_capabilities_identify_channel_and_database` 與 `test_p2c_capabilities.py::test_standalone_channel_keeps_multiplayer_capabilities_disabled` 鎖住六個 multiplayer flag 全 false。
- [x] 8. Multi-Room isolation：Room A caller 無法用 UUID 操作 Room B 的 Character / Draft / Campaign / Seat / Session。`test_p2b_room_character_api.py::test_room_a_cannot_use_room_b_character_or_draft_ids`、`test_p2c_campaign_policy.py`、`test_p2d_seat_policy.py`、`test_p2e_late_join.py::test_late_join_revalidates_same_room_even_if_persistence_is_tampered`。瀏覽器層的限制見「已知限制」。
- [x] 9. Same-Room multi-Campaign：同一 Character 可在兩個 Roster，且 Current State 是同一份。**P2-F 新增** `p2f-cross-campaign.spec.ts::P2-F Journey 7 shares rich Character State across two Campaign roster contexts`——在 Campaign Alpha 的 roster 情境改動角色 State，切到 Campaign Beta 讀到同一份，不是兩份副本。後端側為 `test_p2c_campaign_integration.py`。

## Permission / concurrency

- [x] 10. Room access code / password / throttle 與 heartbeat 契約有自動證據。`test_p2a_room_access.py` 十二條，含 throttle 視窗、`X-Forwarded-For` 不能繞過、revoked session 不能 heartbeat。
- [x] 11. Owner-controlled DM assignment 成立；DM Key holder 不能 self-assign DM Seat。`test_p2d_seat_policy.py` 與 `p2d-lobby-seats.spec.ts::P2-D Owner drives Campaign, Roster and Lobby seats against the real backend`。
- [x] 12. 被 Session history reference 的 Seat 只能 archive，Session Seat FK history 不破壞。`test_p2e_session_persistence.py::test_session_referenced_seat_cannot_hard_delete_but_can_archive`；restart 之後歷史 Seat 仍在，見條目 21。
- [x] 13. Active Session collision：同一 Character 不得同時在兩場 active Session。DB primary key 保證，`test_p2e_postgres_sessions.py` 三條在真 PostgreSQL 驗併發，**P2-F 新增** `p2f-cross-campaign.spec.ts::P2-F Journey 8` 在瀏覽器上驗使用者看到的是 localized 409 訊息而不是 raw code。
- [x] 14. Lobby / Start / Late Join / End / Abandon lifecycle 符合產品契約。後端為 `test_p2e_session_lifecycle.py` / `test_p2e_late_join.py`；**P2-F 新增** `p2f-session-lifecycle.spec.ts` 兩條 journey，涵蓋 Start → 參與者顯示 → End → 回 Lobby，以及 Start 後才選角的 Late Join 與 reload 後仍成立。
- [x] 15. Session End 不改 Character gameplay state。`test_p2e_end_state_preservation.py::test_end_session_preserves_exact_rich_character_state_and_history`。
- [x] 16. Room Hard Delete 強確認後能清掉整個 workspace，沒有 P2 scope orphan。`test_p2e_room_hard_delete.py::test_room_hard_delete_removes_session_restrict_graph_before_owned_history`、`test_p2c_room_hard_delete.py`。UI 提示的不足見「已知限制」。
- [x] 17. `zh-TW` / `en` P2 user-facing copy 完整，不出 raw key / raw server code。`hardcodedUiCopy.test.ts` 掃描清單已含 `RoomCampaignPage.tsx` / `RoomLobbyPage.tsx` / `RoomSessionPage.tsx`；`sessionMessages.test.ts`、`seatMessages.test.ts`、`p2eRequestMessages.test.ts`、`campaignCopy` / `lobbyCopy` / `sessionCopy` 的 locale parity 測試；Journey 8 另在瀏覽器上斷言 localized 衝突訊息。browser crawl 的涵蓋缺口見「已知限制」。

## Standalone / baseline

- [x] 18. M03 standalone import-boundary tests green。`test_m03_import_boundary.py`、`test_p2a_room_import_boundary.py`。P2-F 未新增多人層 module 或 table，兩份清單無需擴充。
- [x] 19. Windows standalone build workflow 仍能成功產出 artifact；P2 不把 multiplayer package 拉進 standalone runtime graph。**P2-F 新增** `P2 Non-E2E` 的 `windows-standalone` job：`scripts\build-standalone.cmd` 產出 frozen distribution，再跑 `scripts\smoke_standalone.py`。這是 P2 第一次把 standalone 發版與 smoke 綁進 P2 自己的 workflow，不再借用其他 workflow 的結果。
- [x] 20. P0 / P1 / M01 cumulative Character baseline 沒有因 Room scope wrapper regression。全套 backend pytest 與全套 Playwright suite 皆綠，見 Verification evidence。
- [x] 21. P2 real-backend E2E、restart persistence、authorization matrix 與 human smoke 皆有 closeout evidence。real-backend E2E 見下方；**P2-F 新增** `test_p2f_restart_integration.py::test_p2f_restart_preserves_full_room_campaign_session_workspace_graph` 以 [測試指南](測試指南.md) §18 指定的完整 dataset（2 Rooms、3 Campaigns、同一 Character 在 2 個 Roster、active + ended Session、open Draft、archived Character、被 Session 歷史 reference 的 archived Seat）重建 engine / service / repository 後重讀重寫；authorization matrix 為 `test_p2e_live_character_scope.py` 加上條目 8 / 11 的各層 policy 測試；human smoke 見下方。

## 關門過程中修正的問題

**Web 從未真正能用 Session 頁面。** [meta.py](../../apps/server/app/api/meta.py) 的 `build_capabilities()` 只設了 `room` / `campaign` / `seat`，漏掉 `session`，所以 web channel 一直回 `session: false`。P2-E 的 review 修正把 `/rooms/{id}/campaigns/{cid}/sessions/{sid}` 明確 gate 成 `session` capability（見 [P2-E closeout](P2-E_CLOSEOUT.md)「關門過程中修正的問題」第 3 點），兩者相加的結果是：**任何瀏覽器一進 Session 頁只會看到 standalone capability boundary 的「This feature is not available here」**，Session API 正常但 UI 完全不可達。

這個缺口在 P2-E 沒有被抓到，因為當時沒有任何 Session 的 browser 證據，而前端單元測試是餵 mock capability snapshot。P2-F 新增的 Journey 5 / 6 / 8 一跑就三條同時紅在同一個 assertion 上，正是這條缺陷。

修法是 `session=channel == "web"` 一行，並把兩條原本斷言 `session is False` 的測試翻正：`test_m03e_capabilities.py::test_web_capabilities_enable_p2_multiplayer_surface`（HTTP 層）與 `test_p2c_capabilities.py::test_web_channel_advertises_p2_multiplayer_capabilities`（direct contract）。standalone 側維持六個 multiplayer flag 全 false，未放寬。

## Verification evidence

分支 `p2-f-full-integration-closeout`，final code SHA `22220df`。

```text
Branch / final code SHA
  p2-f-full-integration-closeout @ 22220df
  （p2-f-full-integration-closeout-work 為同一棵樹的鏡像分支，內容一致）

Alembic heads
  0009_p2a_character_head (character) (head)
  0014_p2e_sessions (web) (head)
  P2-F 未新增 migration。standalone SQLite 仍只升 character@head。

Backend pytest
  1111 collected / 182 files
  1100 passed, 11 skipped, 0 failed, exit 0
  cwd apps/server，直譯器 ..\..\.venv\Scripts\python.exe
  11 個 skip 全部是缺 PostgreSQL URL 的 gated 測試
  （test_p2a_postgres_migration.py ×2、test_p2b_postgres_workspace.py ×3、
    test_p2e_postgres_sessions.py ×3、test_p2f_postgres_seat_selection.py ×1、
    test_m03b_migration.py ×1、test_m03c_migration.py ×1），
  全數改由下方 CI 的 postgres-migrations job 覆蓋。

CI P2 Non-E2E（正式 workflow evidence）
  run id 34181507756 @ 22220df（exact final code SHA）
  https://github.com/shellpig/adventure-table/actions/runs/34181507756
  conclusion success；backend / frontend / postgres-migrations /
  windows-standalone 四個 job 全綠。
  postgres-migrations 在真 PostgreSQL 上跑
  test_p2a_postgres_migration.py + test_p2b_postgres_workspace.py
  + test_p2e_postgres_sessions.py + test_p2f_postgres_seat_selection.py
  + test_m03c_migration.py。
  windows-standalone 跑 scripts\build-standalone.cmd 與
  scripts\smoke_standalone.py（frozen distribution smoke）。
  前一個 run 34175760850 @ 560fdd9 亦為 success，但當時 Session capability
  缺陷尚未修，該 SHA 的完整 E2E 為紅，不可作為關門證據。

Frontend unit
  219 passed / 47 files，exit 0 @ 22220df

TypeScript / build
  npm run build（tsc --noEmit && vite build）exit 0 @ 22220df

Full Web Playwright
  npm run test:e2e:docker exit 0 @ 22220df
  第一輪 111 tests：108 passed / 0 failed / 3 skipped（7.4m）
  第二輪 xge-less M03-C 子集：7 passed（6.2s）
  3 個 skip：m01j-subclass-expansion.spec.ts 的 direct-vs-sequential 等價
  （KI-M01J-001 intentional fixme，不計入 P2-F 功能證據），以及
  m03c-character-import.spec.ts 兩條需要缺 pack 後端的案例——後者正是
  第二輪跑的那批，已在該輪通過。
  執行前先 docker compose up -d --build server，確保後端是 22220df；
  test:e2e:docker 本身只 rebuild web service。

docker compose config
  exit 0

Human smoke
  使用者於 2026-09-08 在本機執行並確認通過，未回報 blocker。
  本文件不代為記錄逐步操作紀錄。
```

### 驗收條目 → 測試對應

| 條目 | 證據 |
|---|---|
| 1, 2 | `test_p2a_postgres_migration.py` 兩條（CI `postgres-migrations`）；`test_m03d_migration_sqlite.py`、`test_m03d_sqlite_fk.py` |
| 3 | `test_m03d_schema_parity.py::test_sqlite_character_migration_schema_matches_character_metadata`、`test_p2a_migration_tracks.py`、`test_m03c_migration.py`（P2-F 起進 CI） |
| 4 | `test_p2a_workflow_contract.py::test_p2f_final_non_e2e_workflow_closes_postgres_and_standalone_gates`；run 34181507756 |
| 5 | `character-builder.spec.ts`、`p1f-character-creation.spec.ts`、`p1g-level-up.spec.ts`、`p2a-room-bootstrap.spec.ts`（全部經 `roomTest` fixture 走 Room namespace） |
| 6 | `m03c-character-import.spec.ts`（兩輪）、`test_p2a_legacy_fixture.py`、`test_p2a_character_json_v1.py` |
| 7, 18 | `test_m03g_roundtrip.py`、`test_m03g_standalone_runtime.py`、`test_m03g_import_edges.py`、`test_m03_import_boundary.py`、`test_p2a_room_import_boundary.py`、`test_p2a_standalone_room_boundary.py` |
| 8 | `test_p2b_room_character_api.py::test_room_a_cannot_use_room_b_character_or_draft_ids`、`test_p2c_campaign_policy.py`、`test_p2d_seat_policy.py`、`test_p2e_late_join.py::test_late_join_revalidates_same_room_even_if_persistence_is_tampered` |
| 9 | `p2f-cross-campaign.spec.ts::P2-F Journey 7 shares rich Character State across two Campaign roster contexts`、`test_p2c_campaign_integration.py` |
| 10 | `test_p2a_room_access.py` 十二條 |
| 11 | `test_p2d_seat_policy.py`、`p2d-lobby-seats.spec.ts` 兩條 |
| 12 | `test_p2e_session_persistence.py::test_session_referenced_seat_cannot_hard_delete_but_can_archive`、`test_p2f_restart_integration.py`（restart 後歷史 Seat 與 participant 仍在） |
| 13 | `test_p2e_postgres_sessions.py` 三條（CI）、`p2f-cross-campaign.spec.ts::P2-F Journey 8 shows a localized browser conflict for cross-Campaign active Character collision` |
| 14 | `p2f-session-lifecycle.spec.ts::P2-F Journey 5 starts and ends a real Session from the browser`、`::P2-F Journey 6 selects a Character after Start and Late Joins through the browser`、`test_p2e_session_lifecycle.py`、`test_p2e_late_join.py` |
| 15 | `test_p2e_end_state_preservation.py::test_end_session_preserves_exact_rich_character_state_and_history` |
| 16 | `test_p2e_room_hard_delete.py::test_room_hard_delete_removes_session_restrict_graph_before_owned_history`、`test_p2c_room_hard_delete.py` |
| 17 | `hardcodedUiCopy.test.ts`、`sessionMessages.test.ts`、`seatMessages.test.ts`、`p2eRequestMessages.test.ts`、`RoomSessionPage.test.ts`、`RoomLobbyPage.test.ts`、`RoomCampaignPage.test.ts`、`m02h-bilingual-site-smoke.spec.ts`、`m02h-localization-state-integrity.spec.ts` |
| 19 | `P2 Non-E2E` 的 `windows-standalone` job @ 34181507756；`test_p2a_workflow_contract.py::test_p2f_final_non_e2e_workflow_closes_postgres_and_standalone_gates` |
| 20 | 全套 backend pytest 1100 passed；全套 Playwright 108 passed |
| 21 | `test_p2f_restart_integration.py::test_p2f_restart_preserves_full_room_campaign_session_workspace_graph`、`test_p2f_postgres_seat_selection.py::test_concurrent_seat_selection_has_one_database_winner`（CI）、`test_p2e_live_character_scope.py` 三條、human smoke |
| Session capability 修正 | `test_m03e_capabilities.py::test_web_capabilities_enable_p2_multiplayer_surface`、`test_p2c_capabilities.py::test_web_channel_advertises_p2_multiplayer_capabilities`、`routes.test.ts` |

## 承接 P2-E 的未結清項目

- [x] **Seat 選角併發已在真 PostgreSQL 驗過。** `test_p2f_postgres_seat_selection.py::test_concurrent_seat_selection_has_one_database_winner` 用 `ThreadPoolExecutor` + `Barrier` 讓兩個 transaction 同時對同一個 Seat 選同一隻角色，斷言只有一個 commit 成功、另一側收斂成 `SeatPersistenceConflictError`。測試已進 CI `postgres-migrations` job，`with_for_update()` 不再只有 SQLite（no-op）證據。
- [x] **Journey 5 後半、Journey 6、Journey 7、Journey 8 已補上 browser 證據。** 四條分別落在 `p2f-session-lifecycle.spec.ts`（2）與 `p2f-cross-campaign.spec.ts`（2）。
- [ ] **`SessionResumeService` / Lobby 的 N+1 查詢未處理。** 見「已知限制」。
- [ ] **Campaign status 仍無 transition 規則。** 見「已知限制」。
- [ ] **Room Hard Delete 與 draft Campaign hard delete 的確認 UI 未顯示連帶刪除數量。** 見「已知限制」。

## Boundary

- P2-F 不新增 API、資料模型、migration 或多人層 module。產品面 diff 只有 `meta.py` 的一行 capability 修正。
- P2-F 不提前做 P3：沒有 chat / action / check / roll / PendingAction / AI join token / MCP / event queue。
- P2-F 不提前做 P7：沒有 snapshot payload、沒有 restore。
- `app.standalone` 仍不 import `app.main` 或任何 `app.*.rooms`；standalone capability 六個 multiplayer flag 全 false。
- [實作規格](實作規格.md) §8「P2 明確不做」全數維持，未因關門而破例。

## 已知限制

- **Journey 2（多 Room 隔離）仍只有後端證據。** [測試指南](測試指南.md) §13 Journey 2 描述的是瀏覽器層：Room A 的 UI 不列出 Room B 的角色、手動把 Room B 的 UUID 貼進 Room A route 應被拒。目前 `test_p2b_room_character_api.py::test_room_a_cannot_use_room_b_character_or_draft_ids` 在 HTTP 層完整覆蓋，`p2a-room-bootstrap.spec.ts` 只斷言兩個 Room 的 id / code / token 不同。隔離本身由 server 保證且有測試，但「使用者實際貼 URL 會看到什麼」沒有 browser 斷言。建議在 P3 第一個碰 Room route 的 Subphase 補一條。
- **雙語 browser crawl 未涵蓋 P2 新畫面。** `m02h-bilingual-site-smoke.spec.ts` 的路由清單只有 `/rooms/{id}/characters`、`/characters/{id}`、`/versions` 三條，沒有 `/campaigns`、`/lobby`、`/sessions/{id}`。條目 17 目前靠 `hardcodedUiCopy.test.ts` 的掃描與各 `*Copy.ts` 的 locale parity 單元測試把關，加上 Journey 8 對單一條 localized 錯誤訊息的瀏覽器斷言。缺的是整頁 overflow / raw key 的視覺層 crawl。
- **`test_p2f_restart_integration.py` 跑在 SQLite + `metadata.create_all`。** dataset 完整符合 §18 的七項要求，但重啟證據不是建立在 Alembic 遷移後的 PostgreSQL 上。migration 面另有 `test_p2a_postgres_migration.py` 與 `test_p2e_postgres_sessions.py` 在真 PostgreSQL 覆蓋，兩者合起來沒有留下未驗的組合，但單一測試本身不等於「Web 正式引擎上的重啟」。
- **`test:e2e:docker` 只 rebuild `web` service。** 後端改動若不先 `docker compose up -d --build server`，整套 E2E 會靜默測到舊 backend。這次驗證期間就因此先誤判了兩支順序相依的失敗。建議把 server 重建併進該 script，或在 [README.md](../../README.md) 明記。目前是操作者責任。
- **`SessionResumeService` 與 Lobby 的 N+1 查詢未處理。** P2-E 已記錄：Resume 對每隻 Active Character 各 load 一次完整 Character，Lobby 對每個 Seat 各查一次 access session，兩處都在 heartbeat 週期重抓。桌上跑團量級可忽略；P3 若讓這兩頁變高頻輪詢就必須先併查詢。
- **Campaign status 仍沒有 transition 規則。** Campaign 可從 `completed` 退回 `draft`，`delete_draft_without_session_history()` 因此必須同時檢查 status 與 Session history 才安全。P2 全程未建立 transition guard。
- **Room Hard Delete 是目前最容易造成不可逆資料遺失的入口。** 確認 modal 只要求輸入 Room 名稱，未顯示會連帶刪除幾個 Character / Draft / Campaign / Session，也未提示先匯出。行為符合契約，但 human smoke 期間曾實際造成角色永久遺失。draft Campaign hard delete 連帶移除 Roster 也同樣沒有數量提示。兩者都未在 P2 處理。
- **P2-A 的 Room 層取捨全數延續。** throttle 為 process-local（多 worker 會稀釋）、`POST /api/rooms` 無 throttle 無授權、Room access token 以明文存 `localStorage` 且無到期機制。
- **E2E global setup 仍會無條件清空 Character / Draft / Room / Campaign / Session。** 由 `ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1` 當閘門（CI 自動放行）。本機在有真實資料的 DB 上設此變數會直接刪光，跑之前必須自行備份。
- **KI-P1D-001 的 `m01e` / `m01m` 半邊仍未解**，KI-M01J-001 的直創／逐級升等等價 E2E 仍是 `fixme`。兩者都屬 `已知問題.md`（verifier 文件），P2-F 未改寫。
- **`character_in_active_session` 用 409 表示授權拒絕。** 語意上較接近 403，但同時承載「角色被佔用」的資源狀態。code 已穩定並有雙語訊息，改動會是 API breaking change。

## Handoff

P2-F 已完成，**P2 — Room / Campaign / Session / Seat 關門**。下一步是 **P3 — Exploration + Roll + AI**。

P3 可以直接假設下列基礎已存在，不要重造：

- **Room / Campaign / Roster / Seat / Session 全鏈路。** Session identity、participant snapshot、固定 DM Controller、immutable Active Character、Late Join 與 `active_character_session_leases` 的全域唯一保證。
- **`live_character_write_scope()` / `live_draft_write_scope()` / `unleased_character_write_scope()`。** active Session 期間 Character 寫入授權的唯一住所。P3 的 GameAction permission 應該擴充這三個 context manager，不要在別處補第二套檢查。
- **`SessionResumeService`。** Resume 是既有 truth 的組合，不是第二份 snapshot。P3 若要在 Session 頁加 Exploration / Chat 狀態，先決定它住哪張表，再決定要不要進 Resume DTO。
- **capability endpoint。** 新的多人能力（combat / timeline / ai_actor）開通時，`build_capabilities()` 與 `protectedCapabilityForPath()` 必須同一個改動一起改，並補 web / standalone 雙向斷言。**P2-F 的唯一產品缺陷就是只改了 route gate 沒改 capability 宣告，而當時沒有 browser 證據會發現。**
- **`sessionMessages.ts` / `seatMessages.ts` / `REQUEST_CODE_MESSAGES` 三張表**與 `hardcodedUiCopy.test.ts` 掃描清單。新 user-visible error code 進對應那一張，新畫面同時加進掃描清單。
- **`P2 Non-E2E` workflow 的四個 job。** 需要真 PostgreSQL 的證據進 `postgres-migrations`；standalone 發版與 frozen smoke 進 `windows-standalone`。P3 建立自己的 workflow 時沿用同一分工，不要把 PostgreSQL 證據塞回一般 backend job。
- **standalone boundary 常駐約束。** P3 新增任何多人層 module 或 table，都必須同步確認 `test_m03_import_boundary.py` 的 `FORBIDDEN_MODULE_RE` / `EXACT_PROTECTED_MODULES` 與 `test_m03d_schema_parity.py` 的 `FORBIDDEN_MULTIPLAYER_TABLES` 涵蓋新命名，否則 gate 會靜默放行。
