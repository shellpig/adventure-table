# P6-G — Full P6 Integration & Closeout · Closeout

日期：2026-09-25　Branch：`codex/p6g-integration`（依賴 P6-F `feat/p6f-import-review-finalize@73a2ee9a`）　狀態：**關門並合併回 `main`（P6-F merge `b06e2e21`、P6-G merge `8b47fb05`）；P6 Phase 全部完成**

步驟與詳細證據見 [P6-G 實作紀錄](P6-G實作紀錄.md) 與 `P6-G_steps/`。

## G.1～G.8 驗收對照

| 項目 | 證據 |
|---|---|
| G.1 Empty Campaign browser journey | `p6g-empty-campaign.spec.ts`（[G1a](P6-G_steps/G1a.md)、[G1b-1](P6-G_steps/G1b-1.md)、[G1b-2](P6-G_steps/G1b-2.md)）：零 Adventure Start → narration → Quick Add NPC＋Fact → Player action → Check／roll → Quick Combat attack／damage → End Combat → Situation → End → next Session 延續 Runtime、HP 與 Combat outcome |
| G.2 Adventure-driven browser journey | `p6g-adventure-journey.spec.ts`（[G2a](P6-G_steps/G2a.md)～[G2b-3](P6-G_steps/G2b-3.md)）：authoring／finalize／attach → Scene／Stage image → Exploration／Check → Quick Combat → Override＋Fact 寫回 → next Session 看到改變後的 world，baseline 不變 |
| G.3 Real PostgreSQL restart | `p6g-restart-continuity.spec.ts`（serial-restart，[G3a](P6-G_steps/G3a.md)）：真 Docker PostgreSQL 重啟 `server-e2e` 後 Runtime、context、import draft 的 id／revision／visibility 一致 |
| G.4 Real web chat AI agent gate | [G4](P6-G_steps/G4.md) 完成紀錄：ChatGPT Web 以 Join Kit 自主主持（context、Check、Quick Combat、world 寫回），Claude 網頁版在下一場 Session 讀回改變後的 world；證據為 AT DB／event。補缺 [G4a](P6-G_steps/G4a.md)～[G4d](P6-G_steps/G4d.md) |
| G.5 Secrecy matrix | [G3b](P6-G_steps/G3b.md)：REST／Resume／Event／MCP／UI network 逐項；13 module 358 passed＋Player Resume network E2E |
| G.6 Quick／P5 independence | G2 Quick Combat 無 Tactical grid；P6 domain（`campaign_runtime`／`adventures`／`adventure_imports`）無 tactical／spatial import（G5 靜態複查） |
| G.7 Standalone | `test_m03_import_boundary.py`、`test_m03d_schema_parity.py` 在全套 backend 內通過；P6-G 未新增 Python 相依、未改 Standalone schema |
| G.8 Closeout evidence | 下方「Gate 結果」與「靜態審核」 |

## Gate 結果

| Gate | 結果 |
|---|---|
| Backend 全套 pytest（G5a 後） | **2556 passed／78 skipped**，0 failed |
| Frontend Vitest＋build | **103 files／775 passed**，build 通過（G5a 未改 `apps/web`） |
| `docker compose config` | 通過 |
| 全套 Docker E2E parallel（兩次） | 各 **101 passed／3 failed／3 skipped**；失敗為 1 次已知 Builder flake（P1-G，重啟後單跑通過）與 5 次 worker crash（KI-ENV-002，單跑全過） |
| baseline-room | **30 passed／1 skipped** |
| serial-restart | **2 passed** |
| xge-less M03-C 子集 | **7 passed**（手動依 script 執行，之後還原完整內容包） |
| G5a 後 AI context 相關 E2E | `m04c-ai-join-kit`、`m05-session-history`、`p3e-mcp-browser-integration`、`p6g-adventure-journey` **8 passed** |

## 靜態審核（P6 closeout blocker）

