# P3-D Closeout Checklist

P3-D — AI Controller, Scoped Token & Handoff closeout scope。編號對應 [實作規格](實作規格.md) 的「完成後必須為真」。

- [x] 1. Seat controller 正式支援 Human / AI / None，controller type 與 connection 狀態分開，`AI + Offline` 是合法狀態。`ck_campaign_seats_controller_binding` 在 `0020_p3d_ai_controller_grants` 被 drop + re-add 成三選一的 typed binding（Human 必須有 access session 且無 grant、AI 必須有 grant 且無 access session、None 兩者皆空），`test_p3d_migration_contract.py::test_p3d_metadata_has_epoch_and_typed_ai_bindings` 鎖住三張表的形狀。presence 只住 `ai_controller_grants.last_seen_at`，`test_p3d_owner_abandon.py::test_owner_abandon_revokes_ai_dm_and_ai_player_atomically` 用 `last_seen_at=None` 的 grant 仍能 `resolve_actor()` 成功，證明離線不影響 controller 有效性。
- [x] 2. AI identity 是 Adventure Table 自己的 scoped Seat credential。`ai_controller_grants` 以 `(room_id, campaign_id, seat_id, role, generation)` 定義身分，沒有任何外部帳號 / 廠牌欄位；`AIControllerService.authenticate()` 只認自家 token，不讀 cookie 或 Room access token。
- [x] 3. Token 是高 entropy secret，只在 create / rotate 時完整顯示，persistence 只留不可逆 hash。`mint_ai_controller_token()` 用 `secrets.token_urlsafe(32)`，DB 只存 `secret_hash`（sha256 digest）與供辨識用的 `secret_prefix`，比對走 `hmac.compare_digest`。`test_p3d_token_codec.py` 四條蓋 round-trip、錯 secret、display hint 不含完整 secret 與 malformed token；`test_p3d_migration_contract.py::test_p3d_grant_schema_never_stores_plaintext_token` 從 schema 面確認沒有明文欄位。前端 `PlayerAIControlPanel.test.ts::keeps one-time controller tokens out of browser storage` 與 `LobbyAIDMGrantPanel.test.ts::keeps plaintext tokens ephemeral and renders returned expiry` 蓋 browser 端不落 storage。
- [x] 4. Token scope 固定 Room / Campaign / Seat / Role / generation，可操作 gameplay 時必須綁 Session。`ck_ai_controller_grants_scope` 要求 player grant 必須有 `session_id` 且無 TTL、dm grant 未綁時必須有 TTL；`AIControllerGrantRepository.resolve_current_scope()` 逐項比對 room / campaign / seat / session。跨場重用由 `test_p3d_session_ai_seat_retirement.py::test_finalize_retires_session_ai_binding_before_next_session` 擋下，domain 端整條路徑另見 `test_p3d_ai_dm_domain_journey.py::test_ai_dm_token_start_actor_end_and_revoke_journey`。
- [x] 5. 未綁 Session 的 pre-session AI DM grant 有有限 TTL，且只能做最小 Start context 與 Start。`DEFAULT_PRE_SESSION_DM_TTL` 為 15 分鐘，`resolve_current_scope()` 在 `session_id IS NULL` 時強制 `pre_session_expires_at` 存在且未過期、Campaign 為 `active`、且該 Campaign 仍是 Room 的 active Campaign；`AIControllerService.resolve_actor()` 對未綁 grant 直接拒絕產生 gameplay actor，因此它拿不到 event / Chat / Roll / Character State 任何一條。`test_p3d_ai_dm_session_lifecycle.py::test_ai_dm_start_rechecks_expiry_and_current_seat_epoch_before_creating_session` 與 `test_p3d_ai_controller_grants.py::test_pre_session_dm_rotate_invalidates_old_generation_and_expiry_is_authoritative` 蓋 TTL 權威性。
- [x] 6. Seat / Campaign / Room lifecycle 變化都讓未綁 grant 失效，Start 成功後改受 Session lifecycle 約束。`test_p3d_controller_lifecycle_revocation.py` 三條分別蓋 DM Seat AI→None（同一 mutation boundary 內 revoke + epoch 前進）、Seat archive、Campaign 進入 terminal status 與 Room active Campaign 切離；rotate 由 `test_pre_session_dm_rotate_invalidates_old_generation_and_expiry_is_authoritative` 蓋；Owner explicit revoke 走 `DELETE /seats/{seat_id}/ai-dm-grant`，由 `aiControllers.test.ts::creates and revokes finite pre-session AI DM grants on the DM Seat endpoint` 蓋 client 契約。
- [x] 7. AI 永遠不取得 Owner authority。AI 只會被解析成 `TableActorContext`（`access_session_id=None`），永遠不會產生 `RoomAccessContext` / `RoomAccessAuthority`；Owner-only 與 Owner/DM-only endpoint 一律 `Depends(get_room_access_context)`，只接受 Room bearer token。`grep` 全 `app/api` 只有 `access.py` 會產生 Room access context，AI token 沒有任何 HTTP 入口可取得它。
- [x] 8. Human Player 可對自己目前控制的 Seat 執行 `Let AI Control`，Character identity 與狀態不複製。`AIControllerGrantRepository.player_handoff_in_transaction()` 在 `FOR UPDATE` 下要求 `controller_kind='human'` 且 `controller_access_session_id` 等於 caller，然後只改 Seat binding；`session_participants` 與 `active_character_id` 完全不動。`test_p3d_ai_controller_grants.py::test_player_take_back_requires_exact_handoff_origin_access_session` 與 `test_p3d_player_recovery_instruction.py::test_lost_origin_requires_admin_recovery_and_instruction_does_not_leak` 蓋整段。
- [x] 9. Temporary Handoff Instruction 只屬於這次 grant。它住在 `ai_controller_grants.temporary_instruction`，不進 Character、Version、Biography 或 Campaign；`controller.changed` public payload 只有 `{controller_kind, reason}`，instruction 不在任何 public event 內。
- [x] 10. Instruction 在同一 generation 的 reconnect 後仍可取得，Take Back / revoke / End / Abandon 後立即失效且不沿用。`test_p3d_player_recovery_instruction.py` 的同一條測試斷言：handoff 後 `authenticate().temporary_instruction` 有值 → admin recovery 後舊 grant `temporary_instruction is None` → 重新 handoff 後以**新建的 service instance** 讀回仍是 `None`（證明來自 DB 而非 process memory）。End / Abandon 的清除由 `test_p3d_ai_dm_session_lifecycle.py::test_ai_dm_start_binds_pre_session_grant_once_and_finalize_revokes_it` 與 `test_p3d_owner_abandon.py` 蓋。
- [x] 11. `Take Back Control` 只認原 handoff 的仍有效 access session。`take_back_in_transaction()` 比對 `grant.handoff_return_access_session_id == caller_access_session_id`，其餘一律拒絕。`test_player_take_back_requires_exact_handoff_origin_access_session` 特意讓 h1 / h2 使用**相同 display name**，h2 被拒、h1 成功；Server 端的可見性由 `test_p3d_resume_take_back_scope.py::test_resume_repository_returns_only_exact_active_handoff_origin` 與 `::test_session_resume_projects_only_boolean_equivalent_seat_ids` 保證只回布林等價的 seat id 清單，前端不自行猜身分（`RoomSessionTakeBackScope.test.ts`、`PlayerAIControlPanel.test.ts::shows self-service Take Back only for the server-derived exact origin scope`）。
- [x] 12. 原 access session 遺失時走 Owner/DM administrative reassignment，不假裝有跨裝置 Human identity。`administratively_reassign_player()` 要求 Owner 或 DM authority，`admin_reassign_in_transaction()` 在同一 transaction 內 revoke 舊 grant、清 AI binding、設新 Human binding、`controller_epoch + 1`；audit 走 `visibility='dm_only'` 的 `controller.changed` event，payload 保留 admin 與 target 兩個 identity。證據為 `test_lost_origin_requires_admin_recovery_and_instruction_does_not_leak`（h1 revoked → h2 self-service 被拒 → admin 恢復成功 → epoch 為 `first.generation + 1` → audit event 欄位齊全）。
- [x] 13. Take Back 或 admin reassignment 後舊 token 立即失效。兩條 path 都會前進 Seat epoch 並清掉 Seat 的 `ai_controller_grant_id`，`resolve_current_scope()` 因此同時在「Seat 現綁 grant」與「epoch == generation」兩個條件上失敗。`test_player_take_back_requires_exact_handoff_origin_access_session` 在 Take Back 後直接斷言 `resolve_current_scope()` 丟 `AIControllerGrantUnauthorizedPersistenceError`；真 PostgreSQL 併發版本為 `test_p3d_postgres_controller.py::test_take_back_racing_old_ai_write_has_one_current_authority`。
- [x] 14. handoff 與進行中的 action 有清楚 atomic boundary。三條 controller mutation 全部以 `TableEventRepository.append(..., transaction_projection=...)` 執行，Seat binding 變更與 `controller.changed` event 共用同一 transaction；P3-C 起每次 gameplay 寫入都會重驗 `expected_actor_binding`，因此交接瞬間的舊 controller 寫入會落在 binding 檢查上。`test_p3d_postgres_controller_matrix.py::test_ai_dm_end_racing_write_revokes_old_actor` 與 `::test_owner_abandon_wakes_ai_wait_into_revoked_scope` 是真 PostgreSQL 證據。
- [x] 15. Player controller handoff 不改 participant / Active Character snapshot。`player_handoff_in_transaction()`、`take_back_in_transaction()`、`admin_reassign_in_transaction()` 三條 mutation 只寫 `ai_controller_grants` 與 `campaign_seats`，完全沒有觸碰 `session_participants` 的語句（handoff 只以 `FOR UPDATE` 讀取 participant 來確認 Seat 是本場有 Active Character 的 player）。這是結構性保證而非直接斷言；participant 欄位本身的合法性由 `test_p3d_postgres_controller.py::test_p2_human_controller_rows_survive_p3d_migration` 在真 PostgreSQL 上驗證。缺乏直接斷言一事記於「已知限制」。
- [x] 16. 每個 Seat 有單調遞增的 controller epoch SSOT，grant generation 是 immutable snapshot。`campaign_seats.controller_epoch` 為 NOT NULL，所有 controller 變更都只做 `+1`；`ai_controller_grants.generation` 在 insert 後永不 update（全 repository 沒有任何 `generation=` 的 update）。授權同時驗 grant status、Seat 現綁 grant id 與 `seat.controller_epoch == grant.generation`。`test_p3d_table_actor_binding.py::test_player_authorization_tracks_current_seat_not_join_snapshot` 與 `::test_ai_dm_requires_fixed_session_grant_and_generation` 蓋 domain 層，`test_p3d_session_ai_seat_retirement.py::test_start_fails_closed_on_tampered_stale_ai_player_binding` 蓋被竄改的 stale binding。
- [x] 17. DM Controller 一場之內固定，不支援中途 Human ↔ AI DM 交接。沒有任何 API 可改 active Session 的 `dm_controller_*`；`test_p3d_ai_dm_session_lifecycle.py::test_ai_dm_start_binds_pre_session_grant_once_and_finalize_revokes_it` 證明 grant 只能 bind 一次，`test_p3d_late_join_binding.py::test_late_join_revalidation_rejects_stale_ai_dm_epoch` 證明固定 DM 的 generation 不符時 Late Join 直接拒絕。
- [x] 18. P2 Human-only gameplay caller 已 migrate 成 typed actor。`TableEventService.resolve_human_actor()` / `resolve_ai_actor()` 產出同一個 `TableActorContext`，並在 `_require_valid_binding()` 對 Human / AI 兩種 shape 做互斥檢查；`SessionService` 的 current-DM 判斷、Late Join 重驗、End、current-DM Abandon 都改吃 actor，`start_session_as_ai_dm()` 與既有 `start_from_lobby()` 併存。live Character write 由 `require_live_character_actor_write()` 接手（`test_p3d_live_character_actor_policy.py` 兩條：Human 以**目前** binding 而非 join snapshot 授權、AI Player 與固定 AI DM 共用同一條 policy 且不需要 Human context）。P2 既有 caller 回歸中，本輪同步更新並通過的是 `test_p2e_session_lifecycle.py`、`test_p2e_session_api.py`、`test_p2e_session_persistence.py`、`test_p2e_persistence_contract.py`、`test_p2e_restart_persistence.py`、`test_p2e_session_start_error_typing.py`、`test_p2e_postgres_sessions.py`，以及 P2-D 的 `test_p2d_persistence_contract.py`、`test_p2d_seat_persistence_integration.py`、`test_p2d_seat_policy.py`、`test_p2d_selection_convergence.py`（fake seat repository 契約隨新欄位調整）。測試指南另外點名的 `test_p2e_live_character_scope.py` 與 `test_p2e_late_join.py` 未經修改即通過，是行為未退化的直接證據。
- [x] 19. AI DM 可成為新 Session 的起始 DM Controller。`configure_pre_session_ai_dm()` 由 Owner 在 Lobby 產生有限 TTL grant，`SessionRepository.start_from_ai_dm_grant()` 在 `FOR UPDATE` 下重驗 grant active / role=dm / 未綁 / 未過期 / generation 等於 Seat epoch，再檢查 `_lock_start_scope()` 的 Campaign active 與 Room active Campaign，成功後才寫入 `dm_controller_kind='ai'` 與 grant + generation snapshot。整條 journey 見 `test_p3d_ai_dm_domain_journey.py::test_ai_dm_token_start_actor_end_and_revoke_journey`，UI 入口見 `LobbyAIDMGrantPanel.tsx` 與其三條測試。
- [x] 20. persistence 用 DB constraint 區分 Human / AI / None binding。三條具名 CHECK 在 `0020` 全部 drop + re-add，Seat 增 `ai_controller_grant_id` + `controller_epoch`，`sessions` 增 `dm_controller_ai_grant_id` + `dm_controller_generation`，`session_participants` 增 `controller_ai_grant_id_at_join` + `controller_generation_at_join`，並各有 FK 與索引。`test_p3d_migration_contract.py::test_p3d_migration_replaces_all_three_named_controller_checks`、`::test_p3d_metadata_has_epoch_and_typed_ai_bindings`、`::test_p3d_migration_indexes_match_metadata` 鎖住形狀，`::test_p3d_migration_normalizes_uncredentialed_legacy_ai_rows` 蓋 P2 legacy row upgrade，`0013` / `0014` 未被修改。
- [x] 21. Session End / Abandon 撤銷所有 session-scoped AI grant。`SessionRepository.finalize_in_transaction()` 一次做完：把仍綁該 Session active grant 的 Seat 打回 `none` 並 `controller_epoch + 1`、把 grant 設為 `revoked` 並清 instruction、改 Session status、刪 `active_character_session_leases`。`test_p3d_ai_dm_session_lifecycle.py` 與 `test_p3d_owner_abandon.py::test_owner_abandon_revokes_ai_dm_and_ai_player_atomically` 斷言 DM 與 Player 兩張 grant 都變 `revoked`、instruction 清空、舊 token `resolve_actor()` 被拒、lease 已釋放。
- [x] 22. revoke 與 lifecycle transition 在同一 atomic boundary。上述所有寫入都在 `finalize_in_transaction()` 的單一 connection / transaction 內，且整段又包在 `TableEventRepository.append()` 的 `transaction_projection` 中，因此 final event 失敗時 revoke 與 status 一起 rollback；`test_p3d_owner_abandon.py` 斷言最後一筆 event 是 `session.abandoned`，`test_p3d_session_ai_seat_retirement.py::test_finalize_retires_session_ai_binding_before_next_session` 證明 finalize 後下一場需要新 grant。
- [x] 23. AI DM disconnect 不會自動 End，也不讓別人接管。`resolve_current_scope()` 完全不讀 presence；`last_seen_at` 只在 `touch=True` 時更新，沒有任何 timeout 會改 grant status。`test_p3d_owner_abandon.py` 用 `last_seen_at=None` 的 grant 驗證離線 actor 仍是合法 current controller，Owner 也只能走既有 Abandon escape hatch（`abandon_session()` 仍要求 Owner authority，不是 current-DM 權限）。
- [x] 24. revoke / rotate / handoff / Take Back / admin reassignment 在真 PostgreSQL 併發下安全。`test_p3d_postgres_controller_matrix.py` 十條覆蓋兩個 Let AI Control、Let AI Control vs Take Back、Take Back vs admin reassignment、兩個 admin reassignment、pre-session rotate vs Start、DM Seat mutation vs Start、Campaign lifecycle vs Start、重複 AI DM Start、End vs write、Abandon 喚醒等待中的 AI；`test_p3d_postgres_controller.py` 另兩條蓋 P2 legacy row migration 存活與 Take Back vs 舊 AI 寫入。沒有任何一條留下兩個有效 generation 或跨 Session 重綁。
- [x] 25. reconnect 後由 Server 取回 controller scope、instruction 與 pending state。Human 走 Session Resume（`self_take_back_seat_ids` + `seats` 為 caller-specific 投影，見 `test_p3d_resume_take_back_scope.py` 兩條與前端 `RoomSessionTakeBackScope.test.ts`）；AI 走 `authenticate()`，instruction 從 DB 讀回，`test_lost_origin_requires_admin_recovery_and_instruction_does_not_leak` 以重建 service instance 證明不依賴 process memory。
- [x] 26. P3-D 不宣稱 MCP tool surface 已交付。`app/api` 內沒有任何 endpoint 接受 AI token；AI 目前只能在 domain / application service 層被授權與驗證，正式外部入口留給 P3-E。

