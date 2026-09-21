# P6-C — AI Context & Retrieval 實作紀錄

## 接手摘要

- **更新日期**：2026-09-21
- **目標與邊界**：新增 `CampaignContextService`（`get_campaign_context`／`get_scene_context`／`search_campaign_context`／`get_world_entry`／`get_adventure_entry`）與同名五個 MCP read tool，輸出 role-projected、bounded、deterministic 的 Campaign context；`get_session_context` 只加 compact summary／refs，`BRIEFING_MAX_CHARS` 仍是 hard gate。AI Player 不得拿到任何 Adventure entry id／title／body／命中數 side channel，也不得拿到 DM-only Runtime truth。不做 write-back（P6-D）、不改 P3-D pre-session grant、不做 vector／embedding／LLM reranker。
- **Branch**：尚未建立；自 `main@5f67feba`（P6-B merge）開分支。
- **最近已驗證 commit**：無（尚未開工）。
- **下一步**：使用者拍板後由指揮者拆步（§2.1），先決定是否採納下列 C0。
- **阻礙／未審**：無。
- **派工約束（P6-B 回顧，31.8k 行中 19.1k 是測試；`campaign_runtime/service.py` 已 2,511 行）**：
  1. **測試用 parametrize／shared fixture，同一矩陣不得展開成獨立 function。** 每個 step prompt 明寫；審核時把「同一 assert 模式重複三次以上」視同退修，不只擋錯誤。P6-B 的 `test_p6b_runtime_api.py` 3,779 行是反例。
  2. **C1 開工前先拆 `app/domain/campaign_runtime/service.py`**（建議 C0：依 management／active／override／context 四段拆 module，行為零改動、既有 P6-B 測試全綠即關門），否則 P6-C context 與 P6-D write-back 疊上去會破 4k 行。
  3. 前端測試同樣適用第 1 點；單一 step 的 `.test.tsx` 不應超過該 step 元件本體的兩倍。
- **正式契約入口**：`docs/P6/實作規格.md`「P6 共用產品邊界」「P6-C」；`docs/P6/開發設計方針.md`「Architecture」「Shared authority / projection」「P6-C」（C.1 Context service、C.2 MCP tool contract）「REST / UI surface」「Subphase implementation boundary」；`docs/P6/測試指南.md`「P6 核心風險」「執行環境」「P6-C」（C.1～C.6）。
- **跨步依賴**：C.2 tool 名稱固定，須同步 `app/mcp/guide_tool_names.py` `_EXPECTED` 與 M04 catalog parity、English＋zh-TW description。P6-B 技術決策（context clear 不刪 row、Player Journal 只列 public quest／fact＋own-character）見 [P6-B closeout](P6-B_CLOSEOUT.md)。

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| C0 | 拆分 `campaign_runtime/service.py`（零行為改動） | 待拍板 | — | — |
| C1～ | 待拆分 | 待做 | C0 | — |
