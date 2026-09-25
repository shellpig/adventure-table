# G4d — 暫時性 MCP 失敗重試指引與 host 中立措辭（G4 收尾補缺）

## Scope

- G4 期間 ChatGPT Web 與 Claude 網頁版都偶爾遇到工具呼叫連續失敗 2–3 次（逾時、connector 錯誤），稍後重試即成功；AI 若因此停下，桌面就卡住。使用者決定：失敗且沒有 AT 回應時持續重試，不要停下交回人類。
- G4 跨 Session 讀回由 Claude 網頁版完成（見 [G4](G4.md)），使用者拍板 connector gate 不限 ChatGPT：原本 P6／P5 契約與 AI 接入文案中的「ChatGPT Web」改稱「網頁版 AI agent」。M04 等已關門文件與歷史紀錄保留原措辭。
- 不改工具、資料模型或權限；401 `ai_token_unauthorized` 仍然停止、不重試；AT 回傳的業務錯誤（`ok:false`）不是暫時錯誤。

## 實作

- `app/domain/rooms/ai_guidance.py`：active briefing 的 MCP 呼叫判定（en／zh-TW）精簡後併入「沒有 AT 回應的失敗是暫時的，用同一 `idempotency_key` 重試直到成功，不要停下；只有 401 才停止」；pre-session briefing 加一句重試。DM active／combat briefing 2965／2983 字，仍在 `BRIEFING_MAX_CHARS` 3,000 內。
- `app/mcp/guide.py`：guide 結尾加暫時失敗重試段落（區分業務錯誤與 401）；「ChatGPT Web」標題改「網頁版 AI agent」。
- `app/mcp/oauth.py`：授權頁「ChatGPT connector」改「AI agent connector」。
- `apps/web/src/features/rooms/AIJoinKit.tsx`：AI 指令加重試句；接入設定第 1 項改「網頁版 AI agent」。
- 文件：`docs/P6` 三份契約、`P6-G實作紀錄.md`、G4／G5 step、`PROJECT_BRIEF.md`、`docs/P5` 實作規格與測試指南的 gate 措辭。

## 驗證

- `tests/test_m04c_briefing.py` 新增三種 mode × 兩種 role 都含重試句；`tests/test_m04c_mcp_guide.py` 新增 guide 不含 ChatGPT 且含重試段；`tests/test_m04b_oauth_endpoints.py` 授權頁斷言 host 中立；`AIJoinKit.test.ts` 斷言重試句、新措辭且不含 ChatGPT。
- Focused backend（briefing、guide、OAuth endpoints、P4-E session context、P6-C MCP、G4a outline、M04-B README）：89 passed。
- 前端 `npm test -- --run`：103 files／775 passed；`npm run build` 通過。
- 完整 backend pytest（cwd `apps/server`）：**2545 passed／78 skipped**，exit 0。

## 完成紀錄

- 2026-09-25 完成實作與驗證；commit 訊息標題含 `G4d`。
