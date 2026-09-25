# G5a — AI campaign context 自由文字與清單上限（G5 靜態審核補缺）

## Scope

- G5 依 G.8 做 bounded-context 靜態審核時發現：DM `get_campaign_context` 的 Adventure outline 有 100 筆上限，但 `AttachedAdventureRef.summary` 原樣帶出 Adventure `summary`。該欄位在 `AdventureDefinitionCreate`／`Patch` 沒有長度上限、DB 為 `Text`，單一 summary 可讓回應任意變大。
- 指揮者擴大檢查同一投影：`current_situation`（`CampaignRuntimeContextPatch` 同樣無上限，且經 `get_session_context` 的 campaign summary 帶出）與 `world_entries`（列出全部 active Runtime entry，筆數隨 Campaign 增長）也無上限。
- 依 P6-G 接手摘要「A～F 必要能力缺漏回所屬 Subphase 補」，屬 P6-C bounded context 補缺。只在 AI context 投影加上限，不改寫入 DTO、資料模型或既有資料；Web UI 不消費此 DTO。

## 實作

- `app/domain/campaign_runtime/context_schemas.py`：新增 `CONTEXT_TEXT_MAX_CHARS = 1000`、`CAMPAIGN_CONTEXT_MAX_WORLD_REFS = 100` 與 `bounded_context_text()`；`AttachedAdventureRef.summary_truncated`，DM／Player view 加 `current_situation_truncated`、`world_entries_truncated`。
- `app/domain/campaign_runtime/context.py`：`get_campaign_context` 截斷 `current_situation`、依既有順序取前 100 筆 `world_entries`；`_resolve_attached_adventures` 截斷 `summary`。
- `app/domain/campaign_runtime/ai_tools.py`：`get_session_context` 的 campaign summary 加 `current_situation_truncated`。
- 契約：`開發設計方針.md` P6-C AI context 段補上限條款。

## 驗證

- 新增 `tests/test_p6g_context_bounds.py`（11 cases）：`bounded_context_text` 邊界；DM（human／AI）summary 截斷與短 summary 不變；四種 actor 的 `current_situation` 在 campaign context 與 session summary 都截斷；短 situation 不變；`world_entries` 上限與旗標。
- Focused（新檔＋`test_p6g_adventure_outline.py`＋`test_p6c_mcp_tools.py`）：60 passed。
- 完整 backend pytest（cwd `apps/server`）：**2556 passed／78 skipped**，exit 0。
- 重建 `server-e2e` 後跑會呼叫 AI context 工具的 E2E：`m04c-ai-join-kit`、`m05-session-history`、`p3e-mcp-browser-integration`、`p6g-adventure-journey`，**8 passed**。

## 完成紀錄

- 2026-09-25 完成實作與驗證；commit 訊息標題含 `G5a`。
- 已知限制：`world_entries` 沿用既有 `created_at` 升冪，超過上限時保留的是最早的 100 筆（`get_session_context` 的 20 筆 refs 同樣取最早）；較新的 entry 需經 `search_campaign_context`。改為「最近更新優先」屬後續調整，不在本步。
