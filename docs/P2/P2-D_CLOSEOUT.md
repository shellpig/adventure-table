# P2-D Closeout Checklist

P2-D — Seat, Controller & Lobby closeout scope。編號對應 [實作規格](實作規格.md) 的「Lobby / Seat 行為」十三條，另加「Seat 概念」與「Controller」兩節的形狀要求。

## Lobby / Seat 行為

- [x] 1. Active Campaign 可進 Lobby。`_require_current_active_campaign()` 同時驗 `campaign.status == 'active'` 與 `rooms.active_campaign_id == campaign_id`，兩者缺一即 409 `lobby_unavailable`。[開發設計方針](開發設計方針.md) §8.2 把兩者定義成不同的東西，Lobby 取的是「Room 目前選中的那一個」。
- [x] 2. 不強制 Ready。`campaign_seats` 沒有 ready 欄位，Lobby 也沒有 ready 動作。
- [x] 3. 不要求所有 Roster Character 都出席。Seat 與 Roster 是兩張表，Roster 有幾筆與建了幾個 Seat 無關。
- [x] 4. 一個 Human controller 可以同場控制多個 Player Seat。`controller_access_session_id` 沒有 unique constraint。
- [x] 5. 一個 Seat 同時只對應一隻本場 Active Character。`selected_character_id` 是單一欄位，且 `(campaign_id, selected_character_id)` 的 unique constraint 讓同一 Campaign 內不會有兩個 Seat 選到同一隻。
- [x] 6. Start 前 Player Seat 只能從目前 Campaign Roster 選 Character。`select_character_if_eligible()` 在同一個 transaction 內以 `campaign_roster_entries` join `campaigns` join `room_characters` join `characters` 驗證，不在 API 層事後篩。
- [x] 7. 只有 Roster status `active` / `inactive` 可選；`retired` / `dead` 不出現在 Active Character 選單。Server 端拒絕，前端只是同步隱藏選項。
- [x] 8. DM Seat 不需要綁 Player Character。`ck_campaign_seats_player_character_only` 在 DB 層擋住 `role != 'player'` 帶 `selected_character_id`，service 另外回 409 `seat_character_invalid`。
- [x] 9. Human presence 使用 P2-A 既有 heartbeat 資料顯示 Connected / Offline，不另建 P3 realtime event system。`SeatService._presence()` 讀 `room_access_sessions.last_seen_at`，門檻為 P2-A 契約的 90 秒；前端沿用既有的 `startRoomHeartbeat`，沒有第二套 presence substrate。
- [x] 10. Owner / DM authority 可配置目前 Campaign 的 Roster 與 Player / Spectator Seats；一般 member 只能操作分配給自己的 Human Player Seat，不得改他人 Seat。
- [x] 11. DM Seat 的 Human controller assignment / reassignment 只有 Owner authority 可做。`_require_dm_seat_management()` 只接受 `owner`，持 DM Key 者回 403 `room_owner_required`；被指定的對象本身仍必須具備 `dm` 或 `owner` authority。
- [x] 12. Room authority 與 Seat role / controller boundary 由 Server enforce，不能只靠 frontend 隱藏按鈕。每個 deny 都有 HTTP 層測試。
- [x] 13. 從未被任何 Session 引用的 Seat 可以刪；一旦被 Session history 引用，Seat 只能 archive。P2-D 尚無 Session 表，`delete_unreferenced()` 目前恆真並在原始碼標明由 P2-E 補上 history guard；archive 路徑已完整實作並測試。

## Seat 概念與 Controller 形狀

- [x] Owner 不是 gameplay role。`role` 只有 `dm` / `player` / `spectator`，由 `ck_campaign_seats_role` 鎖住；Owner 要上桌就佔一個 DM 或 Player Seat。
- [x] Controller 形狀為 `human` / `ai` / `none`，由 `ck_campaign_seats_controller_kind` 鎖住。
- [x] P2 只正式交付 Human / None。`SeatService.set_controller()` 對 `ai` 直接回 409，UI 只顯示「AI（尚未開放）」。沒有 AI Join Token、MCP、event queue、wait_for_event 或 Connection workflow。
- [x] `ck_campaign_seats_controller_binding` 讓 `human` 必須帶 access session、`ai` / `none` 必須為 null，形狀在 DB 層自我一致。

