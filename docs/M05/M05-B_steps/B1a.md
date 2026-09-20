# B1a — backend：history read scope 與 `/events/history` 分流

## Scope

- `persistence/rooms/table_runtime.py`：`StoredHistoryReadScope`、`TableEventRepository.history_read_scope()`（§4.2）；既有 actor 解析零改動。
- `domain/rooms/table_events.py`：`HistoricalSessionReadScope`、`EventReadScope` Protocol（`_visible`／`_present` 參數型別放寬）、`resolve_history_scope()`、`list_history_before()`，與 `list_before` 共用一個回掃 helper（§4.2a）。
- `api/rooms/table_events.py`：`list_table_event_history` 分流（§4.4）。
- `tests/test_m05b_history_reader_scope.py`：B.2、B.3 全部 11 個測試。

## 前置

- 無程式依賴；fixture 沿用 `test_m05a_owner_end_ai_dm.py` 的種子 helper 形狀。

## 驗收

- `pytest tests/test_m05b_history_reader_scope.py tests/test_p3a_*.py tests/test_p3d_table_actor_binding.py tests/test_m05a_owner_end_ai_dm.py tests/test_code_quality_gate.py`（cwd `apps/server`）全綠且既有測試零修改。

## 紀錄

- **起始**：2026-09-20，worker agy（`Gemini 3.8 Flash (High)`），1 回合 16 分鐘，prompt `C:/_work/AI_Work/Tools/agy-runs/agy-m05b-B1a.prompt.txt`，conversation `ad6b42ca-b793-4b11-8c66-442dce941044`
- **交付**：`StoredHistoryReadScope`＋`TableEventRepository.history_read_scope()`；`EventReadScope` Protocol、`HistoricalSessionReadScope`、`resolve_history_scope()`、`list_history_before()`、`_scan_before()`（`list_before` 改為薄包裝）；`list_table_event_history` 分流；`test_m05b_history_reader_scope.py` 11 個測試（含 s2 真實 Quick Combat＋Monster、s1 四種 visibility 事件）。
- **指揮者審核修正**：
  - route 裡 `try: service.resolve_history_scope except AttributeError: 走舊路徑` 是為了讓 `test_p3a_event_api.py` 的 stub service 過而寫的防禦分支——刪除，改在該測試 stub 加 `resolve_history_scope`（回 active scope），既有斷言零改動。
  - stored↔model 三處逐欄轉換改為 `HistoricalSessionReadScope(**asdict(stored))`／`StoredHistoryReadScope(**scope.model_dump())`。
  - 測試 10 的 `.get()` 迴圈可能空轉，改為明確斷言恰有 1 個 hostile combatant 且 projection 無 `current_hp`／`max_hp`；Combat mutation 的期待收斂為 `{403, 409}`（排除 404，證明 route 存在且被授權層擋）。
- **測試**：`pytest tests/test_m05b_history_reader_scope.py tests/test_p3a_*.py tests/test_p3d_table_actor_binding.py tests/test_m05a_owner_end_ai_dm.py tests/test_code_quality_gate.py` exit 0；focused 11 passed。既有測試除 P3-A API stub 新增方法外零改動。
- **未解問題／下一步**：無；B1b。
