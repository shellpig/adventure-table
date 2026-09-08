# P3-A Closeout Checklist

P3-A — Session Table Runtime & Event Stream closeout scope。編號對應 [實作規格](實作規格.md) 的「完成後必須為真」。

- [x] 1. 每個 Session 有自己的 table-runtime namespace。`TableEventRepository._session_scope_row()` 一律以 `(room_id, campaign_id, session_id)` 三段解析 Session，Room A 帶 Room B 的 session id 得到 `TableEventSessionNotFoundPersistenceError`，HTTP 層映射成 404 `session_not_found`，不區分「不存在」與「無權限」。
- [x] 2. 單調遞增且持久化的 event sequence。`append()` 在同一 transaction 內以 `SELECT ... FOR UPDATE` 鎖住 `session_table_runtime` row 後 `last_event_seq + 1`，不使用 `MAX(seq)+1`；`uq_session_events_session_seq` 為 DB 層兜底。`(session_id, idempotency_key)` 唯一，重送同一 key 回傳既有 event 而不配置第二個 seq。
- [x] 3. 四種 visibility 由 Server 過濾。`TableEventVisibility` 提供 `PUBLIC` / `DM_ONLY` / `ACTOR_AND_DM` / `SEAT_PRIVATE`，`TableEventService._visible()` 在 projection 階段套用，前端與 API DTO 都拿不到被過濾掉的 event。
- [x] 4. 猜 id / sequence 不能繞過 visibility。cursor 以 `raw[-1].seq` 跨過整個 bounded window（含 caller 看不到的 event），caller 既無法停在同一個 cursor 空轉，也無法從 `has_more` 或回傳筆數反推隱藏 event 內容。
- [x] 5. 初次 Resume + 後續 incremental feed。`SessionResumeService` 一次帶回 `table_runtime` cursor 與 `recent_events`；`RoomSessionPage` 的 heartbeat 迴圈已移除 `getActiveSession`，改由 `/events/wait` long-poll 更新。`RoomSessionPage.test.ts` 以原始碼斷言鎖住「整份 Resume 只在 mount / explicit reload 呼叫一次」。
- [x] 6. `after_seq` cursor 續接。`GET /events` 與 `GET /events/wait` 都吃 `after`，回傳 `cursor` / `current_seq` / `has_more`；前端 `applySessionEventPage()` 對重疊 page 冪等，reconnect 沿用同一 cursor。cursor 落後時 `has_more` 為真，caller 可持續拉或退回完整 Resume。
- [x] 7. restart 後 order / revision 不倒退。`test_p3a_restart_persistence.py` 對同一份 DB 重建 engine，last seq、runtime revision 與 event history 全部保持。
- [x] 8. write 前重新確認 caller scope。`test_p3a_event_write_authorization.py` 證明 actor 在 append 的同一個 write transaction 內重新驗證，而不是只在 request 入口驗一次。
- [x] 9. wait 走 async path 且不持 DB。`GET /events/wait` 是 `async def`；`TableEventService.wait_after()` 只把短查詢丟 `asyncio.to_thread`，idle 期間 await `asyncio.Event`。所有 room service 由 engine 建構，沒有 request-scoped ORM Session dependency，等待期間不持有 connection / transaction。`ProcessLocalTableEventNotifier` 只負責 wake-up：註冊後立刻做第二次 DB recheck 補 lost wakeup，wake / timeout 後再 recheck，durable cursor 為唯一真實來源。
- [x] 10. idle waiter 不餓死一般 DB 請求。`test_p3a_event_wait.py::test_many_idle_waiters_hold_no_db_connection_and_do_not_starve_db_request` 在 `pool_size=1, max_overflow=0` 下掛 24 個 idle waiter，斷言 `pool.checkedout() == 0`，並讓一般 DB 請求在 0.3 秒內完成。cancellation / timeout 後 waiter registration 與 pool 都回到 baseline。
- [x] 11. 不建立上層產品行為。本 Subphase 沒有 Chat、Stage、Roll、PendingAction 或 AI token；event kind 由 append contract 驗證，未知 kind 被拒。
- [x] 12. 不搬入 P7。沒有跨 Session history search、Snapshot / Restore 或 Timeline UX。
- [x] 13. 高頻同步不放大既有 N+1。**Resume 側已解除**：新增 `SessionResumeRepository.load_character_summaries()`，Active Character summary 由逐隻 load 改為單次批次查詢，`test_p3a_session_resume.py` 有對應斷言。**Lobby 側未動**：`SeatService.lobby()` 仍對每個 Human-controlled Seat 各查一次 access session。P3-A 沒有放大它——Session 頁的 Lobby 輪詢頻率不變，新的 event feed 是獨立 long-poll，且整份 Resume 已從 heartbeat 移除，Session 頁每輪心跳的查詢量淨減少。詳見「已知限制」。
- [x] 14. Standalone 同能力維持 false。`build_capabilities()` 的 `table_runtime` 只在 `channel == "web"` 為真；`test_m03e_capabilities.py`、`test_p2c_capabilities.py` 與前端 `CAPABILITY_KEYS` fixture 同步更新。`test_m03_import_boundary.py` 的 `FORBIDDEN_MODULE_RE` 已加入 `table_runtime` / `table_events`，並補上對應的 negative fixture。

