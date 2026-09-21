# P6-C — AI Context & Retrieval · Closeout

日期：2026-09-21　Branch：`feat/p6c-ai-context-retrieval`（自 `main@a2e04387`）　Worker：agy（C1～C3）、指揮者（審核修正、C4 gate、closeout、合併）

## 驗收對應

| 契約 | 證據 |
|---|---|
| C.1 Compact session context：`get_session_context` 有 current scene／situation 摘要與 context tool hints，不含 Adventure body；M04 briefing cap 全綠 | `tests/test_p6c_mcp_tools.py::test_get_session_context_full_path`（AI DM：`campaign_context.current_scene.kind == "adventure"`、`current_situation`、`attached_adventure_count`、`next_context_tools` 含 `get_adventure_entry`、`world_entry_refs` 非空且 recursive key scan 無 `body`／`data_json`／`dm_notes`；AI Player：無 `attached_adventure_count`、`next_context_tools` 無 `get_adventure_entry`、序列化字串無 Adventure entry id／"Secret Room"；pre-session DM grant 無 `campaign_context`；兩 role `len(briefing) <= BRIEFING_MAX_CHARS`）；`test_m04c_briefing.py` 全綠（briefing 文案未改） |
| C.2 Relevant detail：scene context／search／get entry 可取到 Adventure＋Runtime 資訊；override 存在時 current truth 明確優先 | `test_p6c_context_service.py::test_override_truth_and_player_omission`（DM `SceneContextDmView` 同時有 `baseline`＋`override` 且 `current_truth == "override"`）、`::test_scene_ref_sources`（explicit adventure／runtime ref、Current Scene、無 Current Scene → no-scene view、invalid／foreign ref → `CampaignInvalidSceneRefError`）、`::test_active_combat_compact_ref`、`::test_empty_campaign_minimal_view`；`test_p6c_context_search.py::test_dm_override_and_source_truth_marking`（adventure hit `has_override`／`current_truth ∈ {override, baseline}`、runtime hit `"runtime"`）；`test_p6c_mcp_tools.py::test_facade_with_real_services`（五個 tool 輸出 == service `model_dump`） |
| C.3 Bounded query：大量 entries 下 limit／pagination／max payload 受控；空 query 不回整本 Adventure | `test_p6c_context_search.py::test_search_bounded_query`（120 Adventure＋60 Runtime entries：預設 20 hits＋`has_more`、`limit=50 offset=160` 收尾、snippet ≤ 160 字）、`::test_search_invalid_bounds`（limit 0／51、offset −1 → validation error）、`::test_search_empty_query_rejected`（空／空白／`\t\n\r` × DM／Player）、`::test_search_deterministic_and_pagination_stable`（同 query 兩次 JSON 相等；分頁串接 == 全量排序）；MCP 層 `test_p6c_mcp_tools.py::test_mcp_dispatch_validation_and_permission_failures[dm-search_campaign_context-…-invalid_arguments]`（`limit=51` schema 擋下、零 dispatch） |
| C.4 Projection：DM 可讀 Adventure／Runtime secrets；Player／AI Player 同 query 拿不到 secret entry id／title／body／source ref／存在提示／count side channel；任何 Adventure entry 不可由 Player context／search 取得或推導命中數 | `test_p6c_context_service.py::test_player_projection_secrecy`（Human／AI Player：序列化 JSON 無 `attached_adventures`／Adventure entry id／title／`dm_only`／`dm_notes`／他人 character）、`::test_player_get_adventure_entry_forbidden`（存在與不存在 id 同為 authority error）、`::test_dm_and_ai_dm_parity`；`test_p6c_context_search.py::test_dm_vs_player_projection_secrecy`（DM 命中含 adventure source；Player 只有 `CampaignSearchHitPlayerView`、count／`has_more` 只反映 public runtime、Player＝AI Player、DM＝AI DM）、`::test_player_secret_or_adventure_match_indistinguishable`（只命中 Adventure 或 dm_only 的 query 與完全無命中的結果除 `query` 外相等）、`::test_own_character_fact_search_projection`、`::test_search_kinds_filter`；結構證據：`search_campaign_context` 非 DM 分支不執行任何 adventure 讀取，Player result 無 total count 欄位；`test_p6c_mcp_tools.py::test_facade_with_real_services[ai_player_2_actor-*]`（recursive key scan 無 `attached_adventures`／`baseline`／`override`／`dm_notes`）、`::test_mcp_catalog_and_guide_tool_names`（Player catalog 無 `get_adventure_entry`）、`::test_mcp_dispatch_validation_and_permission_failures[player-get_adventure_entry-…-permission_denied]` |
| C.5 Authority lifecycle：AI grant revoke／controller epoch 改變後 context tool 立即失效；pre-session DM grant 不新增 P6 context | `test_p6c_context_service.py::test_authority_lifecycle_rejections_zero_side_effects`（inactive Session／revoked Human access／revoked AI grant × 四 intent，`_snapshot` 前後相等）；`test_p6c_context_search.py::test_authority_lifecycle_rejections_zero_side_effects`（＋`controller_epoch`：Seat `controller_epoch` 推進後 AI DM actor 被 shared active-actor gate 拒絕）；`test_p6c_mcp_tools.py::test_authority_lifecycle_at_facade_level`（revoked AI grant／controller epoch／inactive Session × 五個 tool，零副作用）、`::test_pre_session_auth_requires_active_session`（五個 tool 對 `session_id=None` 的 DM grant 回 `active_session_required`，零 dispatch）、`::test_get_session_context_full_path`（pre-session 無 `campaign_context`）；token 層失效沿用 P3-E `test_p3e_mcp_session_invalidation.py`／`test_p3e_mcp_token_lifecycle.py` |
| C.6 MCP read tool contract：catalog 固定含五個 tool 與 role set；全部 active-session only；`guide_tool_names.py`／catalog parity／English＋zh-TW description gate 全綠 | `test_p6c_mcp_tools.py::test_mcp_catalog_and_guide_tool_names`、`::test_mcp_dispatch_validates_and_delegates`（五個 tool 各 dispatch 一次、parsed input 型別正確）；`test_m04c_guide_tool_parity.py`、`test_m04c_tool_descriptions.py`（`PLAYER_ACTIVE`／`DM_CATALOG` 已納入五個名稱）、`test_m04c_mcp_guide.py` 全綠；`test_p6a_campaign_adventures.py::test_adventure_domain_has_no_gameplay_actor_entry_point` 放行契約固定的 `get_adventure_entry`，其餘仍禁 |
| 共用產品邊界：只新增獨立 `CampaignContextService`，`campaign_runtime/service.py` 零改動；Standalone boundary | `git diff main...HEAD -- apps/server/app/domain/campaign_runtime/service.py` 為空；`test_m03_import_boundary.py`、`test_m03d_schema_parity.py` 全綠；無新 migration（web head 仍 `0032`） |