## Verification evidence

分支 `p2-d-seat-controller-lobby`，最終 code SHA `3439cbe`。

```text
Branch / final code SHA
  p2-d-seat-controller-lobby @ 3439cbe

Alembic heads
  0009_p2a_character_head (character) (head)
  0013_p2d_campaign_seats (web) (head)
  0013 接在 0012_p2c_campaigns_roster 之後，只落在 web track；
  standalone SQLite 仍只升 character@head，不會長出 campaign_seats。
  本機 compose PostgreSQL 實跑 alembic upgrade heads 通過，
  alembic_version 為 0009_p2a_character_head + 0013_p2d_campaign_seats。

Backend pytest
  1052 collected / 166 files
  1041 passed, 11 skipped, 0 failed, exit 0
  cwd apps/server，直譯器 ..\..\.venv\Scripts\python.exe
  11 個 skip 全部是缺 P2_POSTGRES_URL 的 PostgreSQL-gated 測試，
  該部分改由下方 CI 的 postgres-migrations job 覆蓋。
  執行於 44e4b4b；44e4b4b..3439cbe 只改 apps/web/e2e 與
  apps/web/scripts，backend 無差異，未重跑全套。

CI P2 Non-E2E（正式 workflow evidence）
  run id 34111033698 @ 3439cbe（exact final SHA）
  https://github.com/shellpig/adventure-table/actions/runs/34111033698
  conclusion success；backend / postgres-migrations / frontend 三個 job 全綠。
  postgres-migrations 在乾淨 PostgreSQL 17 上跑
  test_p2a_postgres_migration.py + test_p2b_postgres_workspace.py，
  其中 _assert_p2d_web_schema() 驗 campaign_seats 存在、三個 FK 的
  ondelete（campaign_id CASCADE / controller_access_session_id RESTRICT /
  selected_character_id SET NULL），以及
  (campaign_id, selected_character_id) unique constraint。
  前一個 SHA b1ee7a7 的 run 34109856936 亦為 success。
  對照組：6c4ae8d 的 run 34102224030 為 failure，正是 44e4b4b 修掉的
  P2-C CampaignRepository 契約回歸。

Frontend unit
  200 passed / 41 files

TypeScript / build
  npx tsc --noEmit exit 0
  npm run build（tsc --noEmit && vite build）exit 0

Full Web Playwright
  npm run test:e2e:docker exit 0 @ 3439cbe
  第一輪 107 tests：104 passed / 0 failed / 3 skipped（5.9m）
  第二輪 xge-less M03-C 子集：7 passed（5.9s）
  執行時 compose server 已在 0013_p2d_campaign_seats，
  /api/meta/capabilities 回 seat:true，確認 E2E 是對 P2-D backend 跑的。
  本次全套無 KI-P1D-001 失敗（見下方「順帶修掉的既有問題」）。

docker compose config
  exit 0
```

### 驗收條目 → 測試對應

