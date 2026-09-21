# P6-C — AI Context & Retrieval 實作紀錄

## 接手摘要

- **更新日期**：2026-09-21
- **目標與邊界**：新增 `CampaignContextService`（`get_campaign_context`／`get_scene_context`／`search_campaign_context`／`get_world_entry`／`get_adventure_entry`）與同名五個 MCP read tool，輸出 role-projected、bounded、deterministic 的 Campaign context；`get_session_context` 只加 compact summary／refs，`BRIEFING_MAX_CHARS` 仍是 hard gate。AI Player 不得拿到任何 Adventure entry id／title／body／命中數 side channel，也不得拿到 DM-only Runtime truth。不做 write-back（P6-D）、不改 P3-D pre-session grant、不做 vector／embedding／LLM reranker。
- **Branch**：`feat/p6c-ai-context-retrieval`（自 `main@a2e04387`）
- **最近已驗證 commit**：`28bd076e`（C4 test）；closeout 見 [P6-C_CLOSEOUT.md](P6-C_CLOSEOUT.md)
- **下一步**：C1～C4 完成，Subphase 關門並合併 `main`；接 P6-D（開工前先拆 `campaign_runtime/service.py`，見派工約束 2）。使用者 2026-09-21 拍板四步；C0 拆 `service.py` 不做，留到 P6-D write-back 再拆。
- **阻礙／未審**：無。
- **派工約束（P6-B 回顧，31.8k 行中 19.1k 是測試；`campaign_runtime/service.py` 已 2,511 行）**：
  1. **測試用 parametrize／shared fixture，同一矩陣不得展開成獨立 function。** 每個 step prompt 明寫；審核時把「同一 assert 模式重複三次以上」視同退修，不只擋錯誤。P6-B 的 `test_p6b_runtime_api.py` 3,779 行是反例。
  2. **P6-C 只新增獨立 `CampaignContextService` module，不往 `campaign_runtime/service.py` 疊程式**；該檔（2,511 行）留到 P6-D write-back 開工前再拆。
  3. 前端測試同樣適用第 1 點；單一 step 的 `.test.tsx` 不應超過該 step 元件本體的兩倍。
- **正式契約入口**：`docs/P6/實作規格.md`「P6 共用產品邊界」「P6-C」；`docs/P6/開發設計方針.md`「Architecture」「Shared authority / projection」「P6-C」（C.1 Context service、C.2 MCP tool contract）「REST / UI surface」「Subphase implementation boundary」；`docs/P6/測試指南.md`「P6 核心風險」「執行環境」「P6-C」（C.1～C.6）。
- **跨步依賴**：C1→C2→C3→C4；共用測試 fixture 住 `tests/p6_active_fixture.py`（C2 起）。C.2 tool 名稱固定，須同步 `app/mcp/guide_tool_names.py` `_EXPECTED` 與 M04 catalog parity、English＋zh-TW description。P6-B 技術決策（context clear 不刪 row、Player Journal 只列 public quest／fact＋own-character）見 [P6-B closeout](P6-B_CLOSEOUT.md)。

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| C1 | `CampaignContextService`：campaign／scene context 與單筆 entry read | 完成 | — | [C1](P6-C_steps/C1.md) |
| C2 | `search_campaign_context`：bounded、deterministic、零 side channel | 完成 | C1 | [C2](P6-C_steps/C2.md) |
| C3 | `get_session_context` compact summary 與五個 MCP read tool | 完成 | C1、C2 | [C3](P6-C_steps/C3.md) |
| C4 | 完整 gate、closeout、合併 | 完成 | C1～C3 | [C4](P6-C_steps/C4.md) |
