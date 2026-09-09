# P3-B Closeout Checklist

P3-B — Exploration, Chat & Actions closeout scope。編號對應 [實作規格](實作規格.md) 的「完成後必須為真」。

- [x] 1. Session UI 有 Main Stage、右側 Chat / Dice / Log 與桌面角色摘要。`SessionTableSurface.tsx` 提供 `session-stage` 主舞台、`session-table__characters` 角色摘要與 Chat / Dice / Log 三個分頁；Dice 與 Log 在 P3-B 只是佔位與 raw event 列表，玩法面留給 P3-C。側欄寬度是純前端偏好，`sessionTableLayout.test.ts` 鎖住上下界、鍵盤操作與壞值回退。
- [x] 2. Main Stage 支援 Text only / Image only / Image + Text / Clear。`test_p3b_stage.py::test_stage_supports_all_four_modes_and_emits_ordered_public_events` 逐一走過四種模式並斷言 event 順序。
- [x] 3. 最小 Room-scoped Stage image upload / replacement，Room Hard Delete 一併清掉。`room_stage_images` 以 `room_id` 為 FK 且 `ondelete="CASCADE"`，`test_p3b_migration_contract.py::test_p3b_schema_keeps_messages_canonical_and_images_room_scoped` 直接斷言 migration source 帶這個 cascade；`test_p3b_stage_canonical_event_path.py::test_stage_image_is_scoped_to_its_room` 證明 Room A 的圖不能由 Room B 的 access 取得。
- [x] 4. Stage image 只服務「目前舞台」。`ExplorationStageService.get_image()` 先讀出當前 Stage，`image_id` 不符即 `stage_image_not_found`；沒有 Asset Library、folder / tag、Scene entity 或 map 概念。`0017` 只新增 `room_stage_images`、`session_stages`、`session_messages` 三張表。
- [x] 5. Stage 由本場 current DM Controller 修改，持 DM Key 但不是本場 DM Controller 者不能改。`replace_stage()` 檢查 `actor.is_current_dm`；`test_p3b_stage.py::test_only_current_dm_can_change_stage_and_stale_dm_is_rejected_in_transaction` 蓋 Player 與 revoke 後的 stale DM，`::test_dm_key_holder_who_is_not_the_session_dm_cannot_change_the_stage` 另外構造一個持 Room DM 權限、但只坐 Player Seat 的 actor，斷言被拒且 revision 未被推進。
- [x] 6. Exploration input 支援 Character Dialogue / Action / OOC / Whisper DM，DM 另可 Narration。`ExplorationInputKind` 五種 kind 由 `ck_session_messages_kind` 在 DB 層兜底；Narration 的 DM-only 送出權由 `test_p3b_exploration_actions.py::test_whisper_is_server_filtered_to_sender_and_current_dm_and_narration_is_dm_only` 覆蓋。
- [x] 7. Slash command 轉成同一 typed Exploration input，不形成第二套 endpoint。`sessionExploration.ts` 的 `parseExplorationComposer` 只做語法轉換，四個 command 全部落到 `POST .../exploration` 的同一個 `ExplorationActionService`；`/check` 回 `blocked_check`，前端不發任何請求。`sessionExploration.test.ts` 的「maps slash commands into the same typed input contract」與「blocks check ownership and never manufactures a roll request」鎖住這點。
- [x] 8. `/search` 只是語意捷徑，不自動選 Skill、不建立 RollRequest。`source_command` 是 `Literal["search"]`，且 `ck_session_messages_source_command` 限制它只能是 `search`；P3-B 沒有任何 RollRequest / RNG 程式碼路徑。
- [x] 9. Dialogue / Action 綁合法 Seat / Active Character，一人控多 Seat 必須明確選角。`ExplorationInputRequest` 在 model validator 強制 dialogue / action 帶 `subject_seat_id`；`test_one_human_controlling_multiple_player_seats_must_choose_subject_explicitly` 證明兩個 Seat 各自解析出正確的 acting identity。
- [x] 10. current DM 可代理任意 Player Seat，走同一套 Player 規則且不改 Seat Controller。`ExplorationActionService.send()` 對非自控 Seat 只有 `is_current_dm` 一條路，走的是同一個 `_subject()` 驗證；`test_p3b_closeout_gates.py::test_dm_proxy_never_changes_human_or_ai_seat_controller` 在 Human 與 AI 兩種 controller 下比對代理前後的 Seat row。
- [x] 11. DM proxy 保存 acting DM 與 subject Seat / Character。`session_messages` 同時存 `acting_seat_id`、`subject_seat_id`、`subject_character_id` 與 `execution_mode='dm_proxy'`；`test_dialogue_action_search_and_dm_proxy_keep_subject_and_acting_identity_distinct` 斷言兩個身分不會被壓成同一個。
- [x] 12. proxy 涵蓋 Dialogue / Action，且 Seat 是 Human / AI / Offline 都不影響。同上的 closeout gate 測試涵蓋 Human 與 AI controller；offline 在資料層與 Human 同形，因為代理判定只看 `is_current_dm`，不看 controller 是否在線。
- [x] 13. Whisper DM 只對 sender 與 current DM 可見。`visibility='seat_private'` 加上 `recipient_seat_ids`，由 `TableEventService._visible()` 在 projection 過濾；`test_whisper_is_server_filtered_to_sender_and_current_dm_and_narration_is_dm_only` 斷言第三方的 `list_after()` 回空陣列，前端完全拿不到內容。
- [x] 14. 不依 timestamp 強制 fiction turn order。canonical 排序只有 event `seq`，沒有 turn / initiative 概念。
- [x] 15. Action 是自由文字 intent。`text` 是自由字串，沒有 pending / lifecycle 欄位；正式 lifecycle 留 P3-C。
- [x] 16. reload / reconnect 後 Stage 與已 commit 訊息仍在。`eventStreamFromResume()` 對新的 browser session 從 cursor 0 重播 durable 歷史（Server 端仍逐筆過濾 audience）；`test_p3b_closeout_gates.py::test_stage_and_message_survive_database_restart` 蓋 server 側，E2E Journey B1 蓋 browser reload。
- [x] 17. 新增 UI copy / error / aria label 同 Subphase 交付 `zh-TW` / `en`。`sessionCopy.ts` 兩個 locale 同步新增，`sessionMessages.ts` 新增五個 P3-B request code 的雙語訊息；`SessionTableSurface.tsx` 已加入 `hardcodedUiCopy.test.ts` 的掃描清單，`sessionExploration.test.ts` 的「keeps zh-TW and en keys aligned and populated」做 key parity。
- [x] 18. 不做 Point-and-Click 動詞選單、Exploration grid、`current_scene_id`、Fog of War、Vision / LOS。P3-B 沒有任何座標、視野或 scene id 欄位。