| 條目 | 證據 |
|---|---|
| 1, 6 (create gate) | `test_p2d_seat_policy.py::test_lobby_and_seat_creation_require_current_active_campaign`、`::test_controller_and_character_mutations_require_current_active_campaign`；瀏覽器層 `p2d-lobby-seats.spec.ts::P2-D Lobby is reachable only while the Campaign is the Room current active Campaign`（draft 無入口 → active 仍無入口 → select 後出現 → clear 後 server 回 409） |
| 2, 3 | `test_p2d_persistence_contract.py::test_p2d_campaign_seat_schema_matches_contract`（無 ready 欄位）；`p2d-lobby-seats.spec.ts` 建 Seat 時 Roster 只有一隻角色而 Seat 有三個 |
| 4 | `test_p2d_seat_policy.py::test_one_human_controller_can_bind_multiple_player_seats`、`test_p2d_persistence_contract.py::test_p2d_controller_can_repeat_but_character_selection_is_unique_per_campaign` |
| 5 | 同上 unique constraint 條；`test_p2d_seat_persistence_integration.py::test_selection_transaction_rejects_cross_room_roster_corruption_and_duplicate_character` |
| 6, 7 | `test_p2d_seat_policy.py::test_player_character_selection_enforces_eligibility_and_uniqueness`、`test_p2d_seat_persistence_integration.py::test_selection_transaction_rechecks_roster_status_and_character_archive` |
| 8 | `test_p2d_persistence_contract.py`（CheckConstraint）＋ `p2d-lobby-seats.spec.ts` 斷言 DM Seat 沒有 Active Character 選單 |
| 9 | `test_p2d_seat_policy.py::test_lobby_presence_uses_p2a_ninety_second_timeout`（89s/91s 邊界）、`test_p2d_seat_lifecycle_evidence.py::test_offline_controller_keeps_seat_binding_and_reconnect_restores_connected_presence`；`RoomLobbyPage.test.ts` 鎖住 heartbeat 掛載與離開時的 `stopHeartbeat()` |
| 10 | `test_p2d_seat_api_permissions.py::test_create_seat_http_permission_matrix`（member/dm/owner × player/dm 六格）、`::test_member_cannot_operate_another_members_player_seat_via_http`、`::test_assigned_member_can_select_character_on_own_player_seat_via_http` |
| 11 | `test_p2d_seat_policy.py::test_dm_seat_assignment_is_owner_only_but_other_seat_management_allows_dm`、`test_p2d_seat_api_permissions.py::test_dm_cannot_reassign_dm_seat_via_http`、`test_p2d_seat_api_authority.py::test_owner_can_reassign_dm_seat_from_dm_a_to_dm_b_via_http`、`test_p2d_seat_policy.py::test_dm_controller_must_have_dm_or_owner_room_authority`、`test_p2d_seat_lifecycle_evidence.py::test_dm_seat_can_be_reassigned_from_one_dm_controller_to_another` |
| 12 | 上述所有 HTTP 層 deny 測試皆斷言 server response code，不檢查按鈕是否隱藏 |
| 13 | `test_p2d_seat_lifecycle_evidence.py::test_unreferenced_seat_delete_and_archive_release_character_for_another_seat`（archive 後 Seat 退出 Lobby、釋出角色、未引用的 Seat 可 hard delete）；`p2d-lobby-seats.spec.ts` 走完 archive → 新 Seat 接手同一角色 → delete 的瀏覽器路徑 |
| Controller 形狀 / AI 未接線 | `test_p2d_seat_policy.py::test_ai_controller_is_domain_shape_only_and_cannot_be_bound_in_p2`、`::test_p2d_router_exposes_seat_and_lobby_but_no_session_surface`、`::test_controller_must_be_an_active_access_session_from_same_room` |
| 選角收斂只發生在寫入路徑 | `test_p2d_seat_policy.py::test_lobby_read_does_not_reconcile_stale_selection`、`test_p2d_selection_convergence.py` 兩條、`test_p2d_character_archive_convergence.py`（走真實 `POST /api/rooms/{id}/characters/{id}/archive`） |
| controller FK RESTRICT 與 Room Hard Delete | `test_p2d_controller_fk_restrict.py::test_human_controller_session_is_restricted_but_room_hard_delete_cleans_seat_first`（`PRAGMA foreign_keys=ON`，真的驗到刪除被擋）；PostgreSQL 層由 `test_p2a_postgres_migration.py::_assert_p2d_web_schema` 斷言三個 FK 的 ondelete 與 unique constraint |
| capability 旗標 | `test_p2c_capabilities.py::test_web_channel_advertises_p2d_seat_capability`、`test_m03e_capabilities.py::test_web_capabilities_enable_room_campaign_and_seat_for_p2d`、`routes.test.ts` |
| standalone 不長 Seat schema | `test_m03d_schema_parity.py`（`campaign_seats` 已加入 `FORBIDDEN_MULTIPLAYER_TABLES`）、`test_m03_import_boundary.py`、`test_p2a_room_import_boundary.py` |
| migration track 分離 | `test_p2a_migration_tracks.py` 三條（`WEB_REVISIONS` 已納入 `0013_p2d_campaign_seats`） |
| 前端 route / 權限 / 文案 | `RoomLobbyPage.test.ts` 五條（含以 `renderToStaticMarkup` 實際 render 元件的兩條）、`seats.test.ts`、`RoomCampaignPage.test.ts`、`hardcodedUiCopy.test.ts`（`RoomLobbyPage.tsx` 已納入掃描清單） |