## Verification evidence

分支 `p3-a-session-table-runtime-event-stream`，最終 SHA `96b54e6`。

```text
Branch / final SHA
  p3-a-session-table-runtime-event-stream @ 96b54e6

Alembic heads（以 alembic branches / heads 實測）
  0008_m03c_import_records (branchpoint)
    -> 0009_p2a_character_head (character)
    -> 0010_p2a_web_rooms (web)
  0015_character_state_revision (character) (head)
  0016_p3a_table_runtime_events (web) (head)
  0016 接在 0014_p2e_sessions 之後，落在 web track，不觸及 character track。

Backend pytest（全套）
  1149 passed / 15 skipped，exit 0
  cwd apps/server，直譯器 ..\..\.venv\Scripts\python.exe
  執行於 bda8ffa；bda8ffa..96b54e6 只動 apps/web 與刪除一支一次性 workflow，
  backend 產品碼與測試零改動，故未重跑全套。

Focused P3-A backend（執行於 96b54e6）
  tests/test_p3a_table_events.py 4
  tests/test_p3a_event_api.py 2
  tests/test_p3a_event_wait.py 4
  tests/test_p3a_event_write_authorization.py 1
  tests/test_p3a_session_resume.py 2
  tests/test_p3_workflow_contract.py 4
  tests/test_p3a_postgres_events.py 3（本機 skip，見下）
  合計 18 passed / 3 skipped

Workflow contract + standalone boundary（執行於 96b54e6）
  tests/test_p3_workflow_contract.py + tests/test_p2a_workflow_contract.py
  + tests/test_m03_import_boundary.py：12 passed

PostgreSQL concurrency / migration gate
  tests/test_p3a_postgres_events.py 3 tests
  本機無 P3_POSTGRES_URL 而 skip；證據取自 P3 Non-E2E 的 postgres-migrations job。
  覆蓋：並發 append 配置唯一且單調的 seq、既有 P2 Session backfill runtime=0、
  migration 產出的 JSONB payload 型別與 metadata 一致。

Private-recipient query strategy
  採 開發設計方針 §14 第二種策略：bounded (session_id, seq) window + Server projection。
  TableEventRepository.list_after() 以 MAX_EVENT_SCAN_LIMIT 夾住 scan_limit 並 .limit()，
  Index ix_session_events_session_seq (session_id, seq)。
  不使用 JSONB/ARRAY membership predicate，故不需要 GIN。
  window 有硬 limit 的證據：test_event_sequence_idempotency_cursor_and_bounded_scan。

Event wait async / no-DB-hold / starvation
  tests/test_p3a_event_wait.py 4 tests
  含 notify 喚醒後 DB recheck 為準、故意遺失 process-local notify 仍由 DB cursor 補到、
  24 waiter vs pool_size=1 不餓死、cancellation 清理 registration 與 timer。

Frontend unit（執行於 96b54e6）
  50 files / 235 tests passed
  含 sessionEventStream.test.ts（cursor reducer）、sessionEventPoll.test.ts（reconnect）、
  sessionsP3a.test.ts（API client）、RoomSessionPage.test.ts（seat merge、連線狀態雙語）

TypeScript / build
  npm run build（tsc --noEmit && vite build）exit 0，執行於 96b54e6

docker compose config
  exit 0，執行於 bda8ffa；至 96b54e6 docker-compose.yml 未變動

P3 Non-E2E
  workflow .github/workflows/p3-non-e2e.yml，Display name「P3 Non-E2E」
  jobs：backend / frontend / postgres-migrations / windows-standalone
  run 34248269253 @ b9649a9，四個 job 全 success
  run 34291341436 @ 96b54e6，workflow_dispatch 補跑 branch tip，四個 job 全 success
  （96b54e6 帶 [skip ci]，內容只有刪除一次性 workflow 檔；補跑是為了讓
    「exact SHA 綠」這條 closeout evidence 直接落在 final SHA 上。）

Session lifecycle E2E
  run 34248269818 @ b9649a9，workflow「P3-A Handoff E2E」success
  透過 npm run test:e2e:docker 執行 e2e/p2f-session-lifecycle.spec.ts
  該 workflow 為本次 handoff 的一次性 gate，證據留存後已於 96b54e6 移除，
  run 紀錄仍保留在 Actions history。
```

