# P6-B — Campaign Runtime World State · Closeout

日期：2026-09-21　Branch：`codex/p6b-campaign-runtime`（自 `main@8db7d851`）　Worker：agy（B1～B5e）、Codex（B6 E2E spec 與 gate 執行）、指揮者（審核、PostgreSQL 補驗、closeout、合併）

## 驗收對應

| 契約 | 證據 |
|---|---|
| B.1 Adventure NPC neutral＋Campaign override hostile：Adventure 仍 neutral、Campaign view hostile；刪／改 Runtime 不回寫 Adventure | `tests/test_p6b_adventure_overrides.py::test_neutral_source_npc_plus_hostile_override_preserves_source`、`::test_override_management_crud_lifecycle`、`::test_override_active_crud_lifecycle_and_events`；`test_p6b_runtime_service.py::test_source_attachment_validation`；前端 `CampaignChangesB5c.test.tsx` 以 request body 斷言 Override 不含 Adventure template title／body／data；E2E 第一條 journey：Override 後 Adventure entry 仍以原 title 顯示於 overlay |
| B.1 NPC optional `monster_instance_id`／`monster_template_ref`、Item `holder_ref=character` 只作 reference | `test_p6b_runtime_schemas.py::test_npc_refs_validation`、`::test_item_holder_kinds_and_target_combinations`；`test_p6b_runtime_service.py::test_item_holder_validation`。結構證據：`app/domain/campaign_runtime/*`、`app/persistence/campaign_runtime/*`、`app/api/rooms/campaign_runtime.py` 皆無 monster／inventory／character 寫入路徑的 import，`monster_instance_id` 只出現在 `payloads.py` 作為 UUID 欄位。無「更新 NPC 後 Monster HP 不變」的正向 assertion，見觀察第 1 點 |
| B.2 空 Campaign 直接建立 Runtime NPC／Scene／Fact／Quest，跨 reload 仍存在 | `test_p6b_runtime_repository.py::test_empty_campaign_create_get_list`、`test_p6b_runtime_service.py::test_empty_campaign_create_works`、`::test_quick_add_minima_and_immutable_kind_patch`、`test_p6b_runtime_schemas.py::test_quick_add_minima`；E2E 第二條 journey：零 Adventure Campaign → Session 內 Quick Add fact → DM／Player reload 後仍在 |
| B.3 Current context：null＋null、situation only、Adventure scene ref、Runtime scene ref 合法；雙 scene ref 拒絕；clear 後 Session 繼續 | `test_p6b_runtime_context.py::test_context_lifecycle_and_invariants`、`::test_context_reference_validation`、`::test_context_idempotency_and_events`；`test_p6b_runtime_api.py::test_context_management_crud`、`::test_invalid_and_dual_scene_references_in_context`、`::test_active_session_dm_context_lifecycle_and_events`；`test_p6b_postgres_migration.py::test_p6b_runtime_context_single_scene_check`（真 PostgreSQL check constraint）；E2E：Session 內 situation only、Session 外 Adventure scene ref＋clear |
| B.4 Knowledge／secrecy matrix（Current DM 全見；Human Player／AI Player 只見 public＋own character，無 dm_only／dm_notes／他人 character／Adventure entry），直接檢查 REST／serialized DTO | `test_p6b_runtime_schemas.py::test_projection_matrix_and_player_secrecy`、`::test_projection_call_safety_requires_explicit_keyword_audience`、`::test_projection_does_not_mutate_canonical_entry`；`test_p6b_runtime_service.py::test_pure_projection_matrix`、`::test_member_read_and_write_denied`；`test_p6b_runtime_active_service.py::test_active_read_matrix`（含 AI Player actor）、`::test_event_payload_allowlist_and_visibility_mapping`；`test_p6b_runtime_api.py::test_active_session_player_secrecy_matrix_list_and_item`（raw JSON key 集合）、`::test_active_session_dm_full_view`、`::test_player_cannot_list_get_or_write`、`::test_player_forbidden_from_overrides_context_and_overlays`、`::test_active_session_player_forbidden_from_overrides_context_and_overlays`；`test_p6b_adventure_overrides.py::test_player_and_ai_player_rejection`；前端 `SessionPlayerJournal.test.tsx` 十欄 Player DTO 白名單；E2E：Player browser 只收到 own-character／public quest＆fact，REST 回應無 `dm_notes`／`character_recipient_ids`／`needs_review`／`provenance_json`，且 Player 端零 `/runtime/context`、`/runtime/overrides`、`/adventure` 請求 |
| B.5 Concurrency：同一 entry／Current Situation 的兩個 expected revision 只能一個成功，失敗方 stable conflict，資料／event 零筆 | `test_p6b_runtime_repository.py::test_update_with_expected_revision`、`::test_stale_revision_conflict_and_unchanged_data`、`::test_sql_where_predicates_and_concurrency`；`test_p6b_runtime_service.py::test_stale_revision_and_validation_error_create_no_mutation`；`test_p6b_runtime_api.py::test_stale_revision_conflict`、`::test_stale_override_and_context_revisions`、`::test_rejected_requests_leave_row_revision_and_mutation_state_unchanged`、`::test_active_session_dm_crud_lifecycle_events_and_concurrency`；`test_p6b_runtime_context.py::test_context_rollback_and_conflicts`、`::test_postgres_context_concurrency_and_detach_race`；`test_p6b_adventure_overrides.py::test_stale_revision_conflict`、`::test_postgres_concurrent_detach_vs_override`；idempotency：`test_p6b_runtime_active_service.py::test_idempotent_retry_behavior`、`::test_idempotency_conflict_rejections`、`::test_160_character_idempotency_key_and_replay`、`::test_cross_session_committed_replay` |
| B.6 Detach blockers：只有 active override 與 Current Scene 指向該 Adventure 兩種阻擋，拒絕零副作用；清除後可 detach；`source_adventure_entry_id` provenance 不阻擋且 detach 後保留 | `test_p6b_adventure_overrides.py::test_detach_blocker_matrix`（含 provenance 不阻擋、detach 後保留）、`::test_sequential_detach_vs_override_race_prevention`、`::test_aba_recreation_prevention`、`::test_rollback_on_failure_leaves_clean_state`；`test_p6b_runtime_api.py::test_clear_removes_detach_blockers_via_api`（public DELETE 409 `campaign_adventure_detach_blocked` → 清除後 204）；`test_p6b_postgres_migration.py::test_p6b_adventure_overrides_uniqueness_and_detach_independence`；E2E 第一條 journey：Override＋Current Scene 同時存在 → Detach 被拒且卡片仍在 → 清除兩者 → Detach 成功、attach list 為空 |
| Human／AI DM parity；stale／revoked authority；inactive Session／non-participant／wrong scope | `test_p6b_runtime_active_service.py::test_human_and_ai_dm_parity`、`::test_rejection_matrix_zero_side_effects`、`::test_management_outside_session_regression`；`test_p6b_adventure_overrides.py::test_ai_dm_active_crud_success`、`::test_stale_or_revoked_actor_binding`、`::test_inactive_session_and_nonparticipant_and_wrong_scope`；`test_p6b_runtime_context.py::test_context_authority_and_actor_parity`；`test_p6b_runtime_api.py::test_active_session_nonparticipant_and_stale_and_scope_and_inactive`、`::test_active_session_blocks_mutations_but_allows_management_reads` |
| Stable error contract | `test_p6b_runtime_api.py::test_error_mapper_does_not_hide_unexpected_value_errors`、`::test_error_mapper_parameterized_matrix`、`::test_active_session_override_and_context_errors_matrix`、`::test_malformed_typed_payload_and_validation_422` |
| Migration `0032` 真 PostgreSQL、Standalone boundary／parity | `test_p6b_postgres_migration.py` 全部 7 tests（upgrade／downgrade 自 P6-A parent、check constraints、FK cascade／set null、idempotency unique）；B1 擴充 `test_m03_import_boundary.py` 與 `test_m03d_schema_parity.py`，全套 pytest 內通過 |
| 雙語 | `campaignRuntimeCopy.ts` 兩 locale 全部 key；`CampaignChangesPage.test.tsx`／`CampaignChangesB5c.test.tsx`／`SessionCampaignRuntimePanel.test.tsx`／`SessionPlayerJournal.test.tsx` copy parity；B5a locale 切換重取錯誤訊息 |
| UI：Campaign Changes、Session DM world panel、Player Journal | `campaignRuntime.test.ts`、`CampaignChangesPage.test.tsx`、`CampaignChangesB5c.test.tsx`、`SessionCampaignRuntimePanel.test.tsx`、`SessionPlayerJournal.test.tsx`；E2E `p6b-campaign-runtime.spec.ts` 兩條 journey |

