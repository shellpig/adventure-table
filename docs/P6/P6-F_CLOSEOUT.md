# P6-F — Import Review, Finalization & Importer MCP · Closeout

日期：2026-09-23　Branch：`feat/p6f-import-review-finalize`（自 `main@6028d6c9`）　狀態：關門驗證通過，待合併回 `main`

## 驗收對應

| 契約 | 證據 |
|---|---|
| F.1 Warning 三級：Info／Warning 可定稿，未解 Blocking 不可，resolve 後可 | `test_p6f_review_state.py::test_unresolved_blocking_warnings_filter`、`test_p6f_finalize.py::test_finalize_blocking_warnings_gate`、`test_p6f_review_api.py::test_unresolved_blocking_warning_blocks_finalize_until_resolved`；`AdventureImporterPanel.test.tsx` 的 warning level／resolved 狀態表；`p6f-import-review.spec.ts` 的 blocking → resolve → finalize 流程 |
| F.2 無虛構規則值：原文沒有 DC 時不得把推測標為 `source_document`，Human 可保留 `DM decides` | `test_p6f_review_state.py::test_nonfabrication_provenance_door_hard_to_pick`；`test_p6f_mcp_tools.py` 的 tool description／dispatch 與 M04 guide parity；Review UI 保留 provenance，Draft edit 不覆寫來源狀態 |
| F.3 Accept／Edit／Ignore／Mark uncertain／View source；不要求逐項 Accept | `test_p6f_review_state.py::test_set_entry_review_happy_path_and_revision_increments`、`::test_pending_entries_do_not_block`、`test_p6f_finalize.py::test_finalize_pending_only_draft`；`AdventureImporterPanel.test.tsx` 的 pending／ignored／uncertain finalize 表、source_ref 條件及 PDF／DOCX section locator → chunk offset 對應；`p6f-import-review.spec.ts` 實際操作 Accept／Mark uncertain／View source |
| F.4 Finalize 建新 Adventure baseline，parent／entry／asset 對應正確；rollback、retry、reconnect 不複製 | `test_p6f_finalize.py::test_finalize_success_full_structure`、`::test_finalize_idempotency_retry`、`::test_finalize_rollback_on_invalid_asset`、`::test_finalize_parent_cycle_rejected_and_rolled_back`；`test_p6f_authoring_transaction.py`；`test_p6f_review_api.py::test_second_finalize_returns_same_adventure_id`；Docker PostgreSQL 人工 retry probe 兩次回同一 Adventure id、import target 相同、Adventure 計數 1；E2E reload 後 target link 仍在 |
| F.5 六個 Importer MCP tool、Human／AI 共用 service、current AI DM authority；Player、stale／revoked、pre-session 拒絕 | `test_p6f_import_ai_authority.py` 的 AI DM success、unauthorized zero-side-effect matrix；`test_p6f_mcp_tools.py` 的 catalog、guide names、gate、real service journey、error mapping；`test_p6a_campaign_adventures.py::test_adventure_domain_has_no_gameplay_actor_entry_point` 與 `::test_table_actor_cannot_modify_finalized_adventure`；M04 guide／description parity tests 皆在全套 backend 中通過 |
| F.6 zh-TW／en 同步：Review UI、warning／validation、MCP description | `adventureImporterCopy.ts` 與 `AdventureImporterPanel.test.tsx` 的 key parity、localized labels／error；`adventureImports.test.ts` 保留 server `params.warning_ids`，409 時兩語 UI 顯示 warning ids；`test_m04c_tool_descriptions.py`／`test_m04c_guide_tool_parity.py` |
| DM-only REST／UI、舊 JSON v1 相容、Standalone 邊界 | `test_p6f_review_api.py` 的 Owner／DM success、Member／cross-Room reject 與零副作用；`test_p6f_review_state.py::test_old_json_backward_compatibility`；E2E Player 無 Importer 且零 Import API request；全套 backend 內 `test_m03_import_boundary.py`／schema parity 通過；本 Subphase 無 migration 或 Python 相依變更 |

## 關門 gate

指揮者於 2026-09-23 在本機驗證。完整程式樹以 F5 `c3c71755` 加關門審核修正 `9bdf8864`、`f2153ef0` 為準；文件同步不改執行結果。

- Backend：`apps/server` 以專案 `.venv` 跑全套 `pytest`，exit 0、零 failed；未設定 PostgreSQL test URL 的既有 PG case skip。P6-F focused／code quality gate 於 F5 step 另跑並通過。
- Frontend：`apps/web` 全套 Vitest **103 files／775 tests passed**；`npm run build` 通過。
- `docker compose config --quiet`、`git diff --check` 通過。
- Docker E2E 使用獨立 `adventure_table_e2e`，`p6a-adventures.spec.ts`＋`p6e-importer-source.spec.ts`＋`p6f-import-review.spec.ts` **4 passed**；關門審核修正後 `p6f-import-review.spec.ts` **1 passed**，source locator 修正後 `p6e-importer-source.spec.ts`＋`p6f-import-review.spec.ts` **2 passed**。E2E 涵蓋 Adventure authoring／multi-attach、原 Importer 流程、Review／Finalize、Player 不可見。
- 真 PostgreSQL retry probe：在 Docker E2E stack 透過既有 Human REST 建 import／draft，對同一 import 與 `expected_revision` 連續 finalize 兩次；Adventure id 相同，import `target_adventure_id` 相同，目標 Adventure 僅一筆，status `finalized`。只操作專用 E2E 資料庫。

## 審核修正與邊界

- F5 已把原大型 Importer panel 拆成 Source、Review 與 pure helper；指揮者修正切換 import 的表單重掛、source／review sibling key、Source effect callback、Finalize 採最新 draft revision，以及 E2E fixture 與 selector。詳見 [F5 紀錄](P6-F_steps/F5.md)。
- 關門審核補齊 F3 留下的 `params.warning_ids` UI 顯示：Web API error 保留 ids；Finalize 收到 blocking 409 時，以 zh-TW／en 文案列出 ids，方便重載後定位警告。驗證 commit `9bdf8864`。
- View source 原本把任意 locator 的第一個數字當字元位移，可能把 PDF 頁碼誤當 offset；現在明確解析 `offset` 或以 extraction metadata 的 page／paragraph／heading index 對應 `start_offset`，未知 locator 回 source 起點。驗證 commit `f2153ef0`。
- F4a 將 current AI DM 的 importer authoring 限在 draft；Human Room owner／dm 仍可明確修正 finalized Adventure。此後續決策已同步 [P6 設計](開發設計方針.md) P6-F 與 [P6-A closeout](P6-A_CLOSEOUT.md) 的歷史敘述。
- 六個已定 MCP intent 不含 source 原文讀取工具；外部 AI 無法僅靠本組工具讀取 Human 上傳的 PDF／DOCX 原文。此為既定工具集合的範圍限制，不影響 Human Importer、手動 Draft 或六工具權限驗收。P6-G 的完整遊玩、restart／next Session 與真實 ChatGPT Web world-state gate 仍由 P6-G 驗證。

P6-F 關門驗證無剩餘 blocker；合併回 `main` 後進 P6-G。