## Verification evidence

分支 `p3-d-ai-controller-scoped-token-handoff`，code SHA `6db34ea`。

```text
Alembic heads
  0015_character_state_revision (character) (head)
  0020_p3d_ai_controller_grants (web)       (head)

本機指令
  apps/server  pytest                       1294 collected, exit 0, 無 fail
                                            （14 skip 為需 P3_POSTGRES_URL 的
                                              test_p3d_postgres_controller*.py）
  apps/server  pytest tests/test_p3d_*.py    47 selected：33 passed, 14 skipped
  apps/web     npm test -- --run             67 files / 298 passed
  apps/web     npm run build                 tsc --noEmit + vite build 通過
  repo root    docker compose config         pass
  apps/web     npm run test:e2e:docker       改動畫面對應 spec（p2a / p2d /
                                             p2f-session-lifecycle / p2f-cross-campaign /
                                             p3b / p3c）：12 passed
  apps/web     npm run test:e2e:docker       全套 114：111 passed, 3 skipped (7.8m)
                                             第二輪 xge-less m03c-character-import.spec.ts：7 passed
```

E2E 的 3 skipped 是既有的 intentional skip（`m01j` direct high-level create 與 `m03c` 兩條需要缺 pack 後端的案例），後者由同一次 `test:e2e:docker` 的第二輪實際執行並通過。P3-D 沒有新增 E2E spec，全套是合併回 `main` 的 gate。

