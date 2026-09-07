# P2-E Closeout Checklist

P2-E — Session Lifecycle & Late Join closeout scope。編號對應 [實作規格](實作規格.md)「P2-E — Session Lifecycle & Late Join」的各節要求。

## Start Session

- [x] 1. Session 狀態只有 `active` / `ended` / `abandoned`。`ck_sessions_status` 在 DB 層鎖住，`SessionStatus` 是唯一的 domain enum。
- [x] 2. Start 的 caller 必須是 **Owner 事前 assign 到該 DM Seat 的 Human controller**，且 Room authority ∈ `{dm, owner}`。`start_from_lobby()` 在同一個 transaction 內先驗 access session 未撤銷且 authority 相符，再從 `campaign_seats` 找出 `role='dm'`、`controller_kind='human'` 且 `controller_access_session_id` 等於 caller 的那一列。只持 DM Key 未被 assign、或有 Owner authority 但未被 assign，都拒絕。
- [x] 3. Start 只能在 Room 目前選中的 active Campaign 上發生。`start_from_lobby()` 同時驗 `campaigns.status='active'` 與 `rooms.active_campaign_id = campaign_id`，沿用 P2-D `_require_current_active_campaign()` 的同一組條件，不另寫第二份。
- [x] 4. Session identity 與 participant snapshot 一次建立。`_insert_session_rows()` 在同一 transaction 內寫 `sessions`、`session_participants` 與 `active_character_session_leases`；任一 lease 撞號即整筆 rollback，不留半成品 Session。
- [x] 5. 每個 Player Seat 的 Active Character 在 Start 當下固定。Seat 的 `selected_character_id` 被 snapshot 進 `session_participants.active_character_id`，之後 Lobby 改選不影響已開始的 Session。
- [x] 6. Start 時的 controller / role context 有記錄。`role_snapshot`、`controller_kind_at_join`、`controller_access_session_id_at_join` 三欄保存當下狀態，`ck_session_participants_controller_binding` 讓 `human` 必須帶 access session、`ai` / `none` 必須為 null。
- [x] 7. 本場 DM Controller identity 固定。`sessions.dm_controller_kind` / `dm_controller_access_session_id` 在 Start 當下寫死；DM heartbeat 逾時不改變 Session 狀態，同一 access identity reconnect 後仍是 current DM。Owner 事後重綁 Campaign DM Seat 不會改既有 Session 的 controller。
- [x] 8. Seat 歷史 reference 不會被刪成 null 洞。`sessions.dm_seat_id` 與 `session_participants.seat_id` 都是 `NOT NULL` + `ON DELETE RESTRICT`，`SeatRepository.delete_unreferenced()` 一旦查到任一側 reference 就丟 `SeatHistoryReferencedPersistenceError`，API 回 409 `seat_history_referenced`；archive 路徑不受影響。這補完了 [P2-D closeout](P2-D_CLOSEOUT.md) 條目 13 的另一半。
- [x] 9. 不強制 Ready / Online。沒有 ready 欄位也沒有 ready 動作；Player controller 已離線仍可 Start、空 Player Seat 不阻塞、Roster 中未被 Seat 選到的 Character 不會被自動塞進 Session。
- [x] 10. 同一 Campaign 同時只有一場 active Session。Start 前在鎖住的 Campaign row 上查既有 active Session，撞到就回 409 `session_already_active`；`ended` / `abandoned` 之後才能開下一場。

## Active Character freeze

- [x] 11. Session 開始後不得換角。沒有任何路徑可以改 `session_participants.active_character_id`；`PATCH .../participants/{id}/character` 存在的唯一目的是回 409 `session_active_character_locked`，讓「不能換」成為明確的 API 契約而不是靜默的缺口。
- [x] 12. Lobby 改選或 Roster status 變動不會回頭改寫已開始的 Session。收斂只發生在 P2-D 既有的寫入路徑上，Session snapshot 不參與收斂。
- [x] 13. Level Up / Build Edit 不能被當成換角手段。versioned Builder 的 `create_version_draft` / `patch_draft` / `confirm_draft` / `cancel_draft` 全部包進 `live_character_write_scope()` / `live_draft_write_scope()`，與 Character State patch 走同一組 Seat / current-DM 授權；角色 identity 本來就不因升等而改變。

## Concurrent Session invariant

