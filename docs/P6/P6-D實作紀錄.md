# P6-D — AI DM Write-back & Exploration Integration 實作紀錄

## 接手摘要

- **更新日期**：2026-09-21
- **目標與邊界**：D0 先把 `app/domain/campaign_runtime/service.py`（2,511 行）拆成 leaf module（errors／conversion／adventure overlay／event envelope）與三個 transaction-bound mutation module，`CampaignRuntimeService` 留在 `service.py`；純搬移、零行為改變、零 public signature 改變。D1 起才做 P6-D 契約：`CampaignWorldService`／`resolve_world_action` atomic world＋narration、Stage bridge、MCP write tool。不做 P7 GameTransaction、不改 P3 narration event kind、不直接寫 Character `inventory_state`。
- **Branch**：`feat/p6d-ai-dm-write-back`（自 `main@10565217`）
- **最近已驗證 commit**：無（D0a 派工中）
- **下一步**：D0a → D0b；D1 起的拆步待使用者拍板後補進步驟板。
- **阻礙／未審**：無。
- **派工約束**：沿 P6-C 派工約束 1／3（parametrize、測試不展開矩陣）；D0 兩步 **只搬不改**——函式本體逐字保留（僅允許移除跨模組後的 leading underscore 與對應 import 調整），指揮者以 AST 逐函式比對前後本體驗證。
- **正式契約入口**：`docs/P6/實作規格.md`「P6 共用產品邊界」「P6-D」；`docs/P6/開發設計方針.md`「Architecture」「Shared authority / projection」「P6-D」（D.1～D.4）「Subphase implementation boundary」；`docs/P6/測試指南.md`「P6 核心風險」「執行環境」「P6-D」（D.1～D.8）。
- **跨步依賴**：D0a → D0b。P6-B／P6-C 技術決策見各自 closeout；共用測試 fixture 住 `tests/p6_active_fixture.py`。

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| D0a | 拆 `service.py`：errors／conversion／adventure_overlay／events leaf module | 進行中 | — | [D0a](P6-D_steps/D0a.md) |
| D0b | 拆 `service.py`：entry／override／context mutation module，`service.py` 只留 `CampaignRuntimeService` | 待做 | D0a | [D0b](P6-D_steps/D0b.md) |