## Verification evidence

分支 `p3-b-exploration-chat-actions`。

```text
Alembic heads
  0015_character_state_revision (character) (head)
  0017_p3b_exploration_stage   (web)       (head)
  branchpoint 0008_m03c_import_records -> 0009 (character) / 0010 (web)

本機指令
  apps/server  pytest                       1158 passed, 20 skipped (394.66s)
  apps/web     npm test -- --run            55 files / 255 passed
  apps/web     npm run build                pass（既有 chunk-size 警告）
  repo root    docker compose config        pass
  apps/web     npm run test:e2e:docker      113 tests：110 passed, 3 skipped (8.0m)
                                            第二輪 xge-less m03c-character-import.spec.ts：7 passed

GitHub Actions
  P3 Non-E2E  run 34326610019  @ 77bf7c6  綠
    backend / frontend / postgres-migrations / windows-standalone 四個 job 全綠
```

E2E 的 3 skipped 是既有的 intentional skip：`m01j` 的 direct high-level create，以及 `m03c` 兩條需要缺 pack 後端的案例——後者由同一次 `test:e2e:docker` 的第二輪（server 以移除 `xge` 的 pack 清單重啟）實際執行並通過。

`postgres-migrations` job 明列並實際執行 `test_p3b_postgres_stage.py`（五條：index 加 atomic stage event、stale DM rollback、message/cursor idempotent replay、stale actor rollback、projection failure rollback），以及既有的 `test_p3a_postgres_events.py`、`test_p2a_postgres_migration.py`、`test_p2b_postgres_workspace.py`、`test_p2e_postgres_sessions.py`、`test_p2f_postgres_seat_selection.py`、`test_postgres_roster_lock_order.py`、`test_m03c_migration.py`；這些檔案在本機沒有 `P3_POSTGRES_URL` / `P2_POSTGRES_URL` 時會 skip，唯一的真 PostgreSQL 證據來自該 job。