- [x] 14. 同一 Character 不得同時是兩場 active Session 的 Active Character，且跨同 Room 多 Campaign 生效。`active_character_session_leases.character_id` 是 primary key，DB 層直接保證全域唯一；失敗側回 409 `character_already_in_active_session`。
- [x] 15. 這條 invariant 有真 PostgreSQL 併發證據。`test_p2e_postgres_sessions.py` 三條在 CI `P2 Non-E2E` 的 `postgres-migrations` job 對真 PostgreSQL 執行：兩個 transaction 同搶一隻角色只有一個 commit、跨 Campaign 撞既有 lease 對應到穩定 domain error、End 與 Late Join 交錯不留 partial lease。
- [x] 16. Archive 不能繞過 lease。`POST /characters/{id}/archive` 走 `unleased_character_write_scope()`，有 lease 就回 409 `character_in_active_session`。

## Late Join

- [x] 17. Late Join 只有本場 current DM Controller 可發起。Owner 但非本場 DM、其他持 DM Key 者，一律 403 `dm_controller_mismatch`。
- [x] 18. Late Join 從同 Campaign Roster 取合法 Character，且在 transaction 內重驗。`late_join_from_lobby()` 鎖 Session row 與 Seat row 後，重新 join `campaign_roster_entries` / `campaigns` / `room_characters` / `characters`：`retired` / `dead` roster status、archived Character、跨 Room Character 一律拒絕，不靠前端過濾。
- [x] 19. 已被另一場 active Session lease 的角色無法 Late Join，且失敗不留下 participant。lease insert 的 `IntegrityError` 在同一 transaction 內轉成 `LateJoinCharacterLeasedPersistenceError`，整筆 rollback。
- [x] 20. 不要求 spawn position。Late Join payload 只有 `seat_id`；Tactical placement 留給 P5。

## End / Abandon

- [x] 21. `End Session` 只有本場 current DM Controller 可執行。Owner 與其他 DM authority 不因權限較高而成為替代 DM，一律 403 `dm_controller_mismatch`。
- [x] 22. `Abandon Session` 由本場 current DM Controller 或 Room Owner 執行，且不建立 replacement DM。`abandon_session()` 完成後 `dm_controller_access_session_id` 仍是原本那一位。
- [x] 23. End / Abandon 都更新 status 與 `ended_at`、釋放本場全部 lease、保留 participants 與 Seat 歷史 reference。`finalize()` 在鎖住的 Session row 上一次做完，非 `active` 的 Session 回 409 `session_not_active`。
- [x] 24. **不改 Character Current State。** 不 heal HP、不 refresh spell slots / resources、不清 conditions、不重新準備 spells、不 archive Character。`finalize()` 完全不觸及 `character_states`。
- [x] 25. P3 session-scoped AI token 未提前偽造。P2 沒有 token table，也沒有假的 revoke hook。

## Resume

- [x] 26. Resume 只呈現 P2 目前真的存在的 structured state：Room、Campaign、active / unfinished Session、participants、參與 Seat（含已 archive 的歷史 Seat）、Active Character 摘要（名稱 / 等級 / 職業組成 / version）。
- [x] 27. Resume 不建立第二份 snapshot truth。`SessionResumeService` 組合既有的 `SessionService` / `RoomRepository` / `CampaignService` / `SeatService` / Character repository，不新增持久化。
- [x] 28. Combat Round / Pending Roll / Reaction 等 P3/P4/P5 資料沒有 placeholder。DTO 裡沒有這些欄位。

## Verification evidence

分支 `p2-e-session-lifecycle-late-join`，review 修正後 code SHA `d0cecb7`。

