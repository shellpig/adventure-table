# P6-A — Adventure Definition & Campaign Attachment · Closeout

日期：2026-09-20　Branch：`feat/p6a-adventure-definition`　Worker：agy（A1a、A1b、A1c、A2a、A2b、A3、A4a、A4b-1、A4b-2、A4c）、指揮者（A5）

## 驗收對應

| 契約 | 證據 |
|---|---|
| A.1 只 Name 可建立；八種 entry kind 可建；known kind invalid payload 被拒；freeform 合法 | `tests/test_p6a_adventure_authoring.py::test_owner_creates_adventure_with_only_a_name`、`::test_every_known_kind_accepts_a_valid_payload`、`::test_every_known_kind_rejects_an_invalid_payload`、`::test_unknown_kind_is_rejected`；E2E editor 建 scene／secret／suggested_check |
| A.1 draft 直接 finalize；draft attach 被拒、finalized attach 成功；finalized 仍可 authoring 修正 | `::test_finalized_adventure_still_accepts_authoring_corrections`、`test_p6a_adventure_api.py::test_finalize_then_archive_lifecycle`、`test_p6a_campaign_adventures.py::test_draft_and_archived_adventures_cannot_attach`；E2E finalize 後 Add Entry 仍在、draft attach 409 |
| A.1 world / gameplay service 不得改 finalized Adventure | `test_p6a_campaign_adventures.py::test_adventure_domain_has_no_gameplay_actor_entry_point`（Adventure service 只接受 `RoomAccessContext`，無 `TableActorContext` 入口；P6-B／D 的 world service 開工時再加正向拒絕測試） |
| A.1 attached finalized 不能 destructive delete | `test_p6a_adventure_api.py::test_delete_rules`；E2E `DELETE` attached → 409 |
| A.1 Human Player／AI Player 對任何 visibility 不可讀 | `::test_dm_can_write_member_gets_404_everywhere`、`test_p6a_adventure_authoring.py::test_dm_can_author_member_cannot_read_or_write`、`test_p6a_campaign_adventures.py::test_member_gets_404_on_attach_list_detach`；E2E member 進 `/adventures`／editor 看到無權限且零 API 呼叫、直接打 API 404。AI Player 走同一 `RoomAccessContext`／authority；P6-A 未 expose 任何 MCP tool，P6-C 加 read tool 時補 AI actor 明確測試 |
| A.1 Room A 不能讀／改 Room B | `::test_cross_room_adventure_is_not_found`、`test_p6a_adventure_api.py::test_cross_room_is_404`、`::test_entry_asset_link_rejects_cross_room_and_unknown_assets` |
| A.2 多重 attach、list 兩筆、無單一 active 限制、detach 剩一；cross-Room 拒絕；duplicate 契約 | `test_p6a_campaign_adventures.py::test_attach_two_adventures_and_list_in_order`、`::test_detach_leaves_the_other_attached`、`::test_duplicate_attach_is_409_with_zero_side_effects`、`::test_cross_room_adventure_and_campaign_are_404`、`test_p6a_postgres_migration.py::test_p6a_campaign_can_link_two_adventures`；E2E UI attach 兩個 → detach 一個 |
| A.3 空 Campaign regression | `::test_empty_campaign_still_starts_session_narrates_checks_and_fights`；E2E 零 Adventure Campaign：Start Session（UI）、narration（UI）、Player action、Request Check、Start Combat |
| A.4 image upload／read authority、dm_only projection、cross-Room 拒絕、invalid MIME／oversize 零 orphan、Room hard delete cleanup 與失敗定位、source_document 固定 dm_only | `tests/test_p6a_room_assets.py` 全部 13 tests（含 `::test_room_hard_delete_file_failure_keeps_locator_and_deletes_the_rest`、`::test_source_document_is_forced_dm_only`、`::test_member_sees_room_image_but_not_dm_only_image`）、`test_p6a_postgres_migration.py::test_p6a_source_document_visibility_check_constraint`；E2E 上傳 dm_only image → 縮圖經 authenticated blob fetch（`src` 為 `blob:`） |
| A.5 Standalone：M03 boundary 擴充、Standalone schema 無 Adventure／Asset table | A1a 擴充 `test_m03_import_boundary.py`（`room_assets?`／`adventures?` regex）與 `test_m03d_schema_parity.py`；全套 pytest 內通過 |
| 雙語 | `adventuresCopy.ts` 兩 locale 全部 key；`RoomAdventuresPage.test.tsx`／`AdventureEditorPage.test.tsx`／`CampaignAdventuresSection.test.tsx` copy parity |
| UI：Adventures workspace、editor、Campaign Attached Adventures | `RoomAdventuresPage.test.tsx`、`AdventureEditorPage.test.tsx`、`CampaignAdventuresSection.test.tsx`、`adventures.test.ts`、`roomAssets.test.ts`；E2E `p6a-adventures.spec.ts` |