## 關門 gate

全部於最後 code commit `0a52b93d`（docs commit `b0543385`）之後、對同一 tree 執行；E2E spec 為本 closeout 一併提交的 `apps/web/e2e/p6b-campaign-runtime.spec.ts`。

- 全套 backend pytest（cwd `apps/server`，未帶 `P4_POSTGRES_URL`）：2011 passed／74 skipped。
- P6-B 真 PostgreSQL 補驗（指揮者，`P4_POSTGRES_URL` 指向 docker `adventure_table_p6b_test`，`-n 0`）：`test_p6b_postgres_migration.py`＋`test_p6b_adventure_overrides.py`＋`test_p6b_runtime_context.py` 33 passed／0 skipped。
- `npm test -- --run`：100 files／718 passed；`npm run build`：成功（189 modules）。
- `docker compose config --quiet`：通過。
- 全套 Docker E2E（`ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1 npm run test:e2e:docker`，exit 0）：`parallel` 99 passed／3 skipped（6.0m，含 `p6a-adventures.spec.ts` 與新 `p6b-campaign-runtime.spec.ts` 兩條）；`baseline-room` 30 passed／1 skipped；`serial-restart` 1 passed；xge-less `m03c-character-import` 7 passed；server-e2e 已還原 full pack list。本輪 `p1f`／`p1g` 未再出現 P6-A closeout 記錄的 Builder 延遲失敗。
- 執行者：gate 由 Codex 於 2026-09-21 19:52～20:02 執行並在回傳後撞到額度上限；指揮者自 Codex transcript（`~/.codex/sessions/2026/09/21/rollout-…01a0c11e.jsonl`）與本機 `test-results/.last-run.json`、E2E 容器 recreate 時間核對結果，未重跑已通過的 gate。

