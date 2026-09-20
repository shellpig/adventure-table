# M05-B — Cross-Session Chat History Paging · Closeout

日期：2026-09-20　Branch：`feat/m05b-cross-session-history`　Worker：agy（B1a、B1b、B2a）、指揮者（B2b、B3）

## 驗收對應

| 契約 | 證據 |
|---|---|
| B.1 前一場可定位；權限＝history scope；跨 Campaign／Room／無 scope 404 | `tests/test_m05b_session_history_link.py::test_previous_session_returns_latest_earlier_session_any_status`、`::test_previous_session_orders_by_started_at_then_id`、`::test_previous_session_rejects_cross_campaign_and_cross_room`、`::test_previous_session_requires_history_scope_returns_404`、`::test_previous_session_allows_seat_holder_not_in_base_session` |
| B.2 已結束 Session 事件可讀且以 Seat 過濾；DM 層跟 `dm_seat_id`；未參加 Seat 讀 public；archive／reassign 重算；active 路徑不變 | `tests/test_m05b_history_reader_scope.py` 測試 1～8；E2E Kael／Mira／DM 三視角 |
| B.3 舊 Session 唯讀；history scope 不給任何 gameplay 能力 | `::test_ended_session_rejects_writes_for_history_reader`（含 Combat mutation）、`::test_history_scope_does_not_grant_combat_detail_on_old_session_url`、`::test_history_scope_does_not_grant_stage_roll_pending_reads_on_old_session_url` |
| B.4 聊天串向上翻越過邊界；一步一頁；分隔線；空場；已到最前；chain reset | `sessionEventStream.test.ts`（hasOlderHistory 四情境、pushOlderSession、applyOlderSessionPage、nextHistoryRequest 含連續空場）；`RoomSessionPage.test.ts` "M05-B: pages older chat…"；`SessionTableSurface.test.tsx` "cross-Session history" ×3；E2E |
| B.5 其他投影不受影響；Resume／MCP 單場 | `SessionTableSurface.test.tsx` "keeps Stage and other projections on the current Session only"；`test_m05b_session_history_link.py::test_resume_recent_events_and_mcp_context_stay_single_session`；E2E Stage 斷言 |
| B.6 雙語 | `SessionTableSurface.test.tsx` 分隔線兩 locale；copy key 五個兩 locale |
| B.7 E2E B 段 | `m05-session-history.spec.ts`：DM 翻頁到分隔線（status／DM: AI）＋AI narration＋DM 層 Check prompt → 已到最前；Kael 看不到 Mira 的 seat-private prompt；Mira 看得到 |

## 關門 gate

- 全套 backend pytest（cwd `apps/server`）：exit 0。
- `npm test -- --run`：90 files／529 passed；`npm run build`：成功。
- `docker compose config`：通過。
- 全套 Docker E2E（`ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1 npm run test:e2e:docker`）：`parallel` 兩輪各 1／2 個 Character Builder spec flake（p1g；m01e＋p1f），單跑皆通過（1 passed；5 passed），其餘 94／93 passed、3 skipped；`baseline-room` 30 passed／1 skipped；`serial-restart` 1 passed。xge-less `m03c` 子集未重跑（M05 不碰 content pack；當日 M05-A merge gate 7 passed）。Builder flake 為既有 KI（Builder 等待），與 M05 無關。

## 指揮者審核修正摘要

- B1a：agy 在 route 加了 `try: service.resolve_history_scope except AttributeError` 回退分支以遷就 `test_p3a_event_api.py` 的 stub——刪除，改在 stub 新增 `resolve_history_scope`；stored↔model 轉換收斂為 `asdict`／`model_dump`；測試 10 的 `.get()` 空轉迴圈改為明確斷言。
- B1b、B2a：零修正。
- B2b、B3：指揮者實作。

## 契約文字與實作的差異（建議 verifier 同步 `開發設計方針.md` §4.5）

- 實作多了 `emptyHistoryChain()`、`pushOlderSession()`、`nextHistoryRequest()` 三個 helper（§4.5 只列 `applyOlderSessionPage`／`hasOlderHistory`）；語意與 §4.6 一致，只是把決策抽成純函式。

## 觀察到但不屬 M05-B 的事項（建議登記 `已知問題.md`）

1. 沿用 M05-A closeout 兩項：Owner 無 Seat 時 Session 頁顯示「Session not found.」；`p2f-session-lifecycle.spec.ts` 隱性順序依賴。
2. `request_check` 要求目標 Seat 有 active Character（`rolls.py` 第 338 行附近）——合理，但 MCP 錯誤訊息未指明缺 Character，AI DM 只看到 `isError`。