## 關門過程中修正的問題

驗證期間發現 3 項，2 項已修並重新驗證，1 項判定為誤報後收回。

1. **Session 頁的座位標籤會被開場快照永久凍住（已修，`351a07f`）。** P3-A 把 `getActiveSession` 從 heartbeat 移除以符合 開發設計方針 §14「Lobby heartbeat 與 Session event feed 分離」，但 `mergeSessionSeatTruth(lobbySeats, resumeSeats)` 是後者覆蓋前者。改動後 `resumeSeats` 只在 mount / explicit reload 更新，`lobby.seats` 仍隨 heartbeat 更新，於是掛載當下的 Resume 快照會永久壓住之後刷新的 Lobby 資料——Session 進行中改座位 label，已在畫面上的人要重新整理才看得到。已反轉合併優先序：以 Resume seats 建 base、Lobby seats 覆蓋。該函式原本的用途是聯集（Lobby 不再列出的已封存座位由 Resume 補 label），此行為與對應斷言原封保留。

2. **event long-poll 遇到任何錯誤就永久終止（已修，`b8a11a7`）。** 原迴圈的 `catch` 除 `AbortError` 外一律 `setError` 後 `return`，不再重啟。任何暫時性失敗（Wi-Fi 換手、行動裝置喚醒、server 短暫重啟、單次 5xx）都會讓該分頁永久停止接收桌上 event，而錯誤 banner 會被後續狀態更新蓋掉，使用者無從察覺，只能重新整理。P3-A 尚無 in-session 玩法面，可觀察影響有限，但 P3-B 交付 Chat 後即為「別人發言收不到且畫面沒有異常提示」。已抽出 `sessionEventPoll.ts`：1 秒起、每次翻倍、上限 30 秒的 backoff，成功後歸零；`SessionApiError` 403 / 404 判定為致命並終止；`AbortError` 與 effect cleanup 為正常終止且清掉 timer；重連沿用同一 cursor，不退回完整 Resume。連線狀態改為常駐 banner（`data-session-event-connection`），`eventReconnecting` / `eventDisconnected` 兩種 locale 同步交付。