## 指揮者審核修正摘要

- B1：無 `P4_POSTGRES_URL` 的 skip 被指揮者以隔離 DB 補跑，抓到 `VARCHAR(16)` fixture 先觸發 `DataError` 而未驗到 check constraint。
- B2a／B2b：canonical 同時持有 `state_json`＋`state`、Patch 可改 kind、projection audience 有不安全預設、非 dict `state_json` 被靜默替換；repository 靜默去重 recipient 與偷轉 tuple 的 `__post_init__` 一律移除，改為明確拒絕並補 regression。
- B2c-1／B2c-2：收回 campaign row lock 至 `CampaignRepository` connection-aware helper；projection 明示 `is_dm`／`controlled_character_ids`；`TableEventService` 改為 required dependency；補 inactive Session read gate、160 字元 key、跨 Session replay。
- B3a／B3b：補 ABA identity 防護（clear 不刪 row）、source／override payload kind 驗證、真 PostgreSQL detach race、stale Human／AI authority 與真實 revoke 後的 read／write／replay 拒絕。
- B4a～B4d：error mapper 不再把任意 `ValueError` 掩蓋成 422；直接核對 union response raw JSON key 集合；detach blocker 改走 public DELETE route 驗 409／204；Player 拒絕時 override／context／mutation／event durable state 零副作用。
- B5a～B5e：Player DTO 精確十欄白名單、無 active Character 時 character projection 整批拒絕（不是 UI hide）；封存取消 pending 卡死、Hazard 誤顯示 Edit、conflict reload 失敗被吞、event 早於 HTTP response 的等待提示卡住、重疊 load 舊回應覆蓋新狀態、authority loss 後在途 load 恢復 DM controls 等競態，以 monotonic load generation／invalidate 與明確 Retry contract 收斂；區分 mutation 失敗與「寫入已成功但 reload 失敗」，後者不以新 idempotency key 盲目重送。

## 本 Subphase 技術決策（契約未指定；建議 verifier 同步 `開發設計方針.md`）

1. Runtime context clear 不刪 row，只把 scene reference／situation 清空並推 revision，避免 clear→recreate 的 ABA 讓 stale revision 誤中；scene 切換時同一 patch 必須明確清除另一種 reference。
2. Active-session mutation 以 repository in-transaction helper 組合 mutation record＋world event＋current actor revalidation，不用 nested transaction；`TableEventService` 為 required dependency。
3. REST error mapper 只接受明確 domain／Pydantic validation error 映射到 422／409，未知 `ValueError` re-raise。
4. Player Journal 只列 public quest／fact 與 own-character knowledge；public scene／NPC／item 不進 Journal（留給 P6-C／D 的 Stage／context 呈現）。
5. Web 端 mutation 成功但 reload 失敗時關閉表單、保留最後正確清單並要求重新整理，不自動以新 idempotency key 重送。

## 觀察到但不屬 P6-B 的事項（建議登記 `已知問題.md`）

1. B.1「更新 Runtime NPC 不改 Monster HP／combat state、Item holder 不改 Character `inventory_state`」目前只有結構證據（runtime 模組無相關 import）與 reference 驗證測試，沒有「先建 Monster Instance／Character、更新 Runtime entry、再斷言 HP／inventory 不變」的正向測試。P6-D 接 write-back 時補。
2. Codex 在 E2E 回傳的同一 turn 撞到額度上限；transcript 保留完整輸出，但 Playwright `.last-run.json` 只反映最後一個 project（xge-less 子集）。若之後要靠 artifacts 而非 transcript 核對，建議 E2E script 為每個 project 指定獨立 `--output` 或保留 list reporter log。
3. `p1f`／`p1g` Builder 延遲失敗（P6-A closeout 觀察第 5 點）本輪未重現；KI 條目維持，尚無新資料。