```text
Branch / final code SHA
  p2-e-session-lifecycle-late-join @ d0cecb7

Alembic heads
  0009_p2a_character_head (character) (head)
  0014_p2e_sessions (web) (head)
  0014 接在 0013_p2d_campaign_seats 之後，只落在 web track；
  standalone SQLite 仍只升 character@head，不會長出 sessions /
  session_participants / active_character_session_leases。

Backend pytest
  1046 collected / 180 files
  1036 passed, 10 skipped, 0 failed, exit 0
  cwd apps/server，直譯器 ..\..\.venv\Scripts\python.exe
  10 個 skip 全部是缺 P2_POSTGRES_URL 的 PostgreSQL-gated 測試
  （含 test_p2e_postgres_sessions.py 三條），改由下方 CI 覆蓋。

CI P2 Non-E2E（正式 workflow evidence）
  run id 34140748598 @ d0cecb7（exact final code SHA）
  https://github.com/shellpig/adventure-table/actions/runs/34140748598
  conclusion success；backend / frontend / postgres-migrations 三個 job 全綠。
  postgres-migrations 在真 PostgreSQL 上跑
  test_p2a_postgres_migration.py + test_p2b_postgres_workspace.py
  + test_p2e_postgres_sessions.py。
  review 前的 run 34136642169 @ 1666044 亦為 success。

Frontend unit
  219 passed / 47 files
  （d0cecb7 當下為 218；本 closeout commit 把 RoomSessionPage.tsx 加進
  hardcodedUiCopy.test.ts 的掃描清單，該檔多一條斷言。）

TypeScript / build
  npm run build（tsc --noEmit && vite build）exit 0

Full Web Playwright
  npm run test:e2e:docker exit 0 @ d0cecb7 + 本 closeout commit 的文件／掃描清單改動
  第一輪 107 tests：104 passed / 0 failed / 3 skipped（7.4m）
  第二輪 xge-less M03-C 子集：7 passed（6.5s）
  3 個 skip：m01j-subclass-expansion.spec.ts 的 direct-vs-sequential 等價
  （KI-M01J-001 intentional fixme，不計入 P2-E 功能證據），以及
  m03c-character-import.spec.ts 兩條需要缺 pack 後端的案例——後者正是
  第二輪跑的那批，已在該輪通過。
  執行時 compose server 已在 0014_p2e_sessions。

docker compose config
  exit 0
```

### 驗收條目 → 測試對應

| 條目 | 證據 |
|---|---|
| 1, 6, 8 (schema) | `test_p2e_persistence_contract.py::test_p2e_session_schema_matches_history_contract`、`::test_p2e_participant_schema_keeps_non_null_seat_history`、`::test_p2e_active_character_lease_uses_character_primary_key` |
| 2, 9 | `test_p2e_session_lifecycle.py::test_start_authority_matrix_offline_players_and_reopen_after_finalization`（Owner 未被 assign、另一 DM Key holder、一般 member 三種 deny；player controller 心跳逾時仍可 Start；空 Player Seat 與未被選到的 Roster 角色都不進 Session） |
| 3, 10 | 同上（finalize 後可重開下一場）；`test_p2e_session_lifecycle.py::test_start_freezes_dm_and_selected_players_then_end_releases_lease` |
| 4, 14 | `test_p2e_session_persistence.py::test_lease_collision_rolls_back_the_entire_second_session` |
| 5, 7, 23 | `test_p2e_session_lifecycle.py::test_start_freezes_dm_and_selected_players_then_end_releases_lease`、`::test_start_authority_matrix_offline_players_and_reopen_after_finalization`（DM 心跳逾時後 Session 仍 active，且仍由同一 identity End） |
| 8 (guard) | `test_p2e_session_persistence.py::test_session_referenced_seat_cannot_hard_delete_but_can_archive` |
| 11, 12 | `test_p2e_session_lifecycle.py::test_active_character_snapshot_ignores_lobby_and_roster_changes`；`test_p2e_session_api.py::test_session_http_error_contract_covers_read_join_lock_and_finalize`（409 `session_active_character_locked`） |
| 13, 16 | `test_p2e_live_character_scope.py::test_live_character_state_http_scope_tracks_current_player_controller_and_fixed_dm`、`::test_versioned_builder_mutations_use_same_live_character_scope`、`::test_active_character_cannot_be_archived_until_session_releases_lease` |
| 15 | `test_p2e_postgres_sessions.py::test_concurrent_session_lease_collision_has_one_atomic_winner`、`::test_cross_campaign_start_maps_existing_global_lease_to_stable_domain_error`、`::test_end_and_late_join_serialize_without_partial_lease`（CI `postgres-migrations` job） |
| 17, 18, 19, 20 | `test_p2e_late_join.py` 五條：`::test_late_join_is_current_dm_only_and_snapshots_selected_character`、`::test_late_join_revalidates_terminal_roster_status_inside_transaction`、`::test_late_join_revalidates_archived_character_inside_transaction`、`::test_late_join_revalidates_same_room_even_if_persistence_is_tampered`、`::test_late_join_maps_existing_global_lease_without_partial_participant` |
| 21, 22 | `test_p2e_session_lifecycle.py::test_owner_can_abandon_without_becoming_replacement_dm`、`::test_start_authority_matrix_offline_players_and_reopen_after_finalization`（另一 DM Key holder End 被拒） |
| 24 | `test_p2e_end_state_preservation.py::test_end_session_preserves_exact_rich_character_state_and_history`（HP / temp HP / conditions / prepared spells / spell slots / resources / hit dice / inventory 全部改過後整份 `model_dump` 比對，並先斷言每個欄位確實非空以防退化成 vacuous 相等） |
| 25, 28 | `test_p2e_session_api.py::test_session_routes_expose_start_resume_late_join_lock_end_and_abandon`（router 只有 Start / Resume / Get / Late Join / lock / End / Abandon，沒有 token、chat、roll、combat、snapshot 面） |
| 26, 27 | `test_p2e_session_resume.py::test_resume_composes_current_p2_truth_without_a_second_snapshot`、`::test_resume_without_active_session_keeps_room_and_campaign_truth` |
| Session 歷史 vs Campaign / Character 刪除 | `test_p2e_campaign_history_guard.py::test_campaign_with_session_history_cannot_be_hard_deleted_even_if_returned_to_draft`、`test_p2e_character_history_guard.py` 兩條（Session history 擋個別 Character permanent delete，未被引用者仍走中性 delete primitive） |
| Room Hard Delete 的 RESTRICT 圖 | `test_p2e_room_hard_delete.py::test_room_hard_delete_removes_session_restrict_graph_before_owned_history` |
| Restart persistence | `test_p2e_restart_persistence.py::test_restart_preserves_active_session_controller_participants_leases_and_access` |
| 穩定 API error code | `test_p2e_session_api.py::test_start_session_http_error_contract`、`::test_session_http_error_contract_covers_read_join_lock_and_finalize`；`test_p2e_session_start_error_typing.py` 兩條（分類依例外型別，不依訊息文字） |
| standalone 不長 Session schema | `test_m03d_schema_parity.py`（三張新表已加入 `FORBIDDEN_MULTIPLAYER_TABLES`）、`test_m03_import_boundary.py`、`test_p2a_room_import_boundary.py` |
| migration track 分離 | `test_p2a_migration_tracks.py`（`WEB_REVISIONS` 已納入 `0014_p2e_sessions`） |
| 前端 route / 權限 / 文案 | `RoomSessionPage.test.ts` 六條、`RoomLobbySession.test.ts` 兩條、`sessions.test.ts` 四條、`sessionMessages.test.ts`、`seatMessages.test.ts`、`p2eRequestMessages.test.ts`、`routes.test.ts`（`/rooms/{id}/campaigns/{cid}/sessions/{sid}` → `session` capability）、`hardcodedUiCopy.test.ts`（`RoomSessionPage.tsx` 已納入掃描清單） |