P3 Non-E2E 的最後一次綠燈在 `77bf7c6`，之後的 commit 只改動 E2E spec、backend 測試、`RoomSessionPage` 的 banner 呈現與一條 CSS。其中 backend 與前端單元測試面已由本機全套覆蓋，E2E 面由上表的全套執行覆蓋。

## 關門過程中修正的問題

1. **兩條 real-backend journey 從未綠過。** B1 與 B2 都死在 Playwright strict mode，不是桌面行為出錯。`getByLabel` 比對的是外層 label 的文字，而 composer 兩個 select 的 label 文字包含全部 option 標籤；`Character` 又同時命中可調整版面時加入的 `aria-label="Table Characters"` 區塊。改用 role 加 exact accessible name。reload 後的 Stage 斷言是同一類問題的另一面：DM 的 Stage 編輯器會從已存的 Stage 回填，於是同一段文字同時出現在畫布段落與 textarea，該行改為 scope 到 `.session-stage__canvas`。
2. **gate 4 與 gate 21 缺精確證據。** 原本只證明 Player 被拒與 access session 被 revoke 的 stale DM 被拒，沒有「持 Room DM Key、但不是本場固定 DM Controller」這個 actor。補了 `test_dm_key_holder_who_is_not_the_session_dm_cannot_change_the_stage` 與 `test_dm_key_holder_who_is_not_the_session_dm_cannot_proxy_or_narrate`，後者同時證明該 actor 用自己的 Seat 發言仍然成功，所以拒絕的是桌上權限而不是可達性。
3. **P3-A 留下的兩項 banner 呈現取捨。** 致命錯誤原本同時渲染 generic error banner 與 disconnected banner，敘述同一件事；重新連線中的暫時狀態沿用 `error-banner` 告警樣式。現在 `onFatal` 不再另設 generic error banner，reconnecting 改用新的 `.notice-banner` 加 `role="status"`，fatal 維持 `error-banner` 加 `role="alert"`，`RoomSessionPage.test.ts` 加上對應斷言。

## Boundary

`app.domain.rooms.exploration`、`app.persistence.rooms.exploration*`、`app.api.rooms.exploration` 全部含 `.rooms.` 區段，落在 `test_m03_import_boundary.py` 既有的 `FORBIDDEN_MODULE_RE` 內，standalone 匯入圖不會碰到它們。`test_m03d_schema_parity.py` 的 `FORBIDDEN_MULTIPLAYER_TABLES` 已加入 `session_messages`、`room_stage_images`、`session_stages`，SQLite character track 不會被灌進這三張表。

P3-B 沒有新增 capability flag：Stage 與 Chat 都掛在 P3-A 已有的 `table_runtime` 之下，standalone 該旗標本來就是 false，沒有出現需要單獨開關的新 web-only 能力。

## 已知限制

