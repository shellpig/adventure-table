# P6-E — Adventure Source & Import Draft · Closeout

日期：2026-09-22　Branch：`feat/p6e-adventure-import`（自 `main@4c4943f5`）　Worker：agy（E1～E5）、指揮者（審核修正、gate、closeout、合併）

## 驗收對應

| 契約 | 證據 |
|---|---|
| E.1 Pasted / TXT / Markdown：normalize 後可 chunk 讀取、保留 source metadata／hash；重傳同一 source 依 contract idempotent | `tests/test_p6e_import_service.py::test_text_source_kinds`（paste／txt／markdown × str／bytes／BOM／CRLF parametrize：normalized text、sha256、metadata `filename`／`media_type`／`byte_size`／`line_count`／`char_count`、重傳回同一 source id 且 row 數不變、`list_sources` 不含 normalized text）、`::test_text_source_oversize_and_undecodable`、`::test_chunk_reading_boundary_and_validation`（offset／limit 邊界、結尾 `next_offset=None`、非法 offset／limit）；`tests/test_p6e_extraction.py::test_text_and_markdown_assets_reuse_normalization`；`tests/test_p6e_import_api.py::test_all_routes_happy_path_owner_and_dm`、`::test_raw_upload_mime_empty_and_size_limits_and_revision_conflicts` |
| E.2 PDF / DOCX：deterministic extraction 與 page／section／source locator；無文字不做 OCR 假裝成功，產 warning／empty extraction state 供 Human 補內容 | `tests/test_p6e_extraction.py::test_pdf_extraction_deterministic_locators`、`::test_docx_extraction_deterministic_locators`、`::test_docx_paragraph_index_preserves_gaps_from_empty_paragraphs`、`::test_extractors_preserve_normalized_leading_spaces`、`::test_empty_extraction_creates_warning_and_empty_state`、`::test_repeated_same_asset_is_idempotent_with_one_warning`、`::test_distinct_assets_with_identical_bytes_remain_distinct_sources`、`::test_unavailable_library_creates_warning_not_500`、`::test_media_mismatch_or_unsupported_rejected`、`::test_asset_handle_closure_guaranteed_on_rejection` |
| E.3 URL boundary：backend 不對 arbitrary URL 做 unrestricted fetch；提交 URL metadata＋normalized content 可成功；只有 URL 無內容時要求 Human／external AI 補 source，不暗中 crawl | `tests/test_p6e_import_service.py::test_url_source_invalid_scheme`（非 http(s)／無 host 拒絕）、`::test_url_source_with_text_and_without_text`（`socket.socket`／`socket.create_connection` monkeypatch 為 raise，兩條路徑仍成功＝零網路；無 content 時建 source＋stable warning `source:<id>:no_content`、status 停 `source`、同 URL 重送 idempotent）；`tests/test_p6e_import_api.py::test_json_url_source_boundary_no_network_fetch`；`tests/test_p6e_no_llm_boundary.py::test_adventure_imports_has_no_llm_or_network_dependencies`（AST 掃描：無 httpx／requests／urllib.request／openai／anthropic） |
| E.4 Draft revision：AI／Human update draft 需 expected revision；stale edit 拒絕；restart 後 draft／warning ids 不變 | `tests/test_p6e_import_service.py::test_draft_lifecycle_revisions_and_restart_stability`（首次 `expected_revision=0` → revision 1 且 import `source`→`drafting`；正確 revision 遞增；stale 拒絕且 draft／warnings／revision／status 全不變；dangling `source_ref`／warning `source_id` 拒絕；同一 SQLite 檔換新 repository／service 後 entry／warning／question id 逐字相同）、`::test_cancel_import_and_post_cancel_rejections`；`tests/test_p6e_import_persistence.py::test_upsert_draft_lifecycle_and_restart_stability`、`::test_import_status_update_with_revision_guard`、`::test_cascade_delete_import`；`tests/test_p6e_import_api.py::test_raw_upload_mime_empty_and_size_limits_and_revision_conflicts`（stale → 409） |
| E.5 No LLM backend／dependency boundary：importer module 無 model API client／API key setting／外部 LLM HTTP call；PDF／DOCX 套件只在 `web` extra，不進 base／Standalone；同一改動重產 constraints、跑 standalone build 與 frozen smoke，且兩者都不含 extraction 套件 | `tests/test_p6e_no_llm_boundary.py::test_adventure_imports_has_no_llm_or_network_dependencies`、`::test_ast_scanner_detects_forbidden_imports_and_api_keys`（掃描器自身反向驗證）；`tests/test_m03_import_boundary.py`（`FORBIDDEN_MODULE_RE` 已含 `adventure_imports?`，正向斷言 `app.domain.adventure_imports.service`／`app.persistence.adventure_imports.tables`）；`pyproject.toml` 兩套件只在 `[project.optional-dependencies].web`；E3 由指揮者重產 `constraints-standalone-win.txt`、跑 `scripts\build-standalone.cmd --version p6e-e3` 與 frozen smoke，constraints 與 frozen artifact 均不含 `pypdf`／`python-docx`（見 [E3 紀錄](P6-E_steps/E3.md)） |
| Draft 是 mutable review state 而非 Adventure truth；provenance 四值；parsed entry shape 對應 P6-A typed entry payload；warning／question stable id | `tests/test_p6e_import_schemas.py::test_import_draft_accepts_valid_entry_per_kind`（12 entry kind 重用 `parse_entry_payload`）、`::test_draft_entry_rejects_payload_kind_mismatch`、`::test_import_draft_rejects_duplicate_ids`、`::test_import_draft_rejects_dangling_and_self_parent_entry_id`、`::test_draft_entry_rejects_unknown_provenance`、`::test_import_draft_rejects_schema_version_not_one`、`::test_view_models_and_stored_conversions`；本 Subphase 完全不觸 `adventure_definitions`／`adventure_entries`（無 finalize 路徑，留 P6-F） |
| 沒有 AI 也能停在 Source 階段或由 Human 直接編 Draft | `AdventureImporterPanel.test.tsx`（四個案例：draft 新增／編輯／刪除保留 warnings／questions／id／provenance／`source_ref` 且不動 import revision；chunk 分頁與檔案正規化；雙語 copy parity、error mapping、localized label；權限 guard 與渲染結構）；E2E `p6e-importer-source.spec.ts`（Owner 建 import → 貼文字 → 看 chunk → 編 draft entry → reload 後保留） |
| 權限與可見性：DM-only；Player／非成員拒絕且零副作用 | `tests/test_p6e_import_service.py::test_authority_matrix`（10 個 public method × {room A member, room B owner} parametrize，零 row 寫入）；`tests/test_p6e_extraction.py::test_add_asset_source_authority_rejections`、`::test_cross_room_and_non_source_document_rejected`；`tests/test_p6e_import_api.py::test_authority_matrix_rejection_and_zero_side_effects`、`::test_cross_room_ids_never_leak_and_return_404`、`::test_json_source_validation_422_with_zero_side_effects`、`::test_raw_upload_compensating_delete_for_missing_and_cancelled_import`；E2E `p6e-importer-source.spec.ts`（Member 看不到 Importer 區且零 import 請求） |
| Supported locale 同步交付（zh-TW／en） | `adventureImporterCopy.ts` 全部 copy 雙語；`AdventureImporterPanel.test.tsx` 第三案例（key parity、非空、`importStatusLabel`／`sourceKindLabel`／`draftProvenanceLabel`／`entryKindLabel` 兩語系、error mapping）；REST validation／error 訊息沿既有 room machine code 路徑 |
| 共用產品邊界：Standalone boundary；schema parity | `tests/test_m03_import_boundary.py`、`tests/test_m03d_schema_parity.py`（三張新表列入 `FORBIDDEN_MULTIPLAYER_TABLES`）、`tests/test_migration_heads.py` 全綠；`tests/test_p6e_postgres_migration.py`（真 PostgreSQL `0033` upgrade／downgrade、status 與 source_kind CHECK、unique 與 cascade；無 `P4_POSTGRES_URL` 時 skip） |

