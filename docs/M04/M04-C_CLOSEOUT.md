# M04-C Closeout Checklist

M04-C — AI Join Kit, Server-hosted Guide & Other Client Compatibility。此文件依 [實作規格](實作規格.md) C.1～C.9 與 [測試指南](測試指南.md) C.1～C.10 收斂證據。

> 狀態：**closeout gates 完成。** 自動 gate（C.1～C.7、C.10）與 C.8 真實 AI 憑 kit 進桌（ChatGPT Web Plus）皆於 2026-09-12 完成。C.8 的 Bearer MCP client 與純 HTTP 路徑、C.9 其他 client 相容記錄，依使用者 2026-09-12 拍板**延後**，不列為本 Subphase gate（見下「延後項目」）。

## 自動 gate 證據（C.1～C.7、C.10）

- Branch：`m04-c-ai-join-kit-guide`
- 本機全套 backend pytest：1,429 tests，exit 0（0 failed；clean worktree @ `e9c310b`）
- 本機前端 `npm test -- --run`：72 files / 331 tests passed；`npm run build`：✓ built
- `docker compose config`：OK
- CI `M04-C Non-E2E Regression`：run `34701747258`（success，含 `e9c310b`）
- E2E：diff 動到 `apps/web`（`AIJoinKit.tsx`、兩個 AI control panel、`SessionTableSurface.tsx`、`e2e-global-setup.mjs`），依測試指南 1.1 以 `P3 Full-Stack E2E`（全套 Playwright，含 `m04c-ai-join-kit.spec.ts`、`p3e-mcp-browser-integration.spec.ts`、`p3c-roll-check-pending-action.spec.ts`）為證據：run `34703269124` **success**（2026-09-12，branch @ `e9c310b`）

| 契約 | 測試檔 |
|---|---|
| C.1 `GET /mcp/guide` | `tests/test_m04c_mcp_guide.py`；standalone 不掛：`tests/test_p3e_standalone_mcp.py` |
| C.2 指引內容 | `tests/test_m04c_mcp_guide.py`（三種接入方式、適用性聲明、wire 契約、等待規則 120 秒／5 次、無秘密、不碰 DB）；與 catalog 同源：`tests/test_m04c_guide_tool_parity.py` |
| C.3 tool description 加厚、catalog 前後相同 | `tests/test_m04c_tool_descriptions.py`；`tests/test_p3e_mcp_tools.py::test_pre_session_dm_catalog_matches_active_dm_catalog`、`tests/test_p3e_pre_session_ai_dm.py` |
| C.4 `briefing`（強制流程、MCP 呼叫判定、≤ `BRIEFING_MAX_CHARS`） | `tests/test_m04c_briefing.py` |
| C.4a `stage_unset` / `next_required_action` | `tests/test_p3e_pre_session_ai_dm.py`、`tests/test_p3e_temporary_instruction_context.py`、`tests/test_m04c_briefing.py::test_stage_hint_steers_dm_to_set_stage_then_wait` |
| C.5 `server/discover.instructions` | `tests/test_m04c_discover_instructions.py` |
| C.6 kit builder、雙 URL、面板接線、公網 origin endpoint | `apps/web/src/features/rooms/AIJoinKit.test.ts`、`LobbyAIDMGrantPanel.test.ts`、`PlayerAIControlPanel.test.ts`、`src/api/aiControllers.test.ts`、`hardcodedUiCopy.test.ts`；`tests/test_m04c_public_origin_endpoint.py`；browser：`e2e/m04c-ai-join-kit.spec.ts` |
| C.7 雙語 | 上列各測試皆斷言 zh-TW／en；`hardcodedUiCopy.test.ts`、copy store parity 測試 |
| `wait_for_event` 上限 120 秒 | `tests/test_m04b_wait_timeout_cap.py`（120 通過、120.1 拒絕；Human UI `le=60` 不變） |
| Standalone boundary | `tests/test_m03_import_boundary.py`、`tests/test_m03_standalone_composition.py`、`tests/test_p3e_standalone_mcp.py` |

## C.8 真實 AI 只憑 kit 進桌（2026-09-12）

