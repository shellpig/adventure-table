# P3-C Closeout Checklist

P3-C — Roll, Check & PendingAction closeout scope。編號對應 [實作規格](實作規格.md) 的「完成後必須為真」。

- [x] 1. 正式 roll 有可持久化 identity，reload / reconnect 不失去 pending request。`0018_p3c_roll_pending` 建 `roll_groups`、`roll_requests`、`roll_results`、`pending_actions` 四張表，`test_p3c_migration_contract.py::test_p3c_schema_has_canonical_roll_and_pending_tables` 與 `::test_p3c_metadata_and_migration_indexes_match` 鎖住 schema 與索引；Resume 端由 `test_p3c_resume_projection.py::test_p3c_resume_projects_canonical_roll_and_pending_truth_for_actor` 證明 pending truth 是 canonical 投影而不是第二份 Session JSON，browser 端由 E2E Journey C1 的 reload 段覆蓋。
- [x] 2. DM 可從 Player Action 或 DM Toolbar 建立 Request Check。兩條入口最後都進 `RollService.request_check()`：Toolbar 走 `SessionCheckRequestPanel`（`SessionCheckRequestPanel.test.tsx::builds a multi-target canonical skill request without inventing a roll`），Player Action 走 `/check` 交棒（`sessionCheckIntent.test.ts::hands a DM /check to Request Check UX without submitting a roll`）。
- [x] 3. Request Check 支援 Target / Check Type / Ability / Skill / optional DC / Normal-Advantage-Disadvantage / optional ±N / visibility。欄位由 `RequestCheckInput` 定義並在 model validator 強制 ability / skill ref 對應；`test_p3c_roll_engine.py::test_request_check_validates_target_and_rule_reference_shape` 蓋輸入契約，多角色 Target 由 `test_p3c_roll_group_and_authorization.py::test_group_check_tracks_each_seat_from_waiting_to_rolled` 實際建立兩個 Seat 的 request。
- [x] 4. Group Check 用同一 RollGroup 管多個 RollRequest，UI 顯示 Waiting / Rolled / Result，最終 fiction result 仍由 DM 判定。`test_group_check_tracks_each_seat_from_waiting_to_rolled` 斷言兩個 request 共用同一 `roll_group_id`、其中一個由 Seat 自己完成、另一個由 current DM 代理完成，中間狀態是 `resolved` 與 `pending` 並存；同一條測試也斷言 request projection 沒有 `outcome` / `success` / `group_result` 這類 Server 判定欄位。前端呈現由 `SessionRollRequestList.test.tsx` 的三條覆蓋。
- [x] 5. Server roll 產生 raw die、採用 die、modifier、total 與 source，AI 不得捏造 total。`RollEngine.d20()` 全部由 Server 計算；`test_p3c_roll_engine.py::test_server_d20_records_raw_kept_modifier_and_total` 蓋欄位，`::test_formal_input_never_accepts_client_dice_for_server_rng` 證明 `source=server` 帶 `raw_dice` 直接被 schema 拒絕。
- [x] 6. formal physical dice 必須提交 raw die，不能只輸入 final total。`FormalRollInput` 的 model validator 對 `source=physical` 強制 `raw_dice`，`RollEngine._physical_d20()` 再依 modifier mode 檢查顆數與 1–20 範圍；`test_physical_roll_requires_raw_dice_shape_not_final_total` 與前端 `SessionPhysicalRoll.test.ts` 三條同時覆蓋，total 一律由 Server 重算。
- [x] 7. Quick Dice 是獨立 convenience roll，不得自動完成 pending formal RollRequest。`ck_roll_results_request_binding` 在 DB 層要求 `source='quick'` 的 result 必須 `roll_request_id IS NULL`；`test_quick_dice_has_no_formal_request_semantics` 與 `SessionQuickDicePanel.test.tsx::builds convenience dice input independently of formal RollRequest identity` 蓋 service 與 UI 兩側。
- [x] 8. visibility 支援 `public` / `roller+DM` / `dm-only`，secret DC 與 dm-only result 不送 Player。`RollService._request_view()` 只在 `actor.is_current_dm` 時回 `dc`，其餘一律 `None`；HTTP 層 `_submission_response()` 對 dm-only 只回 `hidden=True` 與 identity。`test_p3c_roll_api_contract.py::test_dm_only_result_is_not_projected_to_player_response` / `::test_dm_can_receive_dm_only_result_details` 蓋兩個方向，`test_p3c_roll_visibility.py::test_private_formal_requests_wake_target_seats_without_exposing_result_audience` 證明非 public 的 request 事件走 `seat_private` 喚醒目標而不外洩 result audience。E2E Journey C1 另在 browser 端斷言 Player 的 request projection `dc` 為 null、畫面沒有 DC。
- [x] 9. 合法 Player controller 或 current DM proxy 都可完成；DM 代理用 target Character 規則計算並保留 acting + subject；跨 Seat、跨 Session、非 DM 第三方、舊 controller token 不能 submit。`test_p3c_roll_group_and_authorization.py` 四條：`test_current_dm_proxy_rolls_with_subject_character_rules_and_keeps_both_identities` 直接比對 result 的 `base_modifier` 等於 subject Character 自己算出來的 modifier，並斷言 `execution_mode='dm_proxy'` 與兩個 Seat identity 分離；`test_third_party_player_cannot_complete_another_seats_request` 證明第三方被拒且 runtime cursor 不動；`test_request_outside_this_session_is_never_resolvable` 蓋跨 Session id；`test_stale_actor_binding_cannot_submit_a_formal_roll` 蓋舊 access session。modifier 來源本身由 `test_p3c_character_rolls.py` 五條覆蓋（ability override、skill proficiency / expertise、saving throw、`other` 無隱藏 modifier、非法 ref）。
- [x] 10. `/check` 正式接手：Player 只能表達 Check intent，current DM 走同一 command 建立合法 RollRequest。`sessionCheckIntent.test.ts::turns a Player /check into PendingAction intent without a RollRequest` 與 `::hands a DM /check to Request Check UX without submitting a roll` 鎖住分流；`0019_p3c_check_command` 把 `check` 加進 `ck_session_messages_source_command`，`test_p3c_migration_contract.py::test_p3c_check_command_constraint_matches_metadata_and_downgrades_safely` 蓋 constraint 與 downgrade。
- [x] 11. formal completion 有 replay / duplicate submit 防護，不得 roll 兩次挑結果。`uq_roll_results_roll_request_id` 由 `test_formal_result_is_unique_per_request_and_quick_roll_is_unbound` 在 migration source 層斷言；`test_p3c_roll_retry.py::test_resolved_formal_retry_returns_canonical_result_without_new_rng` 證明 retry 不重新 RNG；`test_p3c_roll_concurrent_rng.py::test_concurrent_formal_submit_consumes_rng_only_inside_winning_completion` 蓋序列化邊界；真 PostgreSQL 證據為 `test_p3c_postgres_rolls.py::test_concurrent_formal_completion_commits_one_result_and_one_rng_draw`（兩個 actor 同時 submit，DB 只有一列 result、RNG 只被抽一次、兩邊看到同一個 total）。
- [x] 12. PendingAction 支援五個狀態且 transition 由 Server 驗證。`_ALLOWED_TRANSITIONS` 為唯一真值，`test_p3c_pending_actions.py` 四條蓋合法 / 非法 / 反向 transition 與 `waiting_for_roll` 必須帶 request；`ck_pending_actions_status` 由 `test_pending_action_state_machine_values_are_schema_guarded` 兜底；roll binding 由 `test_p3c_pending_roll_binding.py` 三條（同 subject、錯誤或已 resolved、跨 Session）覆蓋。cancel 與 resolve 的併發真 PostgreSQL 證據為 `test_p3c_postgres_rolls.py::test_concurrent_cancel_and_resolve_commit_exactly_one_pending_outcome`：兩個 actor 從同一 `expected_version` 同時搶，只有一個 commit，另一個拿到 stable 拒絕，durable event 只多一筆。
- [x] 13. ActionWindow 只能是 optional grouping，不得把 Exploration 變成固定 turn system。P3-C 沒有實作 ActionWindow；`pending_actions` 沒有 window / turn / initiative 欄位，Exploration 仍無回合概念。
- [x] 14. Roll resolve 後可透過同一 table action service 寫入合法 Character Current State，Human 與 DM proxy 兩條都證明，且不得 hardcode `RoomAccessContext.access_session_id`。`TableCharacterStateService` 只吃 `TableActorContext`，Human 假設集中在 `_human_binding()` 並標注 P3-D 會換掉；`test_p3c_table_character_state.py` 四條蓋授權與 identity，`test_p3c_table_character_state_persistence.py::test_table_state_self_and_dm_proxy_commit_state_with_audit_event` 蓋兩條 path 的實際落地與 audit event。
- [x] 15. 只建立完成 Exploration 所需的 transaction / atomic boundary，不提前交付 P7。Character State 與 event 在同一 transaction 內寫入，`test_failed_state_projection_rolls_back_event_and_state_atomically` 證明失敗時 event、runtime cursor 與角色狀態一起回滾；P3-C 沒有 generic transaction browser、Undo 或 Snapshot。
- [x] 16. user-visible error 全部 stable code + 雙語 mapping。`sessionMessages.ts` 新增 `P3C_SESSION_REQUEST_CODES` 十五個 code，`zh-TW` / `en` 成對；`sessionMessages.test.ts` 做 key parity 與非空檢查，API 端由 `test_p3c_roll_api_contract.py::test_roll_input_errors_have_stable_http_code`、`test_p3c_pending_api_contract.py::test_pending_action_domain_errors_have_stable_http_codes` 與 `test_p3c_state_api.py::test_table_state_errors_map_to_stable_p3c_codes` 對齊。