GitHub Actions：`P3 Non-E2E` run `34455746357`，exact SHA `6db34ea`，四個 job 全 success。

- `backend`：全套 pytest。
- `postgres-migrations`：真 PostgreSQL job，明列執行 `test_p3d_postgres_controller.py`、`test_p3d_postgres_controller_matrix.py`，以及 legacy real-Postgres 回歸 `test_p3a_postgres_events.py`、`test_p3b_postgres_stage.py`、`test_p3c_postgres_rolls.py`、`test_p2a_postgres_migration.py`、`test_p2b_postgres_workspace.py`、`test_p2e_postgres_sessions.py`、`test_p2f_postgres_seat_selection.py`、`test_postgres_roster_lock_order.py`、`test_m03c_migration.py`。這 14 支在本機因缺 `P3_POSTGRES_URL` 而 skip，在此 job 實際執行。
- `frontend`：`npm test -- --run` 與 `npm run build`。
- `windows-standalone`：`scripts\build-standalone.cmd` + `smoke_standalone.py`，standalone 發版路徑未因 P3-D 退化。

`test_p3_workflow_contract.py` 已同步 `p3-non-e2e.yml` 的分支清單與 PostgreSQL test file 清單，避免新增的兩支 P3-D PostgreSQL 測試在 CI 靜默漏跑。

