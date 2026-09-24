# G4c — World 寫入工具 state 形狀說明與錯誤 detail（G4 續跑補缺）

## Scope

- G4 續跑中 AI DM 想把銀鑰匙 `holder_ref` 設為玩家角色，`world_update_entry` 只回無 detail 的 `invalid_arguments`（見 [G4](G4.md)）。以 server 端 `parse_runtime_payload` 重現：正確形狀 `{kind:'item', holder_ref:{kind:'character', target_id:<character id>}}` 可通過；`id`／`character_id` 欄位名或 `kind:'player'` 皆被拒。
- 根因：`RuntimeWorldEntryPatch.state` 是 open object，tool description 未寫各 kind 的 state 形狀；`RuntimeEntryPayloadError`／`CampaignRuntimeValidationError` 走通用 `ValueError` 分支，錯誤原因被丟棄。
- 契約：`開發設計方針.md`「P6-D — D.4 MCP tool contract」新增 state 形狀說明與 DM 錯誤 detail 條款。不改資料模型與驗證規則。

## 實作

- `app/mcp/tools.py`：`world_create_entry`／`world_update_entry` description（en／zh-TW）列出各 kind state 形狀、item `holder_ref` 的 kind／`target_id` 與 character id 來源（`party[].active_character_id`），並註明 `patch.state` 整個取代 state。
- `RuntimeEntryPayloadError`／`CampaignRuntimeValidationError` 另立分支：DM caller 的 `invalid_arguments` 帶 `detail`（包裝的 pydantic 錯誤壓成 `loc: msg`，其餘用訊息本身，上限 600 字）；Player caller 不帶 detail。

## 驗證

- 新增 `tests/test_p6g_world_tool_errors.py`（5 cases）：G4 實際猜錯形狀得到 `item.holder_ref.id: Extra inputs are not permitted`；business validation 訊息原樣帶出；Player caller 無 detail；兩個 world 寫入工具雙語 description 含 state 形狀。
- MCP 相關 regression（10 檔，含 M04 tool description／guide parity、P4-C adapter、M04-B authority、P6-C／D／F MCP、G4a outline）：235 passed。
- 完整 backend pytest（cwd `apps/server`）：**2543 passed／78 skipped**，exit 0。前端未改動。

## 完成紀錄

- 2026-09-24 完成實作與驗證；commit 訊息標題含 `G4c`。
