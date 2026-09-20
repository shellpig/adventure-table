# B1b — backend：前一場定位與 `GET /sessions/{id}/previous`

## Scope

- `persistence/rooms/sessions.py`：`previous_for_campaign()`（§4.1）。
- `domain/rooms/sessions.py`：`SessionHistoryLink`、`SessionService.previous_session()`，授權走 `event_service.resolve_history_scope`（§4.3）。
- `api/rooms/sessions.py`：`GET /sessions/{session_id}/previous`（§4.4）。
- `tests/test_m05b_session_history_link.py`：B.1 五個測試＋B.5 `test_resume_recent_events_and_mcp_context_stay_single_session`。

## 前置

- B1a 已 commit。

## 紀錄

- **起始**：2026-09-20，worker agy（`Gemini 3.8 Flash (High)`），1 回合 4.8 分鐘，prompt `C:/_work/AI_Work/Tools/agy-runs/agy-m05b-B1b.prompt.txt`，conversation `5835bf92-f172-49b0-99fd-113fd487e498`
- **交付**：`SessionRepository.previous_for_campaign()`（`(started_at, id)` tuple 比較、任何 status）；`SessionHistoryLink`、`SessionService.previous_session()`（授權走 `resolve_history_scope`，`TableEventNotFoundError` → `SessionNotFoundError` → 404）；`GET /sessions/{session_id}/previous`；`test_m05b_session_history_link.py` 6 個測試，fixture 沿用 `test_m05b_history_reader_scope.py`（跨模組 import 為既有慣例）。
- **指揮者審核修正**：無；diff 與 §4.1／§4.3／§4.4 一致，無防禦式寫法、無鬆散 status 斷言。
- **測試**：`pytest tests/test_m05b_*.py tests/test_p2e_session_*.py tests/test_p3a_*.py tests/test_p3c_resume_projection.py tests/test_m05a_owner_end_ai_dm.py tests/test_code_quality_gate.py` exit 0；focused 6 passed。
- **未解問題／下一步**：B.5 的 MCP 單場斷言落在 `ai_tools.get_session_context` 使用的 domain 呼叫（`list_before(actor_s2, ...)`），未經 MCP HTTP；B3 E2E 不補此點，屬可接受。下一步 B2a。
