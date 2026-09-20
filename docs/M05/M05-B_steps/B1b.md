# B1b — backend：前一場定位與 `GET /sessions/{id}/previous`

## Scope

- `persistence/rooms/sessions.py`：`previous_for_campaign()`（§4.1）。
- `domain/rooms/sessions.py`：`SessionHistoryLink`、`SessionService.previous_session()`，授權走 `event_service.resolve_history_scope`（§4.3）。
- `api/rooms/sessions.py`：`GET /sessions/{session_id}/previous`（§4.4）。
- `tests/test_m05b_session_history_link.py`：B.1 五個測試＋B.5 `test_resume_recent_events_and_mcp_context_stay_single_session`。

## 前置

- B1a 已 commit。

## 紀錄

（待補）