## 關門過程中修正的問題

Review 提出 4 項，全數已修並補上 regression。

1. **`character_in_active_session` 沒有 localized message，會顯示成誤導的重新載入提示。** `require_live_character_write()` / `require_character_unleased()` 回 409 `character_in_active_session`，但 `localizedRequestErrorMessage()` 對未知 code 且 status 409 一律 fallback 到 `revision_conflict`——「資料已在其他操作中更新，請重新載入後再試一次。」實際原因是角色正被本場另一位參與者控制，重新載入不會有任何幫助。已把該 code 加進 `REQUEST_CODE_MESSAGES`，訊息同時涵蓋 live edit 與 archive 兩種觸發情境，並由 `p2eRequestMessages.test.ts` 斷言 zh 不含「重新載入」、en 不含 `Reload`。

2. **`seat_history_referenced` 在 Lobby 只會吐英文 server message。** `RoomLobbyPage` 的錯誤處理對 `SeatApiError` 直接顯示 `error.message`，等於在 zh-TW UI 新增一段未翻譯字串。已新增 `seatMessages.ts`，`SeatApiError.message` 改為走 `currentSystemLocale()` 的 lazy getter，與 `createLocalizedRequestError` 同一 pattern；順手把整組 seat error code（共 8 個，逐一對回 `app/api/rooms/seats.py` 的實際 `APIError`）一併補齊，不只補新增的那一個。

3. **新的 Session route 落在 `campaign` capability gate。** `protectedCapabilityForPath()` 只特判 Lobby，`/rooms/{id}/campaigns/{cid}/sessions/{sid}` 會被 `ROOM_CAMPAIGN_ROUTE` 吃掉而回 `campaign`。因為 standalone 六個 multiplayer capability 全 false，boundary 沒有實際破口，但與 Lobby 明確 gate 成 `seat` 的做法不一致。已加 `ROOM_SESSION_ROUTE` → `session`，排在 campaign 之前，並補 `routes.test.ts` 斷言。