| 路徑 | 結果 |
|---|---|
| **ChatGPT Web Plus（目標平台，connector + OAuth 貼 token）** | ✅ 使用者於 2026-09-12 以 Lobby／Session 產出的 AI Join Kit 人工完成，AI 憑 kit 進桌並跑迴圈。入口形態同 M04-B B.8（Tailscale Funnel → `/mcp`）。本次未抄錄 server access log 與 tool call 次數；平台、帳號與 OAuth 細節以 [M04-B_CLOSEOUT.md](M04-B_CLOSEOUT.md) B.8 為準 |
| MCP client（Bearer） | **延後**（使用者 2026-09-12 拍板） |
| 純 HTTP code-execution client | **延後**（使用者 2026-09-12 拍板） |

真實使用同日暴露並在本 branch 修正的缺口：

1. AI DM 用 `request_check` 時傳友善技能／屬性名（`investigation`、`dexterity`）會被存成無法 resolve 的 ref，到 Player 擲骰時才炸。→ `0bbb9fa`：`resolve_skill_ref`／`normalize_ability_name` 在建立 Check 時 normalize，失敗回 `unknown_check_ref`（MCP structured error 與 API 422 同碼，前端 locale 字串雙語補齊）。
2. AI DM 建立 Check 後，Player 在 Chat tab 看不到「DM 要求你擲骰」，AI 又被 guidance 禁止為同一次要求另發 `post_narration`。→ `6890811`：既有 `roll.requested` event 在 Chat tab 以系統訊息呈現（`sessionRollPresentation.ts`），payload 補 `label`，DC 仍不進 payload；guidance／tool description 改寫為「request_check 成功會自動顯示擲骰提示」。
3. 本機 E2E reset 對含 AI Seat／Session history 的 DB 只刪掉一部分。→ `e9c310b`：改為 `TRUNCATE rooms, characters, ai_oauth_clients RESTART IDENTITY CASCADE`，`--single-transaction` + `ON_ERROR_STOP=1`；29 張表全部可由這三個 root 經 FK 到達。

## 延後項目（使用者 2026-09-12 拍板）

| 項目 | 原契約 | 處置 |
|---|---|---|
| C.8 Bearer MCP client 路徑 | 實作規格 C.8「兩條路徑各至少一次」 | 延後；不列本 Subphase gate。P3-F E1 已有 Claude Code 2.1.260 經 HTTPS Bearer 進桌的證據，但那是 token 而非 kit |
| C.8 純 HTTP 路徑 | 同上 | 延後 |
| C.9 其他 client 相容記錄 | 非目標平台網頁版 chat、Codex CLI、Codex Desktop 各一列 | 延後；本檔無「Compatibility」表。Codex CLI 0.154.0 仍為 legacy `2025-06-18`（P3-E preflight），現況可預期為不通 |

三份 M04 文件的 C.8／C.9 段已同步加註此修訂。

## 已知限制

- kit 的公網 URL 依賴 `ADVENTURE_TABLE_MCP_PUBLIC_ORIGIN`；未設定時 kit 只印本機 URL 與「尚未設定公網入口」提示，網頁版 chat 連不進來是預期行為。
- `e2eGlobalSetup.test.ts` 是對 `e2e-global-setup.mjs` 原始碼的字串斷言，只防止改回逐表 DELETE；reset 是否真的清乾淨仍以下一次 `test:e2e:docker`／CI E2E 成功為證據。
- `formatTargetRef` 的技能／屬性顯示名仍硬編 `srd5.1:*` key（P3-C 既有），非 SRD pack 的技能會 fallback 顯示原始 key。
- ChatGPT connector 在 `start_session` 後仍需 Refresh 才會重掃 catalog（M04-A A.5）；C.3 把 DM catalog 改為前後相同後，已不需要新對話才看得到 gameplay 工具，但 Refresh 這一步仍寫在 kit 與 guide。

## Closeout status

- C.1～C.7：✅ 自動證據見上
- C.8 ChatGPT Web Plus：✅ 2026-09-12（使用者人工）
- C.8 Bearer／純 HTTP、C.9：延後（非 gate）
- Subphase 關門 gate：backend pytest 1,429 / 0 failed、前端 331 tests + build ✓、`docker compose config` OK、`P3 Full-Stack E2E` run `34703269124` success

**M04-C 關門 ✅。** M04 Phase 關門（合併回 `main`、全套 E2E）待使用者指示；下一步 P4 開工前置。
