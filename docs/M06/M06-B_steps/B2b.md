# B2b — MCP 端到端：真實寫入工具與 wait_for_event

## Scope

- 新 `apps/server/tests/test_m06b_mcp_echo_integration.py`（B2a 的 service 層測試以 `append_event` 模擬；本步改用真實 domain service／MCP facade 寫入，證明實際 call site 都有蓋章、白名單前提成立）。
- B.1：AI DM 經真實路徑 `set_stage_text`、`post_narration`、`world_create_entry`、`world_set_current_context`、非戰鬥 `request_check` 後 `wait_for_event` → `events == []`、cursor＝最後一筆 echo；Player dialogue 後再 wait 只回該 dialogue。
- B.3：AI DM 經 MCP 開始 Quick Combat、推進回合 → `combat.*` 與戰鬥中 `roll.requested` 照送。
- B.4：同 B.1 流程 `include_own=true` → 全部 echo。
- B.5：同範圍 `get_pending_events` 全部 echo；Human `/events` 含 AI DM 寫入。
- B.7：`OWN_ECHO_EVENT_KINDS` 中由 MCP tool 產生的種類，參數化斷言工具回傳包含事件 payload 的全部鍵值資訊。
- B.9：Player 的 `wait_for_event` 不因抑制多拿 `dm_only`／`seat_private`；MCP 回傳的事件 JSON 不含蓋章欄位。
- 契約：`實作規格.md` B.1～B.5；`開發設計方針.md` §4.2、§4.5；`測試指南.md` B.1～B.5、B.7、B.9。
- 不動 production 程式；若發現某寫入路徑沒蓋章或白名單前提不成立，回報而不自行改 production。

## 前置

- B2a 已 commit。

## 驗收

- 新模組＋P3-E／P4-E／P6 MCP 回歸（見 prompt）全綠。

## 紀錄

- **起始**：2026-09-25，worker agy（`Gemini 3.8 Flash (High)`），1 回合 23 分鐘（前 10 分鐘讀檔無改動，未判死），prompt `C:/_work/AI_Work/Tools/agy-runs/agy-m06b-B2b.prompt.txt`，conversation `604f3449-ff56-4485-859f-280c4229a3c0`
- **交付**：`tests/test_m06b_mcp_echo_integration.py`：以 production `get_ai_tool_application_service` 組出的真實 facade，經 HTTP `/mcp`（minted AI DM／AI Player token）與 Human REST 走完 7 個測試、23 個 case——B.1 DM 五種寫入不喚醒且 cursor＝5、Human dialogue 喚醒；B.4 `include_own`；B.5 `get_pending_events`＋Human `/events`；B.2 AI Player／Human／Human 擲骰結果喚醒；B.3 Quick Combat（建敵、開戰、先攻、推進回合）事件照送；B.9 Player 不拿 dm_only、兩種 actor 的事件 JSON 無蓋章鍵；B.7 對 17 個由工具產生的白名單種類參數化斷言工具回傳包含事件 payload 的關鍵值。無 xfail、無 production gap。
- **指揮者審核修正**：
  - **跨測試污染**：fixture 只手列 32 個 `app.state` 快取鍵清除，漏了 `room_service`（Human token 查詢）等，全套 xdist 下同 worker 前一測試留下的 service 指向別的 engine → `no such table: room_access_sessions`；模組單跑不會出現。改為依後綴（`_service`／`_repository`／`_notifier`／`_engine`／`_throttle`）清除全部快取。
  - fixture 結束原本 `dependency_overrides.clear()` 會清掉他人的 override，改為保存後還原。
  - 刪掉與參數列表逐字重複的 `ids=`。
  - 已知寬鬆處（接受）：B.7 以「payload 關鍵鍵的值出現在工具回傳某處」比對（`_value_in_data`），不是逐鍵路徑對照；足以證明「不因略過 echo 而漏資訊」。
- **測試**：全套 backend 連跑兩次 exit 0，2602 passed；模組單跑約 4 秒。
- **未解問題／下一步**：B3（文字，由指揮者做）。