4. **Start 的錯誤分類靠字串比對。** `start_session()` 原本以 `if "Caller" in message or "Start requires" in message` 決定要丟 `DMControllerMismatchError` 還是 `SessionLobbyUnavailableError`——改動 persistence 的錯誤字句就會靜默改掉 HTTP error code。已新增 `SessionStartControllerMismatchPersistenceError`（`SessionStartPersistenceError` 的子類），persistence 的兩個 authority 拒絕點改丟子類，domain 端字串比對整段移除。`test_p2e_session_start_error_typing.py` 兩條分別驗「訊息完全改寫仍正確分類」與「訊息含 Caller 也不會誤判成 dm mismatch」。

### 順帶修掉的既有問題

- **`RoomSessionPage.tsx` 沒有進 `hardcodedUiCopy.test.ts` 的掃描清單。** [P2-D closeout](P2-D_CLOSEOUT.md) 的 handoff 明確要求新畫面要一併加進該清單。copy 本身確實住在 `sessionCopy.ts`，掃描補上後測試直接通過，也就是說沒有真的漏翻，但 gate 先前對這個新畫面是靜默放行的。已補進清單。

## 承接 P2-D 的未結清項目

- [x] **Seat hard delete 的 history guard 已補完。** 見條目 8。`delete_unreferenced()` 現在同時檢查 `session_participants.seat_id` 與 `sessions.dm_seat_id` 兩側。
- [x] **Character permanent delete 的 Session 半邊已補完。** `_HistoryGuardedCharacterRepository` 現在同時查 Campaign Roster 與 Session participant history，維持 409 `character_history_referenced`。
- [x] **Campaign hard delete 在有 Session history 時被擋住。** `delete_draft_without_session_history()` 在鎖住的 Campaign row 上同時驗 `status='draft'` 與無 Session history，補上 `sessions.campaign_id RESTRICT` 之外的 lifecycle guard。
- [ ] **Seat 選角的併發勝負仍未在 PostgreSQL 上驗過。** P2-D closeout 建議在 P2-E 建立 lease 時一併把 Seat selection 併發放進 `postgres-migrations` job。P2-E 只加了 Session lease 的三條併發測試，`SeatRepository.select_character_if_eligible()` 的 `with_for_update()` 至今仍只有 SQLite（no-op）證據。這不是 [實作規格](實作規格.md) 或 [測試指南](測試指南.md) 的 P2-E 契約條目，**明確順延到 P2-F**，不當作已完成。
- [ ] **Journey 5 後半、Journey 6、Journey 8 仍缺 browser 證據。** 見「已知限制」。

## Boundary

- P2-E 不提前實作 P7 Snapshot。沒有 snapshot payload、沒有 restore subsystem、沒有 snapshot store；Session 只保存 lifecycle metadata 與 participants。
- P2-E 不接 P3。router 只有 Start / Resume / Get / Late Join / character-lock / End / Abandon，沒有 chat、roll、pending action、AI join token、MCP 或 event queue。
- `app.standalone` 不 import `app.main` 或任何 `app.*.rooms`。`test_m03_import_boundary.py` 的 `FORBIDDEN_MODULE_RE` 既有 pattern 已含 `sessions?`，涵蓋新增的 `app.api.rooms.sessions`、`app.api.rooms.session_scope`、`app.domain.rooms.sessions`、`app.domain.rooms.session_resume`、`app.persistence.rooms.sessions`、`app.persistence.rooms.session_live`；本 Subphase 未擴充該 regex，`EXACT_PROTECTED_MODULES` 亦未變動。
- standalone migration 只升 `character@head`，SQLite 不長 `sessions` / `session_participants` / `active_character_session_leases`；三張表已加入 `test_m03d_schema_parity.py` 的 `FORBIDDEN_MULTIPLAYER_TABLES`。
- Character JSON 保持 Room / Campaign / Seat / Session-neutral，envelope 不含 `session_id`。
- Presence 仍只消費 P2-A 的 heartbeat，Session 頁沿用同一個 `startRoomHeartbeat`，沒有第二套 liveness substrate。
- Seat 是 Session participant 的唯一來源。Late Join 需要新位置就先在 Lobby 建 Seat 再加入，`session_participants.seat_id` 因此維持 `NOT NULL`。

