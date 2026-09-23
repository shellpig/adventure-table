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

（待填）