3. **「DM 會因 access session 輪替而失去控制項」判定為誤報。** 初次 review 認為 `callerAccessSessionId` 不再隨 heartbeat 更新會讓 `isCurrentDm` 變 stale。追查 `RoomAccessService` 後確認：access session 由 localStorage 中的 token hash 解析，heartbeat 只做 `touch_access_session()`，不 rotate、不重建；被撤銷時走 `RoomAccessRevokedError` 顯性報錯而非靜默改變。該 id 在頁面存活期間為常數，不需隨 heartbeat 更新。

## Boundary

- P3-A 只交付 substrate。沒有 Chat / Stage / Action、沒有 Roll / PendingAction、沒有 AI controller 或 Join Token。
- 沒有 P7 的 Timeline UX、跨 Session history search、Snapshot / Restore。
- `TableEventService.resolve_human_actor()` 是 P3-A 的過渡 adapter；P3-D 會用共用的 Human / AI actor resolver 取代它，projection service 介面不變。它刻意不以 `RoomAccessAuthority` 授予 gameplay scope——Room Owner 若不是本場 participant，不會因為 authority 高就看得到 event。
- `0016_p3a_table_runtime_events` 落在 web track。standalone 只升 `character@head`，不會長出 `session_table_runtime` / `session_events`。
- `app.standalone` 與 `app.content.*` / `app.domain.character*` 不得觸及 `app.*.rooms`、`table_runtime` 或 `table_events`；由 `test_m03_import_boundary.py` 的 forbidden regex 把關。
- P3-A 不改 Character Build / State / Version / StableKey / Builder provenance / Character JSON，故不觸發 M01 的 standalone compatibility review 條款。

## 已知限制

- **Lobby 的 per-Seat access-session N+1 未解。** `SeatService.lobby()` 對每個 Human-controlled Seat 各呼叫一次 `get_access_session()`，而 Session 頁仍以 heartbeat 週期輪詢 Lobby。P3-A 沒有放大它（輪詢頻率不變，且整份 Resume 已從 heartbeat 移除，淨查詢量下降），但 P3-B 若讓 Session 頁依賴更多 Lobby 衍生資料或提高其頻率，必須先批次化這條路徑。實作規格 13 的 Resume 側已解除並有測試證據，Lobby 側只是未被惡化，不是已修復。
- **starvation 測試借用真實 `wait_after` 但 stub 掉 `list_after`。** `_DbBackedWaitService` 以 `wait_after = TableEventService.wait_after` 直接複用產品碼的等待編排，但 `list_after` 是測試替身。因此「idle 期間零 DB checkout」的證據涵蓋 orchestration 層，不涵蓋真實 endpoint 路徑（含 `run_in_threadpool` 的 actor resolution）。真實路徑的 DB 使用由 `test_p3a_event_api.py` 的 HTTP 測試覆蓋，但兩者未合成單一端到端資源斷言。
- **致命錯誤時畫面會同時出現兩則 banner。** `onFatal` 設定 `error`，`onStatus('fatal')` 另外渲染 disconnected banner，兩者敘述同一件事。功能無誤，屬呈現冗餘。
- **重連中的 banner 沿用 `error-banner` 樣式。** 重新連線是暫時狀態而非錯誤，用告警樣式在跑團中容易被誤讀成故障。
- **座位變動的即時同步仍是顯示層權宜。** 上述修正只讓「看得到 Lobby 的 caller」恢復隨心跳更新；`optionalLobby()` 回 `null` 的 caller（無 Lobby 讀取權）其座位資訊仍凍結在 mount 當下。座位變動要成為桌上的一等事件，屬 P3-B 範圍。
- **PostgreSQL 證據只來自 CI。** 本機未設 `P3_POSTGRES_URL`，`test_p3a_postgres_events.py` 在本機一律 skip；並發、backfill 與 JSONB parity 三條證據取自 P3 Non-E2E 的 `postgres-migrations` job，未另做本機 dedicated DB 覆跑。
- **E2E 證據來自一支已移除的一次性 workflow。** `p3a-handoff-e2e.yml` 為本次 handoff 建立、跑完即刪；證據以 run 34248269818 保存在 Actions history，repo 內不再有對應檔案。P3-F 會建立常駐的 `p3-e2e.yml`。
- **KI-P1D-001 未解。** `m01e` / `m01m` 兩支 Builder Draft 存檔競態仍是真逾時而非假通過，根因未確認。P3-A 未觸及 Builder，不影響本次證據，但會持續影響後續每一次 Subphase 關門。