## 關門 gate

diff 觸及 `apps/web`（E5），依 AGENTS 工程守則第 4 條跑全套 backend、全套前端、`docker compose config` 與 E2E；P4+ 各 Subphase 關門後即合併回 `main`，本次直接跑全套 E2E。

### 執行結果

全部由指揮者於 2026-09-22 本機執行，tree = `a164c5b0`（E5 code）。

- 全套 backend pytest（cwd `apps/server`，未帶 `P4_POSTGRES_URL`／`P3_POSTGRES_URL`）：**2,361 passed／78 skipped**、0 failed、exit 0（skip 全為 PostgreSQL job／環境 gate）。
- 真 PostgreSQL：`0033` 的 upgrade／downgrade 與 constraint case 住 `test_p6e_postgres_migration.py`，本機未帶 `P4_POSTGRES_URL`，與既有 P6-A／P6-B PG case 同樣以 skip 計。
- 前端：`npm test -- --run` **103 files／754 tests passed**；`npm run build` 通過。
- `docker compose config`：通過。
- `git diff --check`：通過。
- Standalone：E3 已重產 `constraints-standalone-win.txt` 並跑 `build-standalone.cmd --version p6e-e3` 與 frozen smoke；E4／E5 未再改 Python 相依，不重跑。
- 全套 E2E（`npm run test:e2e:docker`，`ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1`，detached 無參數執行）：`parallel` 98 passed／3 skipped／**3 failed**（`m05-session-history`、`p1f-character-creation`、`p1g-level-up`，6.0m），script 因此中止，其餘由指揮者逐一補跑並全部通過：
  - 重啟 server-e2e 後單跑 `m05-session-history` 與 `p1g-level-up`：2 passed；
  - 單跑 `p1f-character-creation`：**1 passed**（本輪未重現 KI-P1F-001）；
  - `--project=baseline-room`：30 passed／1 skipped；
  - `--project=serial-restart`：1 passed；
  - xge-less `m03c-character-import`（依 script 流程停用 xge 後執行，完成後已還原完整 pack list 並確認 `server-e2e` healthy）：7 passed。
  - P6-E 新增的 `p6e-importer-source.spec.ts` 在 parallel 一次通過。