## 關門 gate

Backend-only（`git diff main...HEAD -- apps/web` 為空），依 AGENTS 工程守則第 4 條不跑 E2E。

- 全套 backend pytest（cwd `apps/server`，未帶 `P4_POSTGRES_URL`）：見下方「執行結果」。
- 真 PostgreSQL：P6-C 無 schema／SQL 變更（search 為 Python 端比對，走既有 P6-B repository 讀取），沒有 P6-C 專屬 PG case；C4 步驟檔原列「PG case 非 skip」在 C2 派工時改為不適用，理由記於 [C2](P6-C_steps/C2.md)。
- `docker compose config --quiet`：通過。
- real composition smoke：`app.mcp.dependencies.get_ai_tool_application_service` 回 `CampaignContextAIToolApplicationService`，`campaign_context_service` 為 `CampaignContextService`。

### 執行結果

全部由指揮者於 2026-09-21 本機執行。

- 全套 backend pytest 於 code commit `094aeb26`（C3）＋docs `c95edf2c` 的 tree：2,095 passed／74 skipped（PostgreSQL／環境 skip）、0 failed、exit 0。
- C4 只再加 `controller_epoch` 測試案例（test commit `28bd076e`，改動限 `tests/p6_active_fixture.py`、`test_p6c_context_search.py`、`test_p6c_mcp_tools.py`），於最終 tree 重跑 `tests/test_p6*.py`＋`test_m04c_*.py`＋`test_code_quality_gate.py`＋`test_m03_import_boundary.py`：319 passed／12 skipped。
- `git diff --check` 通過。