## Verification evidence

分支 `p3-c-roll-check-pending-action`。

```text
Alembic heads
  0015_character_state_revision (character) (head)
  0019_p3c_check_command        (web)       (head)

本機指令
  apps/server  pytest                       1247 collected, exit 0, 無 fail
                                            （新增 8 條：5 條授權 / Group 在此輪執行，
                                              3 條 PostgreSQL 在無 P3_POSTGRES_URL 時 skip）
  apps/web     npm test -- --run            63 files / 285 passed
  apps/web     npm run build                tsc --noEmit + vite build 通過
  repo root    docker compose config        pass
  apps/web     npm run test:e2e:docker      114 tests：111 passed, 3 skipped (8.2m)
                                            第二輪 xge-less m03c-character-import.spec.ts：7 passed
  apps/server  P3_POSTGRES_URL=... pytest tests/test_p3c_postgres_rolls.py
                                            3 passed（連跑三次穩定；本機以獨立的
                                            adventure_table_p3c database 執行）
```

E2E 的 3 skipped 是既有的 intentional skip（`m01j` direct high-level create 與 `m03c` 兩條需要缺 pack 後端的案例），後者由同一次 `test:e2e:docker` 的第二輪實際執行並通過。

`test_p3c_postgres_rolls.py` 已加入 `.github/workflows/p3-non-e2e.yml` 的 `postgres-migrations` job；該 job 是 CI 上唯一的真 PostgreSQL 證據來源，本機另以 docker compose 的 PostgreSQL 實跑過同一組測試。