## 關門過程中修正的問題

Review 提出 6 項，全數已修並重新驗證。

1. **Lobby 只檢查 `campaign.status`，沒檢查 `rooms.active_campaign_id`。** [開發設計方針](開發設計方針.md) §8.2 明確定義 `active_campaign_id` 是「Room 目前 UI / Lobby 選中的 Campaign」，而 Room 可以同時有多個 `active` 狀態的 Campaign。原實作讓任何 `active` Campaign 都能開 Lobby，並留下一個從未被呼叫的 `SeatRepository.active_campaign_id()` — 那是被丟掉的檢查留下的痕跡。已改為 `_require_current_active_campaign()` 並套用到 create / controller / character / lobby 四條路徑，前端 Lobby 入口也一併加上同一條件。

2. **`create_seat` 未檢查 Campaign 狀態。** draft / completed / archived Campaign 都能建 Seat，只是開不了 Lobby。已與第 1 項同一個 gate 一併解決。`archive_seat` 與 `delete_seat` 刻意不套這個 gate，讓 Campaign 被換掉後仍能清理 Seat，並由 `test_seat_cleanup_remains_available_after_campaign_leaves_lobby` 鎖住。

3. **GET endpoint 會寫資料庫。** `list_seats()` 與 `lobby()` 原本呼叫 `_reconcile_selections()`，把不再 eligible 的 `selected_character_id` 清成 null — 任何 member 呼叫 GET 都會觸發寫入，GET 不再 idempotent。已移除該路徑，改在三條真正的寫入路徑收斂：Roster status 轉 `retired` / `dead`、Roster entry 移除、Room Character archive。`unarchive` 刻意不還原選角。

4. **`controller_access_session_id` 的 `ON DELETE SET NULL` 與 CHECK constraint 互斥。** `ck_campaign_seats_controller_binding` 要求 `controller_kind='human'` 時該欄非 null，SET NULL 一旦真的觸發就會撞 CHECK。已改為 `RESTRICT`，語意變成「還有 Seat 綁著就不准刪 access session」，並確認 `hard_delete_room()` 的既有順序（先清 campaigns 連帶 cascade seats，再刪 rooms）仍能通過。

5. **[測試指南](測試指南.md) §9.2 / §9.5 / §9.6 有四條沒有對應證據。** Seat hard delete、archived Seat 退出 Lobby selection、Offline 不動 Seat 與 Controller、reconnect 恢復 Connected、Owner reassign DM A → DM B。已補 `test_p2d_seat_lifecycle_evidence.py` 三條與 `test_p2d_seat_api_authority.py` 一條，全部打真實 repository 或真實 HTTP endpoint。

6. **`RoomLobbyPage` 只有原始碼字串斷言。** 已改用 `renderToStaticMarkup` 實際 render 元件，涵蓋 missing-access 與已授權載入兩種狀態；原本的字串斷言保留作為 heartbeat 接線的補充。瀏覽器層另補 `p2d-lobby-seats.spec.ts`（見下節）。

### 順帶修掉的既有問題

- **E2E global setup 的重置 SQL 順序在 P2-C 之後已經是壞的。** `DELETE FROM characters` 會被 `campaign_roster_entries.character_id` 的 RESTRICT 擋住，P2-D 再加上 `campaign_seats.controller_access_session_id` 的 RESTRICT 也會擋住 `DELETE FROM room_access_sessions`。之前沒爆是因為 E2E 從來沒有建過 Campaign — 正是 Journey 4 缺席的副作用。已改成先刪 Campaign-owned rows 再刪 Character 與 access session，並加上 campaigns / seats 的殘留計數斷言。
- **`select_active_campaign()` / `clear_active_campaign()` 現在會一併更新 `rooms.updated_at`。** 這是 P2-C 的行為變動而非 P2-D 需求，屬順手修正，不影響任何既有斷言。
- **KI-P1D-001 的 `character-builder` 那一半已找到根因並修復。** 該 spec 是唯一還只以 `expect(page.getByText('Saved on server')).toBeVisible()` 當作存檔完成條件的 Builder spec。這句話分不出「這次存檔完成」與「上一次存檔還留在畫面上」：點擊回傳時存檔請求尚未離開瀏覽器，指示器仍顯示前一次的成功，斷言立刻通過，後續的 `.summary-abilities` 就對著還沒收到重算摘要的 UI 斷言 —— 這也解釋了為什麼人手點同樣的步驟一直都正常。其餘十二支 Builder spec 早就改用 draft revision（點擊前記版號、點擊後等 `Draft revision N+1`），版號只在 server 收下這次寫入後才前進，不可能被前一次狀態滿足。已把該 helper 移植過來並保留本 spec 原有的 SRD 同名選項消歧邏輯。修正前 3 跑 3 敗（含單獨跑），修正後 5 跑 5 過，每次約 7.6 秒。**這是測試缺陷，不是產品缺陷**：非同步存檔與存檔期間 disable combobox 都是既有設計。