## 指揮者審核修正摘要

- E1：`upsert_draft` 插入路徑移除多餘 savepoint／IntegrityError 猜測分支，改為 revision 檢查＋import 存在檢查後直接 insert；`warnings_json` 型別收斂；測試檔中段 import 上移、移除未使用 import。
- E2：抽出 `_import_in_room`／`_writable_import`／`_check_source_size`／`_add_source`／`_append_warning_in_transaction`，消去 `add_text_source`／`add_url_source` 近乎相同的 60 行與四處重複 import 查找；移除 Literal 已保證的二次檢查與 `or ""` 防禦讀取；**修正 URL-only source 的 sha256**（見下方技術決策 2）。
- E3：修拒絕路徑 file handle 未關閉、DOCX locator 壓縮後失去原 paragraph index、extractor 額外 `.strip()` 破壞 leading spaces、`add_text_source` 不必要暴露 `asset_id`、warning fallback 假值；補新 public method 的 MEMBER／跨 Room 零副作用 authority matrix。
- E4：補 manual TypeAdapter validation 的 FastAPI 422 mapping、response／input TypeScript shape 分離、production dependency cache 測試、source list 不洩漏 normalized text 與 raw upload 補償刪除證據；補 raw filename 255 字元上限。
- E5：修 E2E heading 文案、entry kind 由 machine value 改 localized label、metadata 白名單改用真實 key `byte_size`、`entryPayloadFromForm` 參數型別收斂、移除 dead return 並以 `key={roomId:token}` 重掛避免舊 Room 請求；移除 `AdventureEditorPage` 的 re-export shim，Editor 測試改直接 import `AdventureEntryPayloadFields`。
- 五步共通：agy 每步仍留未使用 import 或防禦式寫法；審核固定跑 AST 未用 import 掃描與 optional-everything 檢查。

## 本 Subphase 技術決策（契約未指定；建議 verifier 同步 `開發設計方針.md`）

1. 六個 Importer MCP tool **全放 P6-F**；P6-E 只以 service／REST 驗測試指南 E.3 的 URL boundary。使用者 2026-09-22 拍板。
2. URL-only source 的 sha256 為 **`sha256("url:<url>")`** 而非空字串 hash：E1 的 `(import_id, sha256)` unique 會讓所有無內容 source 互撞，改後同一 import 可並存多個 URL-only source，且同 URL 重送仍 idempotent。有內容的 source（含 URL＋content）仍以 normalized text 的 sha256 為鍵。
3. Draft 首次 update 由 service 在同一 transaction 內把 import `source` → `drafting`；`get_draft` 在無 draft row 時回 revision 0 的空 draft 但**不寫入**。
4. `Settings` 新增 `import_source_max_bytes`（預設同 `asset_max_source_document_bytes`）與 `import_chunk_max_chars`（預設 8000）；chunk `limit` 超過上限或非正數一律 validation error，不靜默截斷。
5. PDF／DOCX 採 `pypdf` + `python-docx`，函式內 lazy import；套件缺失映射為 source warning 而非 500。
6. raw-body upload 先建立 `dm_only source_document` room asset，import 端失敗時補償刪除該 asset。
7. E5 Draft editor 為最小表單：Human 建立的 entry provenance 固定 `user_explicit`；Accept／Ignore／Mark uncertain、warning 分級 UI 與 Finalize 全部留 P6-F。
8. `AdventureEntryPayloadFields.tsx` 自 `AdventureEditorPage.tsx` 抽出，Adventure Editor 與 Importer 共用同一組 entry payload 表單與 `entryKindLabel`，不做第二套。

## 觀察到但不屬 P6-E 的事項

1. `AdventureImporterPanel.tsx` 1,241 行為單一元件，功能與測試皆通過，但 P6-F 加 Review／Finalize 前建議拆成 Source 與 Draft 兩塊。
2. `test_p6b_runtime_repository.py` 與 migration／parity 測試被 xdist 排進同一 worker 時會出現 `roll_requests → combat_entries` `NoReferencedTableError`；在完全不含 P6-E 檔案的組合下同樣重現，全套 pytest 不受影響，未修。
3. 本輪 `p1f-character-creation` 單跑通過，未重現 KI-P1F-001；該條目仍留在 `已知問題.md`，不因單次通過結案。