E2E Journey C1 在 `apps/web/e2e/p3c-roll-check-pending-action.spec.ts`。它目前**只在本機全套執行時被跑到**：`p3-non-e2e.yml` 不含 E2E job，`p2-e2e.yml` 是 `workflow_dispatch`。

## 關門過程中修正的問題

1. **bounded Resume cursor 讓 reload 掉歷史。** P3-C 原本把 `eventStreamFromResume()` 的 cursor 從 0 改成 Resume 回傳的 cursor，並刪掉 P3-B 的 backfill 測試，改以「不再回掃 bounded window 之前的歷史」為預期行為。Resume 視窗是 `RECENT_EVENT_WINDOW = 50`，因此超過 50 個 raw event 的 Session，reload 後看不到更早的訊息，牴觸 P3-B 第 16 條與 P3-A 第 6 條。修正後只有在 Resume 能自證覆蓋 `after_seq == 0`、`has_more == false` 且 `cursor >= last_event_seq` 時才沿用該 cursor，否則退回 durable replay，P3-B 的 backfill 測試一併復原。
2. **Resume 競態會永久吃掉已畫出的訊息。** Session 頁在 mount 與每次 lifecycle mutation 都重抓完整 Resume，而 React 會重跑 mount effect，因此可能有多個 Resume 同時在飛；`reload()` 沒有 staleness guard，且整包取代 event stream，而 long-poll runner 擁有自己的單調 cursor、不會重送已送出的 page。晚回來的 Resume 因此會把剛畫出的 event 永久抹掉——P3-B Journey B2 的間歇性失敗（畫面停在 `No in-session messages yet.`）就是這條。修正後 `reload()` 只有最新一次可寫入，event stream 改為合併，`sessionEventStream.test.ts` 增加兩條回歸測試。
3. **契約 4、9 與真 PostgreSQL 併發缺測試證據。** 關門對照時發現：`complete_formal()` 的拒絕分支（非 current DM 第三方、跨 Seat、跨 Session、舊 access session）完全沒有測試觸發過，DM proxy「用 subject Character 規則計算」在 roll 層也沒有證據，Group Check 只有輸入格式驗證，且 P3-C 沒有任何 `test_p3c_postgres_*.py`，CI 的 PostgreSQL job 對本 Subphase 零覆蓋。補上 `test_p3c_roll_group_and_authorization.py`（5 條，真 repository）與 `test_p3c_postgres_rolls.py`（3 條，真 PostgreSQL），並把後者接進 CI job。

## Boundary

