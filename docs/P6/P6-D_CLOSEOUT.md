# P6-D — AI DM Write-back & Exploration Integration · Closeout

日期：2026-09-22　Branch：`feat/p6d-ai-dm-write-back`（自 `main@10565217`）　Worker：agy（D0a～D5）、指揮者（審核修正、gate、closeout、合併）

## 驗收對應

| 契約 | 證據 |
|---|---|
| D.1 Human / AI parity：active Session 內 Human current DM 與 AI DM 走同一 service、相同 validation／event shape；Session 外 Human owner／dm 可 HTTP 管理 Runtime／override／context（有 audit／revision／campaign-scoped idempotency，不建 `session_events`、不 notifier）；AI 同情境拒絕 | `tests/test_p6d_world_service.py::test_human_and_ai_dm_event_shape_and_semantic_parity`、`::test_human_and_ai_dm_negative_validation_parity`、`::test_human_and_ai_dm_parity_all_eight_intents`、`::test_human_management_coherent_flow_all_eight_intents`（八 intent 管理路徑、mutation record／revision／actor audit、`session_events` 與 notifier 計數不變）、`::test_human_management_rejected_when_session_is_active`、`::test_unauthorized_actors_rejected_with_zero_side_effects`（Player／AI Player／revoked／stale／inactive；AI 無 active Session 拒絕）；`test_p6d_mcp_tools.py::test_human_ai_parity_smoke`（Human 直呼 service 與 AI 經 MCP facade 同 view shape、同 `world.entry.created`）；`test_p6d_stage_bridge.py::test_stage_bridge_human_ai_parity` |
| D.2 Atomic world + narration：world validation 失敗 → 無 world change、無 definitive narration；成功時 world event 與既有 `exploration.narration`／`session_messages(kind=narration)` 同在，無 `world.narration`；commit 失敗不留單邊 | `test_p6d_world_action.py::test_invalid_world_change_with_narration_rolls_back_everything`、`::test_forced_narration_projection_failure_rolls_back_world_and_events`、`::test_success_with_narration`（event 順序、`session_messages` row、kind 掃描無 `world.narration`）、`::test_success_without_narration`、`::test_extraction_regression_table_event_and_exploration_message_repos`（`append_in_transaction` 抽取後既有 public append 行為不變） |
| D.3 Idempotency：同 key retry 只成功一次、回同一 result；管理路徑靠 campaign-scoped mutation record 去重且無 event；active 路徑不重複 `world.*`／narration event | `test_p6d_world_service.py::test_idempotency_retry_succeeds_once_and_does_not_duplicate_events`、`::test_idempotency_retry_special_intents_active`、`::test_management_path_idempotency_retries`；`test_p6d_world_action.py::test_same_key_retry_and_conflicts`、`::test_concurrent_idempotency_window_lock_ordering`、`::test_reserved_internal_idempotency_prefix_rejected_with_zero_side_effects`；`test_p6d_stage_bridge.py::test_stage_bridge_idempotency_behavior`（沿 P3 Stage canonical 語意） |
| D.4 Ephemeral vs persistent：atmosphere narration 不強迫建 Fact；persistent request 建 Runtime／Override；`needs_review=true` 不阻塞後續讀取／流程 | `test_p6d_world_action.py::test_success_without_narration`＋既有 P3 `post_narration` 路徑未改；`test_p6d_world_service.py::test_set_needs_review_entry_and_override_does_not_block_reads`；D5 E2E `p6d-stage-and-review.spec.ts`（DM 標 needs_review 後 Player Journal 仍讀到 public fact 且無 badge） |
| D.5 Stage bridge：P6 asset bytes 於 application boundary 複製成既有 `room_stage_images`；`session_stages.image_id` 只指 stage image；P3 schema／`ExplorationStageService` contract 不遷移；Player 只讀合法 stage image，dm_only asset 不經 Stage helper／raw URL／storage_key 外洩 | `test_p6d_stage_bridge.py::test_stage_bridge_bytes_copied`、`::test_stage_bridge_delete_source_asset_independence`、`::test_stage_bridge_room_asset_validation`、`::test_stage_bridge_adventure_entry_asset_validation`、`::test_stage_bridge_runtime_entry_image_validation`、`::test_stage_bridge_dm_only_authority_matrix`、`::test_stage_bridge_player_read_projection`、`::test_stage_bridge_preserve_text_and_stale_revision`、`::test_stage_bridge_rest_endpoint_and_error_mapping`；`tests/test_p3b_*.py` 全綠（Stage contract 未改）；E2E `p6d-stage-and-review.spec.ts`（Player HTML 不含 asset id／`/assets/`） |
| D.6 Existing mechanics reuse：P6 world action 不自造 RollResult／Combat state；Runtime Item holder 不直接改 `inventory_state` | `test_p6d_world_service.py::test_runtime_item_holder_does_not_touch_character_inventory_state`；結構證據：`campaign_runtime/world.py` 無 roll／combat／character state import（`test_m03_import_boundary.py` 全綠）；Check／Combat 仍走 P3／P4 既有 MCP tool（catalog 未改，`test_m04c_tool_descriptions.py`） |
| D.7 Waiter：active Session 成功 world mutation 後既有 `wait_for_event` 被 notifier 喚醒；管理路徑不 notifier；cursor 語意不變 | `test_p6d_world_action.py::test_wait_for_event_awakened_by_notifier_and_cursor_ordering`；`test_p6d_world_service.py::test_human_management_coherent_flow_all_eight_intents`（notifier 計數不變）；`test_p6d_stage_bridge.py::test_stage_bridge_idempotency_behavior`（canonical notifier replay） |
| D.8 MCP write tool contract：DM-only catalog 固定含十個 tool；全部 active-session only；Player／pre-session DM／stale／revoked 拒絕；guide／catalog／雙語 description parity | `test_p6d_mcp_tools.py::test_mcp_catalog_and_guide_tool_names`、`::test_pre_session_auth_requires_active_session`、`::test_player_role_rejected_by_call_tool`、`::test_actor_rejection_zero_service_dispatch`、`::test_authority_lifecycle_zero_db_side_effects`（revoked_ai／controller_epoch／inactive_session × 十 tool，`_snapshot` 前後相等）、`::test_mcp_dispatch_validates_and_delegates`、`::test_missing_idempotency_key_maps_to_invalid_arguments`、`::test_malformed_input_maps_to_invalid_arguments`、`::test_facade_output_equals_service_model_dump`、`::test_error_mapping_through_call_tool`；`test_m04c_tool_descriptions.py`（`DM_CATALOG` 已納入十個名稱、`PLAYER_ACTIVE` 未變）、`test_m04c_guide_tool_parity.py`、`test_m04c_mcp_guide.py` |
| REST／UI surface（Session DM：可從 Adventure／Runtime image set Stage、`needs_review`；Player 不見控制；zh-TW／en 同步） | `apps/web/src/features/rooms/SessionStageAndReviewD5.test.tsx`（actions 非 null 才渲染、三組候選、submit 先 GET revision 再 PUT、409／403 路徑、entry／override toggle payload、markup 無 asset id／storage key、locale parity）；`SessionCampaignRuntimePanel.test.tsx` 既有 mount predicate 測試（Player／非 DM 不掛載）；E2E `p6d-stage-and-review.spec.ts` |
| 共用產品邊界：Standalone boundary；`app.content.*`／`app.domain.character*` 不觸多人層 | `test_m03_import_boundary.py`、`test_m03d_schema_parity.py` 全綠；無新 migration（web head 仍 `0032`）；共用 helper `require_active_table_actor` 住 `app/domain/rooms/table_events.py`（多人層內） |