| Blocker | 結論與證據 |
|---|---|
| Campaign 沒有 Adventure 不能玩 | 否。G.1 零 Adventure journey |
| Adventure template 被 Runtime 直接修改 | 否。`test_p6a_campaign_adventures.py::test_table_actor_cannot_modify_finalized_adventure`；G2b-3 baseline 不變 |
| 只能 attach 一個 Adventure | 否。`test_p6a_campaign_adventures.py::test_attach_two_adventures_and_list_in_order`、`::test_detach_leaves_the_other_attached` |
| Current Scene／Situation 變成 mandatory | 否。G.1 從未設定 scene 仍跑完 |
| Player／AI Player 可讀 secret／dm_notes／他人 knowledge | 否。G.5 secrecy matrix |
| P6 context 無上限塞整本 Adventure | **審核時發現缺口**：Adventure `summary`、`current_situation`、`world_entries` 無上限。[G5a](P6-G_steps/G5a.md) 在 AI context 投影加上限（1000 字、100 筆＋truncated 旗標），`test_p6g_context_bounds.py`；outline 100 筆、search snippet 160 字原本已有界 |
| AI DM 不能可靠寫入 persistent world state | 否。G.4 |
| failed write-back 仍發布 definitive narration | 否。`test_p6d_world_action.py::test_forced_narration_projection_failure_rolls_back_world_and_events` |
| retry 重複建立 world entity／Adventure | 否。`test_p6d_world_action.py::test_same_key_retry_and_conflicts`、`test_p6d_world_service.py::test_idempotency_retry_succeeds_once_and_does_not_duplicate_events`、`test_p6f_finalize.py::test_finalize_idempotency_retry` |
| importer 必須有 server LLM | 否。`apps/server/app` 無任何 LLM client import；P6-E／F 手動 Draft 與外部 AI MCP 路徑 |
| source provenance 可把 AI 猜測標成原文 | 否。`test_p6e_import_schemas.py::test_draft_entry_rejects_unknown_provenance`、`test_p6f_review_state.py::test_nonfabrication_provenance_door_hard_to_pick` |
| P6 依賴 Tactical geometry | 否。G.6 |
| 跨 Session world truth 遺失 | 否。G1b-2、G2b-3、G4 跨 Session 讀回 |
| P6 schema 污染 Standalone | 否。G.7 |
| 真實網頁版 AI agent P6 journey 未通過 | 否。G.4 |

## 已知限制

- **KI-ENV-002**：Windows 主機上 Playwright worker 偶發崩潰（0xC0000409），兩次 parallel 共 5 次、分布在不同 spec，單跑全過；會讓 script 中止、需手動補跑後續趟次。
- **KI-P1D-001**：targeted 單 worker 補跑中 M01-M 重現一次（Draft revision 2／Saving…），整檔單跑 5 passed、之後 parallel 也通過；根因未確認。證據見 [error-context](P6-G_steps/G5_KI-P1D-001_2026-09-25_error-context.md)。
- **G4 非 blocker 觀察**：NPC 在出場前約 8 分鐘即以 public 建立；守衛命中即判死、未走 damage；未使用 Adventure override（改以連回 Adventure 的 runtime entries）；`wait_for_event` 只有 host UI 觀察證據。
- **AI context 排序**：`world_entries` 超過 100 筆、session summary 超過 20 筆時保留最早建立的，較新的要靠 `search_campaign_context`。
- **AI 長時間主持成本**：`wait_for_event` 會被自己的寫入喚醒、實際等待上限 60 秒與契約 120 秒不符、`roll.resolved` payload 偏大；由 M06 處理（P6 關門後、P5-A 前）。

## 合併順序

P6-F closeout 只跑了相關 spec；P6-G 分支包含 P6-F 全部 commit，本 closeout 的全套 E2E 同時涵蓋兩者。2026-09-25 依序 `--no-ff` 合併：P6-F `b06e2e21`、P6-G `8b47fb05`；合併後 `main` 的內容與已驗證的 `codex/p6g-integration` 完全相同（`git diff` 為空），驗證證據直接適用。
