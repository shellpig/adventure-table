# M05-A — Owner End for AI DM Sessions · Closeout

日期：2026-09-20　Branch：`feat/m05a-owner-end-ai-dm`　Worker：agy（A1）、指揮者（A2、A3）

## 驗收對應

| 契約 | 證據 |
|---|---|
| A.1 Owner End AI DM Session 成功 | `tests/test_m05a_owner_end_ai_dm.py::test_owner_end_ai_dm_session_finalizes_and_revokes_atomically`、`::test_owner_end_ai_dm_via_service_matches_owner_abandon_side_effects`；E2E `m05-session-history.spec.ts` |
| A.2 Owner End Human DM Session 被拒 | `::test_owner_end_human_dm_session_rejected_without_side_effects`、`::test_owner_who_is_current_human_dm_ends_via_dm_branch` |
| A.3 非 Owner End AI DM Session 被拒；舊 AI token 被拒 | `::test_dm_key_holder_cannot_end_ai_dm_session`、`::test_member_cannot_end_ai_dm_session`、`::test_ai_dm_binding_rejected_after_owner_end`；E2E 中 End 後 `get_session_context` 401／403 |
| A.4 End 後 Lobby 可指派真人 DM 並 Start；Character State 不變 | `::test_after_owner_end_lobby_can_assign_human_dm_and_start`、`::test_owner_end_does_not_change_character_state`；E2E 全流程 |
| A.5 UI（Owner／AI DM 見 End＋Abandon；Owner／Human DM 只見 Abandon；雙語 copy） | `RoomSessionPage.test.ts` "M05-A: offers the Owner End and Abandon…"（含 `sessionEndControls` 五種組合與 zh-TW／en parity）；E2E 斷言 hint、confirm 文案、按鈕 |

## 關門 gate

- 全套 backend pytest（cwd `apps/server`）：exit 0。
- `npm test -- --run`：90 files／513 passed；`npm run build`：成功。
- `docker compose config`：通過。
- E2E（Docker，`ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1`）：`m05-session-history`、`p2f-session-lifecycle`、`p3e-mcp-browser-integration`（＋`m03c-character-import` 供前置角色）9 passed／2 skipped。
- 全套 E2E：合併回 `main` 前執行，結果記在 merge commit 訊息。

## 指揮者審核修正摘要

- A1：刪除只呼叫另一測試的空殼 `test_ai_dm_token_rejected_after_owner_end`；兩個 fixture builder 的重複 room／campaign／access-session 種子抽成 `_seed_room_and_campaign`／`_insert_access_session`。production diff 零修正。
- A2、A3 由指揮者實作。

## 觀察到但不屬 M05-A 的事項（建議登記 `已知問題.md`）

1. **Owner 沒有 Seat 時 Session 頁顯示「Session not found.」**：Owner 對 AI DM 場（自己不控制任何 Seat）開 Session 頁，Session-management 區塊正常，但事件串／Stage 讀取 404，顯示 "Session not found."。M05 前既有行為，不是 M05-A 造成；M05-B 的 history scope 也只涵蓋已結束場，不會改善 active 場。建議後續讓 Owner 無 Seat 時顯示明確的「你沒有本場 Seat，看不到桌面」提示。
2. **`p2f-session-lifecycle.spec.ts` 有隱性順序依賴**：它讀 `/api/characters` 取第一隻角色，但不在 `BASELINE_ROOM_SPECS`，單獨跑 worker Room 沒有角色必失敗；整套跑時靠同 worker 先跑的 spec 順帶建角色。建議改為自建角色或移入 baseline-room。