## Boundary

`app.domain.rooms.ai_controllers`、`app.domain.rooms.ai_controller_tokens`、`app.persistence.rooms.ai_controllers`、`app.api.rooms.ai_controllers` 全部含 `.rooms.` 區段，落在 `test_m03_import_boundary.py` 既有的 `FORBIDDEN_MODULE_RE` 內，不需擴充 regex。`ai_controller_grants` 只建立在 web migration track（`0020`），character track 仍停在 `0015`，standalone SQLite 不會長出 controller grant 表。全套 pytest 內的 `test_m03_import_boundary.py` 與 `test_m03d_schema_parity.py` 通過。

## 已知限制

- **`ai_controller_grants.secret_prefix` 存了 token secret 的前 6 個字元。** 形式為 `at_ai_<grant hex>_<secret[:6]>…`，供 Lobby / Session UI 辨識是哪一張 grant。測試指南 token 案例 2 的字面要求是「DB row / log 不含 plaintext」，這是刻意的取捨：剩餘 entropy 仍有約 37 個 urlsafe 字元，實務上無爆破風險，但嚴格說不是零明文。若日後要收乾淨，改成只存 grant id 前綴即可，`test_p3d_token_codec.py::test_ai_token_display_hint_does_not_contain_plaintext_secret` 目前只斷言不含**完整** secret。
- **`controller.changed` event 前端沒有消費。** Session 頁的 controller 顯示來自 Resume（初次）與 Lobby 輪詢（後續），event stream 只把它當一般 log 列。因此沒有 Lobby 讀取權的 caller 在別人交接後要 reload 才會看到新的 controller。P3-B closeout 掛給 P3-D 的「座位變動即時同步」只收斂了授權面與初次載入面（Resume 現在帶 `seats` 與 `self_take_back_seat_ids`，不再凍結在進場當下的 join snapshot），真正的 event-driven 更新未做。
- **P3-D 的新 UI 沒有 browser 證據。** `LobbyAIDMGrantPanel` 與 `PlayerAIControlPanel` 只有 vitest 單元測試；handoff / Take Back / admin recovery / AI DM Start 的 browser journey 依測試指南本來就掛在 P3-F 第 6、7、8 條，P3-D 不重複交付。
- **AI 尚無 HTTP 入口，因此 P3-D 的 AI 授權證據全部在 domain / repository 層。** 這符合實作規格第 26 條，但代表「AI 真的能進桌」要到 P3-E 才會有 end-to-end 證據。
- **`abandon_session()` 仍是 Owner authority escape hatch。** 固定 AI DM 以 current-DM 身分 End 已有證據，但「AI DM 自己 Abandon」這條 current-DM path 在本 Subphase 沒有專屬測試，留給 P3-F 的權限矩陣。
- **「handoff 不改 participant snapshot」只有結構性保證，沒有直接斷言。** 三條 controller mutation 確實沒有寫 `session_participants` 的語句，但沒有一條測試在 handoff / Take Back / admin reassignment 前後比對 participant row 與 `active_character_id`。若日後有人在這三條路徑加寫入，現有測試不會擋。P3-F 的 Player handoff journey D1 / D1b 應該補上這個前後比對。
- **Lobby 的 per-Seat access-session N+1 未動。** P3-D 沒有提高 Session 頁對 Lobby 的依賴或輪詢頻率，仍屬「未惡化」而非「已修復」。
- **waiter starvation 測試替身未動。** P3-A 的原始限制原封不動，留給 P3-F 的資源安全整合。