- **`MAX_BUFFERED_EVENTS` 仍是 200，而 reload 已改成從 cursor 0 重播。** P3-A handoff 要求 P3-B 決定「提高上限或改成分頁載入」。目前的決定是兩者都不做：桌上訊息可回捲的產品需求要等 P3-C 的 roll 與 pending 一起看，現在提高上限只是猜數字。實際行為是長場次 reload 會逐頁跑完整條 durable 歷史，但 reducer 只留最後 200 筆，畫面看不到更早的訊息。correctness 無誤，但長場次的 reload 成本會隨 event 數線性成長，P3-C 必須正面處理。
- **座位變動仍不是桌上的一等事件。** P3-A closeout 把這件事掛在 P3-B 範圍，但 P3-B 實作規格 18 條沒有列，P3-B 也沒有做；event kind 只有 `exploration.*` 與 `stage.updated`。無 Lobby 讀取權的 caller 其座位資訊仍凍結在進入 Session 頁當下。改掛 P3-D，因為 controller 交接本來就是該 Subphase 的主題。
- **waiter starvation 測試仍借真實 `wait_after` 但 stub `list_after`。** P3-A 的原始限制未動；P3-B 沒有改動 wait 路徑，也沒有把它惡化。留給 P3-F 的資源安全整合。
- **Lobby 的 per-Seat access-session N+1 未批次化。** `SeatService.lobby()` 仍逐 Seat 查一次。P3-B 沒有提高 Session 頁對 Lobby 的依賴或輪詢頻率，屬「未惡化」而非「已修復」。
- **PostgreSQL 證據只來自 CI。** 本機未設 `P3_POSTGRES_URL`，`test_p3b_postgres_stage.py` 在本機一律 skip。
- **`RoomSessionPage.tsx` 有三段 P3-A 的說明註解在本 Subphase 被刪除或縮寫**（Lobby 取捨、cursor 由 long-poll runner 擁有、Room credential 識別 Session）。功能無影響，但後人少了那三處的設計理由。沒有在關門時回補，避免把純註解改動混進本次 diff。
- **Stage 圖片存在 DB `LargeBinary`。** 對「最小 Room-scoped upload」夠用，但單張上限 10 MB 且與 event 走同一 transaction，圖片變多時 DB 體積與 dump 成本會直接反映在 Room 上。P3 沒有 asset 生命週期管理（除了 Room cascade），要做要等真的有需求。

## Handoff

P3-B 已完成並關門。下一步是 **P3-C — Roll, Check & PendingAction**。

P3-C 直接繼承以下 substrate，不得再造第二套：

- **`ExplorationActionService` 已經是 actor-neutral 的 typed 入口。** 它只吃 `TableActorContext`，`_human_binding()` 是唯一一處假設 Human 的地方，且已明確標註 P3-D 會換掉。P3-C 的 roll service 照同一形狀寫，不要回頭依賴 `RoomAccessContext`。
- **`/check` 已經有 parser 但刻意沒有 endpoint。** `parseExplorationComposer` 回 `blocked_check`，P3-C 接手時是補上 `RequestCheckService` 與對應路由，不是改 parser 的判斷方式。
- **canonical row 加 event 的原子寫入形狀已定。** `ExplorationMessageRepository.append_message()` 在同一 transaction 內寫 canonical row、event 與 runtime cursor，並共用 P3-A 的 idempotency key 機制。RollRequest 與 RollResult 照這個形狀，不要讓 roll 只活在 event payload 裡。
- **DM proxy 的 acting 與 subject 分離已經是資料層事實。** P3-C 的 proxy roll 沿用 `execution_mode` 加 `acting_seat_id` 加 `subject_seat_id`，不要新增第二套代理標記。
- **前端只有一條 long-poll runner。** Stage、Chat 與之後的 roll 都從 `sessionEventPoll.ts` 的同一條 stream 取得更新。
- **雙語同步交付。** P3-C 的 roll 呈現、pending 狀態與錯誤訊息都是 user-visible copy，依 AGENTS.md 工程實作守則 7 必須在同一個 Subphase 補齊 `zh-TW` 與 `en`。
