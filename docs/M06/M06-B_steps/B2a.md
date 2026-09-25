# B2a — domain：own echo 判斷、`list_after`／`wait_after` 抑制與 MCP 接線

## Scope

- `apps/server/app/domain/rooms/table_events.py`：`OWN_ECHO_EVENT_KINDS`（`開發設計方針.md` §4.2 原樣）、`TableEventService._is_own_echo`（§4.3）、`list_after(..., suppress_own=False)`（可見性過濾之後移除 own echo，cursor 以掃描到的最後 seq 計）、`wait_after(..., suppress_own=False)`（`suppress_own=False` 時行為與 M06-A 後完全相同；`True` 時以 deadline 迴圈：有事件回傳、只有 own echo 則推進 cursor 立即重掃、沒有新 seq 才在剩餘時間內等 notifier；每輪等待前註冊新 handle 再重掃，避免漏喚醒與已 set 的 Event 造成忙迴圈）。
- `apps/server/app/domain/rooms/ai_tools.py`：`WaitEventsInput.include_own: bool = False`；`wait_for_event` 傳 `suppress_own=not input.include_own`；`get_pending_events` 不變。
- Human route 不傳 `suppress_own`。
- 測試加進 `apps/server/tests/test_m06b_own_echo_suppression.py`（沿用 `create_m06b_fixture`）：service 層以 `append_event`／`repository.append(expected_actor_binding=...)` 模擬各種事件，驗證 B.1、B.2、B.3、B.4、B.5（`list_after` 預設不抑制）、B.6（換 controller、真人、NULL 舊事件），以及 wait 迴圈的時序行為（真 `ProcessLocalTableEventNotifier`、短 timeout）。
- 契約：`實作規格.md` B.1～B.6；`開發設計方針.md` §4.2～§4.5；`測試指南.md` B.1～B.6。

## 前置

- B1 已 commit（`StoredTableEvent` 帶蓋章欄位）。

## 驗收

- focused＋P3-A／P3-E／M06-A 回歸（見 prompt）全綠。

## 紀錄

- **起始**：2026-09-25，worker agy（`Gemini 3.8 Flash (High)`），1 回合 13 分鐘，prompt `C:/_work/AI_Work/Tools/agy-runs/agy-m06b-B2a.prompt.txt`，conversation `72a0d685-0d35-473c-b16f-d479657e033b`。agy 在「等 pytest 跑完」時結束，沒有最終報告（§3.1 已知模式）。
- **交付**：`OWN_ECHO_EVENT_KINDS`、`TableEventService._is_own_echo`、`list_after(suppress_own=)`、`wait_after(suppress_own=)`、`WaitEventsInput.include_own`；`test_m06b_own_echo_suppression.py` 新增 11 個 service 層測試＋`_regrant_dm_seat` helper，`create_m06b_fixture(notifier=)`。
- **指揮者審核修正**：
  - agy 在 `ai_tools.wait_for_event` 與 `wait_after` 內用 `inspect.signature(...).parameters` 偵測 `suppress_own` 再分支，只為讓 M06-A 測試 stub 不壞（與 A1 的 `except TypeError` 同型）——刪除，改為 M06-A 測試的 stub／spy 補 `suppress_own` 參數。
  - `wait_after` 抑制迴圈重寫：agy 版以 `waited` 旗標讓第一次等待用完整 timeout、之後才看 deadline，剩餘時間計算錯誤且流程重複。改為單一 deadline 迴圈：有事件回傳 → 只有 own echo 則推進 cursor 立即重掃 → 每輪註冊新 handle、重掃一次防漏喚醒 → `notifier.wait` 逾時即最後掃一次回傳；無 notifier 時 sleep 到 deadline 再掃。`suppress_own=False` 路徑維持原程式碼。
  - M06-A 兩個測試改為 `pytest.approx(…, abs=1.0)`：預設 wait 現在走抑制迴圈，傳給 notifier 的是 deadline 剩餘時間。
  - 測試抽 `_append()` helper 取代 23 段重複 `append_event(TableEventAppend(...))`；刪掉沒斷言的 `recorded_max_timeouts`。
- **測試**：focused `test_m06b_own_echo_suppression.py test_m06a_wait_timeout_cap.py test_p3e_mcp_event_loop.py test_p3e_mcp_tools.py test_p3e_ai_event_projection.py test_p3a_table_events.py test_p3a_event_api.py test_code_quality_gate.py` 全綠；全套 backend exit 0，2579 passed。
- **未解問題／下一步**：B2b（經真實 MCP 寫入工具的端到端測試）。