`app.domain.rooms.rolls`、`app.domain.rooms.pending_actions`、`app.domain.rooms.table_character_state`、`app.persistence.rooms.p3c_*`、`app.api.rooms.p3c_*` 全部含 `.rooms.` 區段，落在 `test_m03_import_boundary.py` 既有的 `FORBIDDEN_MODULE_RE` 內。`test_m03d_schema_parity.py` 的 `FORBIDDEN_MULTIPLAYER_TABLES` 已加入 `roll_groups`、`roll_requests`、`roll_results`、`pending_actions`，SQLite character track 不會被灌進這四張表。

新增的 roll / check capability 由 `test_p3c_capability_contract.py::test_p3c_roll_check_capability_is_web_only` 確認 standalone 側維持 false。

Character Current State 的寫入沒有回頭呼叫只吃 Human `RoomAccessContext` 的 P2 `live_character_write_scope()`，而是在同一 transaction 內鎖 `session_participants` 並重驗 subject binding；這是實作規格第 14 條要求的 actor-neutral 形狀，P3-D 會把兩條授權入口收斂成同一個 typed resolver。

## 已知限制

- **`MAX_BUFFERED_EVENTS` 仍是 200，長場次 reload 仍是完整 replay。** P3-B handoff 要求 P3-C 正面處理「提高上限或改成分頁載入」。P3-C 試過用 Resume 的 bounded cursor 取代 replay，但那會犧牲更早的可見歷史（見上節第 1 點），因此回到 replay。correctness 無誤，但長場次 reload 成本仍隨 event 數線性成長，且畫面只保留最後 200 筆。真正的分頁 / 回捲 UX 仍未做。
- **Group Check 沒有專屬的群組視圖。** `SessionRollRequestList` 是逐條 request 的清單，`roll_group_id` 只在資料層成立；「這一組共 4 人、2 人已擲」的彙總呈現沒有做。
- **E2E Journey C1 沒有 CI 覆蓋。** 只有本機 `npm run test:e2e:docker` 會跑到。若要進 CI，得決定把 E2E job 掛進 `p3-non-e2e.yml` 或改 `p2-e2e.yml` 的觸發條件，這牽動整體 CI 時間預算，留給 P3-F 一起決定。
- **PendingAction 的 `intent_payload` 目前沒有 schema。** 它是自由 JSON，`/check` 只塞 `{kind, source_command}`。P3-D 讓 AI 進桌後若要靠這個欄位交換結構化 intent，需要先定契約。
- **Lobby 的 per-Seat access-session N+1 未動。** P3-C 沒有提高 Session 頁對 Lobby 的依賴或輪詢頻率，屬「未惡化」而非「已修復」。
- **waiter starvation 測試仍借真實 `wait_after` 但 stub `list_after`。** P3-A 的原始限制未動，留給 P3-F 的資源安全整合。
- **真 PostgreSQL 證據涵蓋併發，不涵蓋 migration 之外的 restart。** `test_p3c_postgres_rolls.py` 每次由 alembic `heads` 建 schema，但沒有像 P2-F 那樣的真 PostgreSQL restart 整合；P3-F 仍需要那條。

## Handoff

P3-C 已完成並關門。下一步是 **P3-D — AI Controller, Scoped Token & Handoff**。

P3-D 直接繼承以下 substrate，不得再造第二套：

- **`_human_binding()` 是唯一的 Human 假設點。** `rolls.py`、`pending_actions.py`、`p3c_character_state.py` 三處各有一個，形狀相同且都在 AI actor 進來時直接丟 `TableEventActorUnauthorizedError`。P3-D 要做的是把它換成 Human/AI 共用的 typed resolver，不是在旁邊加一條 AI 專用路徑。
- **RollRequest / PendingAction / Character State 三個 service 都已 actor-neutral。** 它們只讀 `actor.controlled_seat_ids` 與 `actor.is_current_dm` 決定 self 或 dm_proxy，AI controller 接上後不需要改判定邏輯。
- **canonical row 加 event 的原子寫入形狀已定。** `RollRepository.complete_request()` 與 `PendingActionRepository.transition()` 都在同一 transaction 內寫 canonical row、event 與 runtime cursor，並共用 P3-A 的 idempotency key 機制與 `expected_actor_binding` 重驗。
- **`expected_actor_binding` 已經是每次寫入都重驗的 binding 檢查點。** P3-D 的 `controller_epoch` / grant generation 驗證接在這裡，不要另外在 API 層做一次就算數。
- **前端只有一條 long-poll runner，且 Resume 只能合併不能取代。** 見 `mergeResumeStream()`。P3-D 若為 controller 交接新增 Resume 觸發點，必須沿用這個合併語意，否則交接瞬間會吃掉桌上訊息。
- **雙語同步交付。** P3-D 的 grant / handoff / Take Back 錯誤都是 user-visible copy，依 AGENTS.md 工程實作守則 7 必須在同一個 Subphase 補齊 `zh-TW` 與 `en`。