## Handoff

P3-D 已完成並關門。下一步是 **P3-E — AI Tool Surface & Event Delivery**。

P3-E 直接繼承以下 substrate，不得再造第二套：

- **`AIControllerService.resolve_actor(token)` 是 AI 進桌的唯一入口。** 它已經回傳與 Human 完全同型的 `TableActorContext`，MCP transport adapter 只要拿 token 換 actor，然後呼叫既有 application service，不要在 MCP 層另寫一套授權。
- **未綁 Session 的 pre-session DM grant 刻意在 `resolve_actor()` 被拒。** 它只能經 `authenticate()` 取得最小 Start context 與呼 `start_session_as_ai_dm()`。P3-E 若要提供 pre-session tool，必須走 `authenticate()` 這條，不能放寬 `resolve_actor()`。
- **`resolve_current_scope()` 是唯一的 current-binding 檢查點。** grant status、Seat 現綁 grant id、`controller_epoch == generation`、Session active、fixed DM snapshot、pre-session TTL 全部在這裡。P3-E 不要在 tool handler 重做一次簡化版檢查。
- **`touch=True` 是唯一更新 `last_seen_at` 的路徑。** presence 不參與授權；P3-E 若要做 AI 在線指示，用這個欄位，不要讓 presence 影響 grant 有效性。
- **event 讀取與等待沿用 P3-A 的 async / no-DB-hold contract。** `get_pending_events` / `wait_for_event` 必須包既有 HTTP wait path，不能在 MCP adapter 重新包一層同步 blocking wait。
- **雙語同步交付。** P3-E 新增的任何 user-visible error 或 tool 描述，依 AGENTS.md 工程實作守則 7 必須在同一個 Subphase 補齊 `zh-TW` 與 `en`。