## 關門 gate

diff 觸及 `apps/web`（D5），依 AGENTS 工程守則第 4 條跑全套 backend、全套前端、`docker compose config` 與 E2E；因 P4+ 各 Subphase 關門後即合併回 `main`，本次直接跑全套 E2E。

- 全套 backend pytest（cwd `apps/server`，未帶 `P4_POSTGRES_URL`／`P3_POSTGRES_URL`）：2,266 passed／76 skipped（全部為 PostgreSQL job／環境 gate）、0 failed、exit 0，於 `12264f20`（D5 code）tree。
- 真 PostgreSQL：P6-D 無 schema／migration 變更；D2 `append_in_transaction` 抽取與 D3 stage bytes 複製走既有 P3／P6-B repository，沒有 P6-D 專屬 PG case。
- 前端：`npm test -- --run` 101 files／734 tests passed；`npm run build` 通過。
- `docker compose config`：通過。
- `git diff --check`：通過。
- 全套 E2E（`npm run test:e2e:docker`，`ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1`）：見「執行結果」。

### 執行結果

全部由指揮者於 2026-09-22 本機執行。

- 全套 backend pytest：2,266 passed／76 skipped（`12264f20` tree）。
- 全套 E2E（`12264f20` tree，detached 無參數執行）：`parallel` 98 passed／3 skipped／**2 failed**（`p1f-character-creation`、`p1g-level-up`，5.7m）；script 因此中止，其餘 pass 由指揮者逐一補跑：`baseline-room` 30 passed／1 skipped、`serial-restart` 1 passed、xge-less `m03c-character-import` 7 passed（restore 後 server-e2e healthy）。P6-D 新增的 `p6d-stage-and-review.spec.ts` 與受影響的 `p6b-campaign-runtime`／`p3b-exploration-chat-actions` 均在 parallel pass 通過。
- 兩個失敗的處置：重啟 server-e2e 後單跑 `p1g` 通過；`p1f` 單跑仍失敗（Review 停在「1 blocking：Barbarian skill choice 未達所需數量」），**切到 `main@10565217`（P6-C merge，未含任何 P6-D 改動）以同一 Docker 路徑單跑同樣失敗**——屬 Builder E2E 的既有問題，非 P6-D regression（`已知問題.md`「附帶觀察」原判斷 Docker 路徑 0/4，現於 Docker 路徑可穩定重現，需獨立追查；建議 verifier 立條目）。