## 承接 P2-C 的未結清項目

- [x] **P2-C 的「沒有 browser journey」已補。** [測試指南](測試指南.md) §13 的 Journey 4（Campaign / Roster）由新增的 `p2d-lobby-seats.spec.ts` 走完真實後端路徑：建立 Campaign → 設為 active → 選為 Room 目前 Campaign → 加入 Roster → 確認名冊呈現。Journey 5 的 Session 前半段（Lobby / Seat / Controller / 選角 / archive / delete）同一支 spec 一併覆蓋；Start / End / Late Join 屬 P2-E，不在此。Journey 7（Cross-Campaign same Character）仍留給 P2-F。
- [x] **P2-C 交接條「Seat selection 不可沿用前端的 archived 過濾」已照辦。** archived Character 與 `retired` / `dead` roster status 都在 server 端 transaction 內拒絕，前端過濾只是同步呈現。

## Boundary

- P2-D 不建立 Session business logic。`test_p2d_router_exposes_seat_and_lobby_but_no_session_surface` 斷言 router 只有 `/seats` 與 `/lobby`，沒有 `/sessions`。
- `sessions`、`session_participants`、`active_character_session_leases` 一律不在 P2-D 建立；`0013_p2d_campaign_seats` 只新增 `campaign_seats` 一張表，不動既有欄位。
- AI 未提前接線。`ai` 只是 domain 與 DB 的合法值，API 拒絕綁定，UI 標示為尚未開放。
- `app.standalone` 不 import `app.main` 或任何 `app.*.rooms`。`test_m03_import_boundary.py` 的 `FORBIDDEN_MODULE_RE` 既有 pattern 已含 `seats?`，涵蓋新增的 `app.api.rooms.seats`、`app.domain.rooms.seats`、`app.persistence.rooms.seats`，本 Subphase 未擴充該 regex；`EXACT_PROTECTED_MODULES` 亦未變動。
- standalone migration 只升 `character@head`，SQLite 不長 `campaign_seats`。
- Character JSON 保持 Room / Campaign / Seat-neutral，envelope 不含 `seat_id`。
- Presence 只消費 P2-A 的 `RoomAccessSession` heartbeat contract，沒有第二套 liveness substrate，也沒有提前引入 P3 realtime event system。

## 已知限制

