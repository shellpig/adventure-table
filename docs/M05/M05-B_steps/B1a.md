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

- **起始**：2026-09-20，worker agy，prompt `C:/_work/AI_Work/Tools/agy-runs/agy-m05b-B1a.prompt.txt`
- **交付**：（待補）
- **指揮者審核修正**：（待補）
- **測試**：（待補）
- **未解問題／下一步**：（待補）