## 指揮者審核修正摘要

- D0a／D0b：只搬不改，AST 逐函式比對本體相等；清除搬移後留下的未用 import。
- D1：補 Human／AI event／validation shape 真實比對、互不污染的 revoked／stale case、八 intent 管理路徑與 retry；修正 override update 預設值誤清空未提供欄位；stale revision 驗證提升為完整 row／mutation／event／notifier 快照。
- D2：archive branch 傳入不存在的 `room_id` 且 update／archive／clear override 未執行——退回同回合修正；抽 D1／D2 共用 override intent conversion；campaign lock 移到 authoritative idempotency lookup 前；加入 reserved internal key 與完整 narration validation。
- D3：補 Adventure／Runtime source 的 image／map role gate、wrong-Room 與各拒絕路徑零副作用快照、canonical notifier replay 證據與 REST 精確 machine code；移除無關 export。
- D4：agy 把兩個 service 依賴宣告 `| None = None` 並在十個 method 各放 `is None → RuntimeError`——改 required；契約缺口：`world_set_current_context` 需要 context revision 但 P6-C 讀 tool 未回傳，`CampaignContextDmView` 補 `current_context_revision`；測試 100 行 if-chain 改 map，去重複 fixture 與未用 import；順手清 D3 三個 nit（共用 `require_active_table_actor`、無作用 re-raise、不可能分支）。
- D5：十二個新 action 欄位全 optional／panel 全 `?.()`——改 required 並加測試 fixture factory；兩個 toggle handler 抽共用；panel 229 行含兩個 JSX IIFE、三段複製 `<optgroup>`、raw id fallback——抽 `StageImagePicker`／`ReviewRow`／`SessionReviewList`；`aria-label` 蓋掉可見文字使 E2E 找不到按鈕——移除；E2E 漏 DM seat 補上。
- 六步共通：agy 每步仍留未用 import 或防禦式 `| None` 依賴；審核固定跑 AST 未用 import 掃描與 optional-everything 檢查。

## 本 Subphase 技術決策（契約未指定；建議 verifier 同步 `開發設計方針.md`）

1. 既有 P6-B REST route **不改接** `CampaignWorldService`：REST 與 world service 都委派同一 `CampaignRuntimeService`，已是同一份 backend logic。
2. `resolve_world_action` **只開 MCP**，不開 Human REST route；D5 可玩 loop 未發現需要。
3. 十個 MCP write tool 的 `idempotency_key` 一律 **required**（world／stage service 要求 key；P3 tool 的 optional 語意不套用）；tool input 直接組合既有 domain model（`RuntimeWorldEntryCreate`／`RuntimeWorldEntryPatch`／`SetAdventureOverrideIntent`／`ClearAdventureOverrideIntent`／`CampaignRuntimeContextPatch`／`GrantCharacterKnowledgeIntent`／`SetNeedsReviewTarget`／`ResolveWorldActionRequest`／`StageImageSource`）。
4. `CampaignContextDmView` 新增 `current_context_revision`（DM only；無 row 時 0，與 `stored_context_to_domain` 一致），供 `world_set_current_context` 取 `expected_revision`。
5. Stage bridge：三種 discriminated source（`room_asset`／`adventure_entry_asset`／`runtime_entry_image`）；Runtime source 只沿既有 `source_adventure_entry_id` linkage，不新增 image 欄位；bytes 經 `RoomAssetService.open_content_for_table_actor`（canonical `TableActorContext`，不偽造 `RoomAccessContext`）；Human REST `PUT .../sessions/{session_id}/stage/image-source`。
6. active-actor revalidation 共用 `require_active_table_actor(connection, actor, repository)`（`app/domain/rooms/table_events.py`），`CampaignRuntimeService`／`CampaignStageBridgeService`／`RoomAssetService` 三處共用。
7. D5 UI：picker 開啟時才 lazy load 候選（attached Adventure image／map asset、有 source linkage 的 runtime entry、Room image），option value 為不透明 key；submit 先 GET canonical stage revision 再 PUT；Stage 畫面更新沿既有 `stage.updated` event。
8. `resolve_world_action` 內部 idempotency 使用 reserved internal prefix 的衍生 key（action／narration event 各一），外部 key 不得使用該 prefix。

## 觀察到但不屬 P6-D 的事項

1. D5 picker 候選只在首次開啟載入；Session 中新上傳的 asset 需重新進入 Session 才出現。
2. D5 vitest 的 submit／toggle 案例沿既有 panel 測試慣例以 `executeActiveSessionMutation`＋spy 重演 action，未 render hook；hook 真實路徑只由 E2E 覆蓋。
3. `mcp/tools.py` catalog 一行一 definition 的慣例讓 >140 字元行由 92 增至 114；`test_p6d_mcp_tools.py` `_DispatchSpy` 十個同型 method 沿 P6-C 前例。
4. active-session briefing 仍未提 P6 write tool（cap 未變）；AI 目前靠 tool description 的 when-to-use 發現。若 P6-G 真 AI DM 驗收觀察到不主動 write-back，再加一句。