## 已知限制

- **Session 層沒有專屬 browser journey。** [測試指南](測試指南.md) §13 的 Journey 5 後半（Start / End）、Journey 6（Late Join）、Journey 8（Active collision）目前只有後端與整合層證據。§13 的要求是「P2-F 前至少有」，所以不構成 P2-E 違約，但這三條連同 Journey 7 會一起壓在 P2-F。
- **Seat selection 併發只有 SQLite 證據。** 見「承接 P2-D 的未結清項目」。
- **Late Join 只接受既有 Seat。** [開發設計方針](開發設計方針.md) §10.6 允許「配置／選一個尚未參與的 Player Seat（或建立新 Seat）」，實作選了前者：payload 只有 `seat_id`，要新位置得先走 Lobby 的建 Seat 路徑。功能上等價，但多一步。
- **`character_in_active_session` 用 409 表示授權拒絕。** 語意上比較接近 403，但它同時承載「角色被佔用」這個資源狀態。code 已穩定並有雙語訊息，改動會是 API breaking change，不在 P2-E 處理。
- **`SessionResumeService` 對每隻 Active Character 各 load 一次完整 Character。** 參與人數在桌上跑團的量級可忽略，但 Session 頁與 Lobby 都會在每次 heartbeat 重抓 Resume，若 P3 讓這頁變成高頻輪詢，這裡要先改成批次查詢。P2-D closeout 記錄的 Lobby N+1 同樣未處理。
- **Campaign status 仍沒有 transition 規則。** P2-C / P2-D 已記錄。P2-E 讓 `active` 又多了「可開 Session」的語意，但 Campaign 仍可從 `completed` 退回 `draft`；`delete_draft_without_session_history()` 因此才需要同時檢查 status 與 Session history。真正的 transition guard 仍未存在。
- **KI-P1D-001 的 `m01e` / `m01m` 半邊仍未解。** P2-D 已把 `character-builder` 那一支的根因修掉；剩下兩支的存檔延遲根因未確認，P2-E 未觸碰。`已知問題.md` 屬 verifier 文件，本 Subphase 未自行改寫。
- **E2E global setup 仍會無條件清空 Character / Draft / Room。** P2-E 未改變這個破壞性前提；本次驗證期間先以 `pg_dump` 備份本機開發資料。
- **P2-A 的 Room 層取捨全數延續。** throttle 為 process-local、`POST /api/rooms` 無 throttle 無授權、Room access token 以明文存 `localStorage` 且無到期機制。P2-E 未處理，亦未加深。
- **Room Hard Delete 與 draft Campaign hard delete 的確認 UI 仍未顯示連帶刪除數量。** P2-B / P2-C 已記錄，P2-E 讓 Room Hard Delete 又多清一層 Session 圖，但確認 modal 沒變。建議在 P2-F polish 一次處理。

## Handoff

P2-E 已完成並關門。下一步是 **P2-F — Full P2 Integration & Closeout**。

P2-F 直接繼承以下 substrate，不得再造第二套：

- **`active_character_session_leases`。** 「同一 Character 只能在一場 active Session」的唯一真相在這張表的 primary key。P2-F 的 collision journey 應該打真實 API 觀察 409 `character_already_in_active_session`，不要另寫一套查詢式檢查。
- **`live_character_write_scope()` / `live_draft_write_scope()` / `unleased_character_write_scope()`。** active Session 期間的 Character 寫入授權只住這三個 context manager。P2-F 的 authorization matrix 應該打 HTTP 層驗它們，不要在別處補檢查。
- **`SessionResumeService`。** Resume 是組合而非第二份 snapshot。P7 真的做 Snapshot 時，接的是 Session lifecycle boundary，不是把這個 DTO 擴寫成 snapshot store。
- **`sessionMessages.ts` / `seatMessages.ts` / `REQUEST_CODE_MESSAGES` 三張表。** 新的 user-visible error code 進對應的那一張，不要在元件裡就地寫字串；新畫面同時加進 `hardcodedUiCopy.test.ts` 的掃描清單。
- **`p2d-lobby-seats.spec.ts`。** Journey 5 後半、Journey 6 與 Journey 8 應該接在這支 spec 既有的 Lobby 狀態之後，不要另建一套 Room / Campaign / Roster / Seat 前置。
- **`P2 Non-E2E` workflow。** 需要真 PostgreSQL 的證據一律進 `postgres-migrations` job；Seat selection 併發是已知的待補項。