## 指揮者審核修正摘要

- C1：Player 帶 `AdventureSceneRef` 原先先查 attach 再拋錯（可探測存在性）→ 非 DM 在任何 lookup 前即拋；移除未測試的 optional 注入雙路徑與吞錯 `try/except`；party 標籤 N+1 改批次；抽 `_project_for_actor`／`_related_aggregates`／`_campaign_or_404`。
- C2：三個 hit builder／兩個 sort key／DM＋Player 各自 sort-page-wrap 合併；`visibility` 改 Literal；清除搬移 fixture 後留下的 26 個未用 import。
- C3：facade 不從 `campaign_runtime` package re-export（避免 package import 拉進 combat＋rooms MCP 鏈）；測試呼叫鏈抽 `_invoke`、去 `object.__new__` 硬塞；failure kind 命名統一並加 `controller_epoch`；pinned M04-C catalog 與 P6-A MCP 名稱 guard 依契約更新。
- 三步共通：agy 每步都留下未用 import、且在跨檔搬移時不清來源檔；prompt 已要求仍未改善，審核 checklist 固定加一條 AST 未用 import 掃描。

## 本 Subphase 技術決策（契約未指定；建議 verifier 同步 `開發設計方針.md`）

1. Search 第一版為 Python 端 casefold token 比對（title＋body），不加 index／migration／SQL LIKE；bound 靠 `limit`（預設 20、上限 50）／`offset`／snippet 160 字／`has_more`，不回總命中數。
2. Player／AI Player 的 search 完全不執行 attached Adventure 分支，秘密不靠事後過濾。
3. `get_session_context` 的 P6 summary 走 `AIToolApplicationService._active_context_extension` hook（base 回 `{}`），P6 facade 覆寫；`CombatAIToolApplicationService` 既有的 override-then-extend 寫法未改。summary 只帶 scene／situation／DM-only adventure count／world entry refs（≤ 20＋truncated 旗標）／per-role `next_context_tools`；briefing 文案未改。
4. Scene／search DTO 分 DM／Player 兩套 model，不 null-fill；`SceneContextDmView.current_truth ∈ {baseline, override, runtime}`。
5. 共用測試 fixture 抽到 `tests/p6_active_fixture.py`（P6-B `ActiveFixture`／`active_fix`、C1 `context_seeded_fix`、`setup_authority_failure_actor`）。

## 觀察到但不屬 P6-C 的事項

1. `_active_context_extension` 每次 `get_session_context` 多跑一次完整 `get_campaign_context`（含 party／combat 查詢後丟棄）；search 每次載入 campaign 全部 runtime entries 與所有 attached adventure overlays。第一版契約允許，成為瓶頸再改 SQL／index。
2. Active-session briefing 未提五個 context tool（cap 2,240／3,000）；AI 目前靠 tool description 的 when-to-use 與 `next_context_tools` 發現它們。若 P6-D 觀察到 AI DM 不主動查 context，再在 briefing loop 加一句。
3. `test_p6c_mcp_tools.py` 349 行超過「≤ 元件兩倍」約束（facade 158 行），主因 `_DispatchSpy` 五個方法與 full-path 測試；未再壓縮。