## Handoff

P3-A 已完成並關門。下一步是 **P3-B — Exploration, Chat & Actions**。

P3-B 直接繼承以下 substrate，不得再造第二套：

- **`TableEventService.append()` 是唯一的 event 寫入口。** Chat message、Action、Whisper、Narration 一律成為 `session_events` 的 row，不另開 message table。seq 配置、idempotency、ended-session 拒絕與 transaction 內 actor 重驗都已在這條路徑上，繞過等於同時繞過四項契約。
- **`TableEventVisibility` 四種 audience 已足夠 P3-B。** Whisper DM 用 `SEAT_PRIVATE` + `recipient_seat_ids`，DM-only narration 用 `DM_ONLY`，一般 Dialogue / Action 用 `PUBLIC`。不要為了 Chat 新增第五種 visibility，除非產品規格真的需要。
- **bounded window 的取捨在 P3-B 會開始有感。** 目前是「取固定筆數的 seq window，再由 Server 過濾」。桌上出現大量 private event（例如 DM 與單一 Player 的長串 whisper）時，其他 caller 會連續收到幾乎全被過濾光的 page。correctness 無誤（cursor 照樣前進），但每頁有效載荷會下降。若 P3-B 實測到這個形狀，再依 開發設計方針 §14 改採 recipient relation table + index，而不是把 window 無限放大。
- **`sessionEventPoll.ts` 是唯一的前端 long-poll runner。** P3-B 的 Stage 與 Chat 都從同一條 event stream 取得更新，不要為新畫面另寫一個輪詢迴圈。新增的致命錯誤條件加進 `isFatalSessionEventError()`，不要在呼叫端各自判斷。
- **`sessionEventStream.ts` 的 reducer 已保證冪等與 seq 排序**，`MAX_BUFFERED_EVENTS` 目前為 200。P3-B 讓訊息可回捲時要決定是提高上限還是改成分頁載入，並同步調整 reducer 測試。
- **`resolve_human_actor()` 會在 P3-D 被取代。** P3-B 新增的 application service 請透過 `TableActorContext` 取得身分，不要直接依賴 `RoomAccessContext`，否則 P3-D 換 resolver 時要改的地方會擴散。

其他必須同步處理的事項：

- **import boundary 的命名 gate。** P3-B 新增多人層 module（Stage、asset、chat 等）時，必須確認 `test_m03_import_boundary.py` 的 `FORBIDDEN_MODULE_RE` 涵蓋新命名，否則 gate 會靜默放行。P3-B 引入 Room-scoped asset 時尤其要檢查，`asset` 這類通用名詞不在目前的 regex 內。
- **capability flag。** P3-B 若新增 web-only 能力，比照 `table_runtime` 在 `build_capabilities()` 與前端 `CAPABILITY_KEYS` 同步加入，並確認 standalone 為 false。
- **雙語同步交付。** P3-B 的 Stage / Chat / slash command 錯誤訊息屬 user-visible copy，依 AGENTS.md 工程實作守則 7 必須在同一個 Subphase 補齊 `zh-TW` 與 `en`。測試指南要求 P3 Session page 納入 hardcoded copy scan。
- **backend-dependent E2E 的 stale image trap。** `npm run test:e2e:docker` 只 rebuild `web`。P3-B 是 P3 第一個有 backend-dependent E2E 的 Subphase，依 PROJECT_BRIEF 的未結清事項，必須在此收斂這個 trap（讓 wrapper 一併 rebuild server，或加上顯式 gate），不要繼續當成操作者責任。