## 關門 gate

- 全套 backend pytest（cwd `apps/server`，帶 `P4_POSTGRES_URL` 指向 docker `adventure_table_p4`）：1918 passed／39 skipped；`test_p6a_postgres_migration.py` 單跑 3 passed（非 skip）。
- `npm test -- --run`：95 files／564 passed；`npm run build`：成功。
- `docker compose config`：通過。
- 全套 Docker E2E（`ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1 npm run test:e2e:docker`）：`parallel` 兩輪各 95 passed／3 skipped／2 failed，失敗皆為 `p1f-character-creation`＋`p1g-level-up`（Builder review 未出現「No blocking issues」／Confirm 停在 disabled，既有 KI「Builder 等待」症狀）；`p6a-adventures.spec.ts` 兩 test 在 `parallel` 內通過。`baseline-room` 30 passed／1 skipped；`serial-restart` 1 passed。xge-less `m03c` 子集未重跑（P6-A 不碰 content pack，同 M05-B 處理）。
- Builder flake 追查：兩個 spec 在 `main`（fresh server-e2e）單跑 2 passed；在本 branch 長跑後的同一 server-e2e process 單跑仍失敗（1 failed／1 passed），`docker compose restart server-e2e` 後單跑 2 passed（8.5s）。判定為 server-e2e 長時間服務後的延遲退化，非 P6-A 程式差異；見下方觀察第 5 點。

## 指揮者審核修正摘要

- 後端 A1a～A3：見各 step 檔；主要為 RFC 6266 `Content-Disposition`、雙重 close、test-only `__post_init__` UTC workaround、私有 `_UNSET` 跨模組 import、`_to_view` 複製、fixture 未還原 app.state、alembic `fileConfig` 關掉 caplog logger。
- A4a：`useEffect` deps 含每 render 重新解析的 `recent` → 無限 fetch；create form 未走 `runMutation`。
- A4b-1（第二回合餵回同對話）：三處禁用 cast；`ability` select 顯示預設與送出值不一致（會 400）；表單未用既有 `label.room-field > span` pattern，label／textarea／checkbox 無樣式；parent 選項 fallback 顯示 UUID；kind 清單手寫重複。
- A4b-2：非 optional 欄位的防禦 guard；zh-TW `assetRoleLabel` '角色' 與 D&D 角色混淆 → '用途'。
- A4c：初次載入 effect 整段複製 `reload()`。

## 本 Subphase 技術決策（契約未指定；建議 verifier 同步 `開發設計方針.md`）

1. Asset upload 走 raw request body（`Content-Type` 為 MIME、`filename`／`kind`／`visibility` query），不用 multipart，避免新增 `python-multipart` 相依觸發發版清單重產。
2. 縮圖不用 `<img src=/assets/{id}/content>`（瀏覽器不帶 Bearer），改 `getRoomAssetContent` fetch blob → `URL.createObjectURL`，與 P3-B Stage image 同 pattern；不加 token query param、不改 server。
3. Duplicate attach 回 409 `adventure_already_attached`、零副作用（不採 idempotent 200）。
4. Adventure entry parent picker 只列 `section` entry（設計 §A.2「section tree / grouping only」）；server 只驗同 Adventure 且無循環。
5. Migration 單檔 `0031_p6a_room_assets_adventures` 五張表。

## 觀察到但不屬 P6-A 的事項（建議登記 `已知問題.md`）

1. 最小 editor 不編輯 `scene.exits`、`map.region_labels`、`other.data`、`npc.monster_template_ref`；patch 以表單重建的 `data` 覆蓋，這些欄位若由 Importer（P6-E）寫入、再經 UI 編輯同一 entry 會被清空。P6-E 開工時決定是否在 editor 補齊或 patch 只送變更欄位。
2. 每個 entry row 常駐一組上傳表單，entries 多時畫面偏長；縮圖 fetch 失敗只顯示在頁首 `form-error`。P8 Polish。
3. `AdventureList` 直接顯示 `updated_at` ISO 字串（與 Campaign 列表一致，未格式化）。
4. `KNOWN_ENTRY_KINDS` 與 `AdventureEntryKind` Literal 重複列舉 12 個 kind（可由 Literal `__args__` 推導）。
5. KI「Builder 等待」補充證據（Docker 路徑）：`p1f`／`p1g` 在整套 `parallel` 末段失敗，且在**同一個未重啟的 server-e2e** 上單跑仍會失敗；restart server-e2e 後立即 2 passed。已知問題條目原判斷「Docker 路徑 0/4、屬 Windows dev server 下游症狀」需修正為 server-e2e process 在長跑後回應變慢（Builder review 5 秒 timeout 內未完成）。建議 U01 後續量測 server-e2e 長跑後的 request latency，或在 E2E script 的 project 之間 restart server-e2e。