- **Seat hard delete 的 history guard 是空的。** `delete_unreferenced()` 目前無條件刪除，因為 P2-D 沒有 Session 表可以 reference。原始碼已標註，[實作規格](實作規格.md) 條目 13 的另一半必須在 P2-E 補上，屆時也要把 `sessions.dm_seat_id` 與 `session_participants.seat_id` 的 RESTRICT 語意一起帶進來。
- **`selected_character_id` 的 FK 是 `ON DELETE SET NULL`。** 目前不可達 — Character permanent delete 已被 `campaign_roster_entries.character_id` 的 RESTRICT 擋在更前面。它是防禦性宣告，不是 Seat 層的 history guard。
- **Seat 相關的併發與 FK 行為在本機只有 SQLite 證據。** `test_p2d_controller_fk_restrict.py` 靠手動 `PRAGMA foreign_keys=ON`，而 `with_for_update()` 在 SQLite 是 no-op。真 PostgreSQL 的 schema 斷言由 CI `P2 Non-E2E` 的 `postgres-migrations` job 覆蓋，但 **Seat selection 的併發勝負從未在 PostgreSQL 上驗過** — P2-E 建立 `active_character_session_leases` 時應把 Seat 選角的併發測試一併放進該 job。
- **`_present()` 對每個 Seat 各查一次 access session。** Lobby 另外還會 `list_access_sessions()` 撈同一批資料，是 N+1。Seat 數量在桌上跑團的量級可忽略，但若 P2-E 讓 Lobby 變成高頻輪詢的畫面，這裡要先併成一次查詢。
- **Campaign status 仍沒有 transition 規則。** P2-C 已記錄；P2-D 讓 `active` 多了「可開 Lobby」這個實質語意，卻仍可從 `completed` 退回 `draft`。若 P2-E 要讓 Session 只能從特定 status 開始，transition guard 必須在該 Phase 補上。
- **`display_name` 到 P2-D 才第一次有去處。** Lobby 的 controller 下拉與 Seat 卡片會顯示它，P2-B closeout 記錄的「填了零反饋」問題部分解除；但 Room landing 與 Character workspace 仍不呈現。
- **Room Hard Delete 的確認 modal 仍未顯示連帶刪除數量。** P2-B closeout 已記錄，P2-D 未處理，亦未加深。建議與 draft Campaign hard delete 的同類問題一起在 P2-F polish。
- **KI-P1D-001 只解掉一半。** `character-builder` 那一支已找到根因並修復（見「順帶修掉的既有問題」）。但 `已知問題.md` 記錄的另外兩支 `m01e` / `m01m` **本來就在用 draft revision 等待**，它們的失敗是 `waitForDraftRevision` 真的等滿 5 秒逾時 —— 那是真的慢，不是假通過，根因仍未確認。兩者被記在同一個 KI 編號底下，建議拆成兩條：已解的測試缺陷，與未解的存檔延遲。`已知問題.md` 屬 verifier 文件，本 Subphase 未自行改寫。
- **E2E global setup 仍會無條件清空 Character / Draft / Room。** P2-D 只修了刪除順序，沒有改變這個破壞性前提。本次驗證期間先以 `pg_dump` 備份本機開發資料。
- **P2-A 的 Room 層取捨全數延續。** throttle 為 process-local、`POST /api/rooms` 無 throttle 無授權、Room access token 以明文存 `localStorage` 且無到期機制。P2-D 未處理，亦未加深。

## Handoff

P2-D 已完成並關門。下一步是 **P2-E — Session Lifecycle & Late Join**。

P2-E 直接繼承以下 substrate，不得再造第二套：

- **`campaign_seats` 與 `SeatService`。** Session participant 一律來自正式 Seat；Late Join 需要新位置就先建 Seat 再加入，因此 `session_participants.seat_id` 不需要 nullable。
- **`_require_dm_seat_management()` 的 Owner-only 語意。** Start Session 時除了 authority ∈ `{dm, owner}`，還必須驗 caller 就是 Owner 事前 assign 到該 DM Seat 的 Human controller。Session 開始後 assignment 被 snapshot 成固定 current DM Controller，Owner 不得靠重綁 Campaign DM Seat 接管既有 Session。
- **`delete_unreferenced()`。** P2-E 必須在這裡加上 Session history 檢查並回 `seat_history_referenced` / 409，讓「有歷史就只能 archive」成真。不要在別處開第二套檢查。
- **`_require_current_active_campaign()`。** Session 也應該只能在 Room 目前選中的 Campaign 上開始；沿用同一個 gate，不要新寫一份條件。
- **選角收斂的寫入路徑。** `CampaignRepository._clear_seat_selection()` 與 `clear_character_seat_selections_in_transaction()` 是唯二的收斂點。P2-E 若讓 Session 也持有角色 reference，收斂邏輯要加進同樣的寫入路徑，而不是回頭在讀取路徑做。
- **`RoomWorkspaceRepository.hard_delete_room()` 的清除順序。** Session history 必須排在 Seat / Campaign 之前清除；現有的 `campaign_ids` 區塊已標好註解與位置。
- **`lobbyCopy.ts` 與 `hardcodedUiCopy.test.ts`。** 新畫面的 copy 進同一種 locale table，並把新檔案加進掃描清單。
- **`p2d-lobby-seats.spec.ts`。** Journey 5 的 Session 半段接在這支 spec 既有的 Lobby 狀態之後，不要另建一套 Campaign / Roster / Seat 前置。
