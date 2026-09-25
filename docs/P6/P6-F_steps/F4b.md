# F4b — 六個 Importer MCP tool＋catalog／guide parity

## Scope

- `app/mcp/tools.py` 新增六個 `MCPToolDefinition`（薄 facade，沿 P6-D D4 模式：只做 input 驗證與 intent 轉發，不自行 parse 內容）：
  `import_adventure_source`、`get_import_draft`、`update_import_draft`、`resolve_import_warning`、`answer_import_question`、`finalize_adventure`。
- Authority：`roles=frozenset({"dm"})`、`pre_session=False`；facade 以既有 `_actor(token)` 取得 canonical `TableActorContext`，直接呼叫 F4a 的 service intent，不另做授權判斷。
- Tool input 直接組合既有 domain model／既有 service 參數，不新增第二套 schema；`import_adventure_source` 以 discriminated input 區分 text／url／asset source，對應 `add_text_source`／`add_url_source`／`add_asset_source`。
- mutation tool 的 `expected_revision` 一律 required。
- Tool description 雙語並進既有 M04 catalog／guide parity（`_WHEN_TO_USE`、`guide_tool_names.py`、`test_m04c_*`）。
- 不做 UI（F5）；不改 Player 工具集；不改 pre-session briefing cap。

## 契約與輸入

- 規格 P6-F（Importer MCP intent 清單、不放寬 pre-session grant）；設計 P6-F「Importer MCP tool names」；測試 F.5、F.6（MCP description locale）。前置 F4a。
- 參考：`app/mcp/tools.py`（`MCPToolDefinition`、`_TOOL_DEFINITIONS`、`_WHEN_TO_USE`、`call_tool` dispatch、`structured_tool_error`）、`app/domain/campaign_runtime/ai_tools.py`（facade 與 `_actor`）、`app/mcp/guide_tool_names.py`、`tests/test_p6d_mcp_tools.py`、`tests/test_m04c_tool_descriptions.py`、`tests/test_m04c_guide_tool_parity.py`。

## 驗收

- `tests/test_p6f_mcp_tools.py`（parametrize，沿 D4 模式）：catalog 含六個 tool 且只對 dm role 出現；Player role 呼叫被拒；pre-session／inactive Session／revoked grant／stale epoch × 六 tool 全拒且 `_snapshot` 前後相等；input 驗證錯誤映射 `invalid_arguments`；facade 輸出等於 service model dump；error mapping（stale revision／blocking）對應既有 machine code。
- `tests/test_m04c_tool_descriptions.py`、`test_m04c_guide_tool_parity.py`、`test_m04c_mcp_guide.py` 全綠（含新 tool 的雙語 description 與 guide 名稱）。
- 指揮者：P6-A～F regression。

## 完成紀錄

- **起始與 worker**：2026-09-23，agy（Gemini 3.8 Flash High），1 回合，CLI 回報約 817 秒；CLI status 為 `ERROR`，但最終報告完整、檔案齊全，指揮者以自己的測試結果為準。
- **交付**：新模組 `app/domain/adventure_imports/ai_tools.py`：`AdventureImportAIToolApplicationService(CampaignContextAIToolApplicationService)`（必填 `adventure_import_service`）與六個 tool input（`ImportAdventureSourceToolInput` 以 `source_kind` 區分 `paste`／`markdown`／`url`／`asset`，未帶 `import_id` 時 `name` 必填並先建 import；其餘五個直接組合 `ImportDraft`／`DraftWarning` 與 service 參數，mutation 的 `expected_revision` 皆 required）。`mcp/tools.py` 新增六個 `roles={"dm"}`、`pre_session=False` 的定義、雙語 description／when-to-use（`update_import_draft` 明示 AI 推論值用 `ai_generated`／`user_approximation`、可留 `DM decides`）、dispatch，以及錯誤對應：blocking → `adventure_import_blocking_warnings`（detail 為 warning id）、revision 衝突 → `adventure_import_revision_conflict`、Adventure domain 錯誤 → 既有 `not_found`／`permission_denied`／`invalid_arguments`／`table_conflict`。`mcp/dependencies.py` 改建新 facade，`guide_tool_names._EXPECTED`、`test_m04c_tool_descriptions.py` 的 DM catalog 加入六個名稱。新增 `tests/test_p6f_mcp_tools.py`（9 個 test function、46 cases）。
- **指揮者審核修正**：`import_adventure_source` 原本依是否新建回傳兩種不同 shape 並用 `# type: ignore`，統一為 `{import_id, source}`；finalize description 的「immutable」改為「baseline」（契約是 immutable-ish，owner／dm 仍可 authoring 修正），並補上 retry 回同一 Adventure；測試抽 `_call` helper、sample 參數表、以 `__getattr__` 記錄的 dispatch spy，合併 pre-session／player gate 與 invalid-arguments 測試，722 行縮為 429 行、斷言不減。
- **觀察（未修）**：(1) 新建 import 後若加 source 失敗，會留下空 import，DM 可取消；(2) 六個 tool 沒有讀 source 原文的工具，Human 上傳的 PDF／DOCX AI 無法經 MCP 讀取內容（超出規格列的六個 intent，若需要另開一步）；(3) 測試仍以覆寫 `_actor` 的測試 facade 取代 token 解析，沿 P6-D 前例，authority 由真實 service 與 fixture 驗證。
- **測試與證據**：指揮者在 `apps/server` 用專案 venv 執行所有 `test_p6*`、`test_m04*`、`test_m03*`、名稱含 `mcp` 的測試與 code quality gate（108 檔），**1070 個 0 failed**（18 skipped，皆為未提供 PostgreSQL URL）；全套 backend `pytest` **2606 個 0 failed**（78 skipped）；`git diff --check` 通過。驗證 code commit：`bce9459c`。
- **未解與下一步**：F5 UI（Draft Review、Warnings、Questions、Finalize、zh-TW／en、E2E），含 F3 留下的 `adventure_import_blocking_warnings` 文案。
