# M06-A — wait_for_event Timeout Cap Alignment · Closeout

日期：2026-09-25　Branch：`feat/m06a-wait-timeout-cap`　Worker：agy（A1）、指揮者（A2）

## 驗收對應

| 契約 | 證據 |
|---|---|
| A.1 MCP 等待可達 120 秒 | `tests/test_m06a_wait_timeout_cap.py::test_mcp_wait_for_event_passes_full_timeout_to_notifier`（120→notifier 收到 120）、`::test_mcp_wait_for_event_passes_shorter_timeout_unchanged`（90→90） |
| A.2 上限只有一個來源 | `::test_wait_cap_single_source`（`WaitEventsInput.timeout` 的 `le`、`ai_guidance.WAIT_TIMEOUT_SECONDS`、`wait_for_event` 傳給 `wait_after` 的 `max_timeout` 皆等於 `WAIT_EVENT_MAX_TIMEOUT_SECONDS`）、`::test_guide_and_briefing_show_cap_seconds`（guide en／zh-TW 與 briefing） |
| A.3 人類 long-poll 不變 | `::test_wait_after_default_cap_is_sixty`、`::test_human_events_wait_uses_sixty_second_cap`（真 HTTP route，notifier 收到 60）、`::test_human_events_wait_rejects_timeout_above_sixty`（61→422） |
| A.4 回歸 | `test_m04b_wait_timeout_cap.py`、`test_m04c_briefing.py`、`test_m04c_mcp_guide.py`、`test_p3e_*.py` 斷言未改；`test_p3e_mcp_event_loop.py` 的 `_WaitEventService` stub 只補 `max_timeout` 簽名 |

## 關門 gate

- 全套 backend pytest（cwd `apps/server`）：exit 0，2563 passed／78 skipped。
- `docker compose config`：通過。
- E2E：M06-A 為 backend-only，依 `測試指南.md` §1.1 不跑。
- 合併回 `main`：M06-B、M06-C 疊在本 branch 上實作；依 P6-F／P6-G 前例，M06-C 關門後在最上層 branch 跑一次全套 Docker E2E，涵蓋 A～C，再依序合併 A → B → C。

## 指揮者審核修正摘要

- A1：刪掉 `wait_for_event` 中為遷就 test stub 而加的 `try/except TypeError` 回退（production 防禦式寫法），改補 stub 簽名；刪掉測試 helper 沒人用的參數。

## 契約變更

- 2026-09-25 使用者拍板 M06-C C.1：精簡投影只移除骰子細節鍵，保留 Combat 鍵（commit `99e4d916`，三份文件同步）。
