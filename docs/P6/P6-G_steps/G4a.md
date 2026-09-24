# G4a — AI DM Adventure outline 與主持指引（P6-C 補缺）

## Scope

- G4 第一次真實 ChatGPT Web 嘗試發現 AI DM 無法自行得知附加 Adventure 的內容（見 [G4](G4.md)「發現與處置」）。依 P6-G 接手摘要「A～F 必要能力缺漏回所屬 Subphase 補」，本步補 P6-C context 與 M04／P6 AI guidance，不新增資料模型或玩法。
- 契約：`開發設計方針.md`「P6-C — C.1 Context service」新增的 AI DM Adventure 發現條款。

## 實作

- `CampaignContextDmView.attached_adventures[]` 增加 `summary`、`outline`（entry id／parent／kind／title／visibility／has_override，不含 body）與 `outline_truncated`；上限 `ADVENTURE_OUTLINE_MAX_ENTRIES = 100`。Player view 不變。
- `get_session_context` DM compact summary 增加 `attached_adventures`（id／name／outline_entry_count）；`next_context_tools` 有 Adventure 時以 `get_campaign_context` 開頭，current scene 為 none 時加 `world_set_current_context`。
- DM pre-session briefing 與 active loop 加入「讀 outline → get_adventure_entry → world_set_current_context → world_set_override／world_create_entry 寫回」；DM active briefing 2957／3000 字。`/mcp/guide` 新增「Adventure 與世界狀態（DM）」段（zh-TW／en）；`get_campaign_context` tool description 標明 DM outline。

## 驗證

- 新增 `tests/test_p6g_adventure_outline.py`（10 cases）：Human DM／AI DM outline 內容、dm_only 條目只出現 id／title 不出現 body、Player／AI Player 無 outline／名稱／id、上限截斷、session summary 導引與 scene 已設時不再提示、briefing 雙語工具導引與長度上限、player pre-session 不含 DM 導引、guide 雙語段落。
- 既有 focused regression：`test_p6c_context_service`、`test_p6c_mcp_tools`、`test_p6d_mcp_tools`、`test_p6f_mcp_tools`、`test_m04c_briefing`、`test_m04c_guide_tool_parity`、`test_m04c_mcp_guide`、`test_m04c_tool_descriptions`、`test_m04c_discover_instructions`、`test_p3e_pre_session_ai_dm`、`test_p4e_session_context_combat`、`test_p4f_adjudication_routing` 全綠。
- 完整 backend pytest（cwd `apps/server`，8 workers）：**2538 passed／78 skipped**，exit 0（G4 前預跑 2528 passed，+10 為本步新測試）。
- 前端未改動、DTO 只經 MCP 送出（無 REST／web consumer），不適用前端單元測試與 E2E。

## 完成紀錄

- 2026-09-24 完成實作與驗證；commit 見 git log `test(P6-G): …G4a` 一筆。
