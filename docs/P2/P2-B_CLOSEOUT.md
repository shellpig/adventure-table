# P2-B Closeout Checklist

P2-B — Room Character Workspace closeout scope。編號對應 [實作規格](實作規格.md) 的「完成後必須為真」。

- [x] 1. Web 新 Character Draft 必須在 `Room → Character Workshop` 建立。`app.main` 不再 mount global Character / Builder router，唯一入口是 `/api/rooms/{room_id}/character-builder/drafts`。
- [x] 2. Web Create Draft 從第一筆 persistence 起就有 Room workspace association。`RoomCharacterWorkspaceService.create_draft()` 在同一個 `engine.begin()` 內建立 Draft 與 `room_builder_drafts` 列。
- [x] 3. Web list Character / Draft / archived Character 只回傳目前 Room 的資料。`RoomWorkspaceRepository.list_character_ids()` / `list_draft_ids()` 以 association table join 過濾，不是在 API 層事後篩。
- [x] 4. 跨 Room 猜 UUID 不能讀、改、confirm、archive、export、level up、build edit 或刪除另一 Room 的 Character / Draft。16 個 endpoint 逐項驗 404。
- [x] 5. Create Draft Confirm 與 Room Character association 是同一個 authoritative transaction boundary。`TransactionBoundEngine` 讓既有 Character / Builder / Import 服務參與外層 transaction，commit / rollback 由外層唯一持有。
- [x] 6. Level Up / Build Edit / Correction Draft 自動繼承原 Character Room，API 沒有 target Room 欄位。
- [x] 7. Web Import 必須由 target Room 發起；成功後 character / repair draft 屬於 target Room。
- [x] 8. Web Character routes / UI 都帶 Room context。`/rooms/{roomId}/characters`、`/rooms/{roomId}/characters/{id}`、`/rooms/{roomId}/characters/{id}/versions`、`/rooms/{roomId}/character-builder/{draftId}`；global path 導回首頁或現用 Room。
- [x] 9. Web global Character / Builder API 不再提供可繞過 Room scope 的 list / mutation path。`GET /api/characters` 與 `POST /api/character-builder/drafts` 在 `app.main` 回 404；Standalone 原 Room-less endpoints 不受影響。
- [x] 10. Standalone 仍可使用 Room-less Character Workshop、Draft、Sheet、Version History、Import / Export。frozen smoke 通過。
- [x] 11. Room Hard Delete 可完整刪掉它管理的 Character / Draft，不留下 orphan，且不動其他 Room。
- [x] 12. P2 升級前既有 global Character / Draft 不得 silent delete。主要路徑是 Owner 在 target Room 的 owner-only migration card 明確 claim；zero-Room bootstrap auto-claim 只是相容捷徑。
- [x] 13. permanent individual Character delete 為 Owner-only 且要求先 archive。**Campaign / Session history reference 的部分在 P2-B 為空條件**，見「已知限制」。
- [x] 14. Web global Character / Builder path 收口後，既有 Web browser 與 HTTP regression 已改走 Room-scoped path 並全數通過，仍以 Web channel 驗證。

## Verification evidence

分支 `p2-b-room-character-workspace`，最終 code SHA `8dbbbe0`。

```text
Branch / final code SHA
  p2-b-room-character-workspace @ 8dbbbe0

Alembic heads
  0009_p2a_character_head (character) (head)
  0011_p2b_room_workspace (web) (head)
  以 `alembic heads` / `alembic branches` 實測。
  0011 接在 0010_p2a_web_rooms 之後，只落在 web track；
  standalone SQLite 仍只升 character@head，不會長出 Room schema。

Backend pytest
  1022 collected, exit 0
  cwd apps/server，直譯器 ..\..\.venv\Scripts\python.exe
  執行於 335ba95；335ba95..8dbbbe0 只觸及 apps/web，未重跑。
  5 個 PostgreSQL-only 測試在本機 skip，由下方 CI job 覆蓋。

P2 Non-E2E CI
  Actions run 34068353554 @ c40ea70，backend / frontend / postgres-migrations 三個 job 全 success
  postgres-migrations job 實際執行本機會 skip 的 5 個測試：
    test_p2a_postgres_migration.py::test_fresh_web_postgres_upgrade_heads_and_readiness
    test_p2a_postgres_migration.py::test_legacy_m03_postgres_upgrade_heads_preserves_character_payloads
    test_p2b_postgres_workspace.py::test_concurrent_cross_room_association_has_exactly_one_winner[character]
    test_p2b_postgres_workspace.py::test_concurrent_cross_room_association_has_exactly_one_winner[draft]
    test_p2b_postgres_workspace.py::test_concurrent_legacy_claim_never_splits_unscoped_workspace_data
  5 passed, 2.70s

Frontend unit
  180 passed / 37 files

TypeScript / build
  npm run build（tsc --noEmit && vite build）exit 0
  tsconfig.json 的 include 涵蓋 e2e/，E2E helper 的型別一併受檢

Full Web Playwright
  npm run test:e2e:docker exit 0 @ 8dbbbe0
  第一輪 105 tests：102 passed / 0 failed / 3 skipped（6.8m）
  第二輪 xge-less M03-C 子集：7 passed
  本次全套無 KI-P1D-001 失敗

Standalone build / frozen smoke
  scripts\build-standalone.cmd --version p2b-check
    STANDALONE_PYTHON 指向 CPython 3.13.13（發版契約要求 3.13，本機預設為 3.14）
    check_standalone_env.py 比對 constraints-standalone-win.txt 通過
    產出 dist\adventure-table-standalone-p2b-check.zip
  .standalone-venv\Scripts\python.exe scripts\smoke_standalone.py dist\adventure-table-standalone --timeout 30
    Standalone smoke passed.

docker compose config
  exit 0
```

### 驗收條目 → 測試對應

| 條目 | 證據 |
|---|---|
| 1, 9 | `test_p2b_room_character_api.py::test_web_global_character_and_builder_mutation_routes_are_closed` |
| 2 | `test_p2b_workspace_transactions.py::test_create_draft_and_room_association_commit_together` |
| 2（反向） | `test_p2b_workspace_transactions.py::test_create_draft_rolls_back_when_room_association_fails` |
| 3 | `test_p2b_room_character_api.py::test_room_a_cannot_use_room_b_character_or_draft_ids` 末段 Room A list 為空 |
| 4 | 同上，character 10 條 + draft 6 條全驗 404 |
| 5 | `test_p2b_workspace_transactions.py::test_bound_core_confirm_rolls_back_character_and_confirm_marker_with_outer_failure` |
| 6 | `test_p2b_acceptance_evidence.py::test_versioned_draft_inherits_character_room`（`level_up` / `build_edit` / `correction` parametrized） |
| 7 | `test_p2b_acceptance_evidence.py` 三條 import 測試：full character、missing refs repair draft、history-loss 與 dry-run |
| 8 | `roomCharacterRouting.test.ts`、`App.test.tsx::roomCharacterRouteFromPath`、`characterWorkspace.test.ts` |
| 10 | `test_m03_import_boundary.py`、`test_p2a_room_import_boundary.py`、frozen smoke |
| 11 | `test_p2b_review_guards.py::test_room_hard_delete_leaves_no_character_workspace_or_access_orphans`、`test_p2b_legacy_and_room_delete.py::test_room_hard_delete_removes_only_that_workspace_core_and_import_rows` |
| 12 | `test_p2b_legacy_and_room_delete.py::test_first_room_bootstrap_claims_existing_unscoped_character_data_atomically`、`::test_owner_claim_card_exposes_counts_only_and_claim_is_idempotent`、`test_p2b_review_guards.py::test_first_room_bootstrap_conflict_retries_the_whole_room_transaction`、`::test_legacy_claim_race_is_a_stable_conflict_not_a_500` |
| 13 | `test_p2b_acceptance_evidence.py::test_member_and_dm_can_archive_but_cannot_permanently_delete_character`（member / DM 皆得 403 `room_owner_required`；Owner 需先 archive） |
| 14 | `web_room_support.py` 的 `WebRoomTestClient` + 遷移後的 8 支既有 backend regression；`e2e/support/roomTest.ts` 的 Room proxy + 全套 Playwright |
| 7.1 association 唯一性 | `test_p2b_workspace_associations.py` 三條 |
| PostgreSQL concurrency | `test_p2b_postgres_workspace.py` 三條（CI） |

## Human smoke

依 [測試指南](測試指南.md) §17，P2-B 範圍為第 1–7、13、14 步，由使用者於 2026-09-07 在本機完整執行並回報通過。§17 列的四項 blocker 判準（誤刪 Room、進錯 Room、legacy data claim 到錯 Room、以為 Character 跨 Room 共用）均未構成阻擋。

過程中觀察到兩項 UX 議題，皆非 blocker，列入下方「已知限制」。

## 關門過程中修正的問題

驗證期間發現 4 項，全部已修並重新驗證。

1. **`page.request` 未被 Room fixture 代理，16 條 E2E 失敗。** `roomTest.ts` 只把 scoping proxy 套在 `request` fixture 上，`m01e` / `m01f` / `m01l` / `m01m` 共 14 處改用 `page.request.*` 直打 global `/api/character-builder/...`。global router 收口後這些呼叫回 404，四支 spec 共 16 條失敗。已新增 `roomPageProxy()` 覆寫 `page` fixture，使 `page.request` 套用同一組 namespace 改寫與 Authorization header。

2. **`m02h-bilingual-site-smoke` 的 ROUTES 仍是 global 前端路徑，3 條失敗。** 只有 `/characters` 被特判成 `openCharacterWorkshop()`，`/characters/{id}`、`/characters/{id}/versions` 與 Builder crawl 的 `/character-builder/{draftId}` 仍是 global。這些路徑會觸發新的 `LegacyWebCharacterRedirect`，其 `window.location.replace()` 在 `forceLocale()` 的 `page.evaluate` 執行中摧毀 execution context。已改為 `routes(roomId)` 並讓 Builder crawl 走 Room-scoped 路徑。

3. **移除 `window.fetch` monkeypatch 後，`m02a` 的頁內原生 `fetch` 漏接。** 第 1、2 項修正的同時，production code 把 `installRoomCharacterRouting()` 的全域 `window.fetch` 覆寫與 document click 攔截改成 `characterWorkspace.ts` 的顯式 Room context。`m02a-localization.spec.ts` 的 `readDraft()` 用 `page.evaluate` 內的原生 `fetch`，那是第三種既不經 `request` 也不經 `page.request` 的呼叫形態，於是回 404。已改用 `page.request.get()`。全 `e2e/` grep 確認頁內原生 `fetch` 僅此一處。

4. **Room heading strip 撐滿一個 viewport。** `.room-character-workspace-heading` 借用 `.workshop-page` 以對齊 Workshop shell，連帶繼承 `min-height: 100vh`。沒有 legacy migration card 可填時，它就是一整片空白並把 Workshop 推到摺線下。已在 `rooms.css` 補 `min-height: 0` / `padding-bottom: 0`，實測 heading 高度由 900px 降為 69.4px、Workshop hero top 由約 930px 降為 101px；同時在 `RoomCharacterWorkspacePage.tsx` 補上 `import './rooms.css'`，不再依賴其他 Room 頁面順帶把樣式載進 bundle。

## Boundary

- P2-B 不建立 Campaign / Seat / Session business logic，也不接 AI。
- Room scope 不進 Character schema。`0011_p2b_room_workspace` 只新增 `room_characters` / `room_builder_drafts` 兩張 association table，不改 Character core 欄位，也不在 migration 內猜哪個 Room 屬於哪個既有 Character。
- Character JSON 保持 Room-neutral，envelope 不含 `room_id` / `room_code`。
- `app.standalone` 不 import `app.main` 或任何 `app.*.rooms`。`test_m03_import_boundary.py` 的 `FORBIDDEN_MODULE_RE` 既有 pattern `(?:^|\.)(?:rooms?|sessions?|seats?|campaigns?|party_rosters?)(?:\.|$)` 已涵蓋 P2-B 新增的 `app.api.rooms.characters`、`app.api.rooms.character_builder`、`app.domain.rooms.workspace`、`app.persistence.rooms.workspace`，本 Subphase 未擴充該 regex。
- 新增的 `app.persistence.transaction_bound` 是 Room-neutral 的 persistence primitive，Character core 不知道 Room 的存在；依賴方向維持 Room → Character 單向。
- P2-A 的 transitional surface 已收口：Web global `/characters` 與 `/api/characters` 不再提供 list / mutation。

## 已知限制

- **驗收條目 13 的 history-reference 保護在 P2-B 是空條件。** Campaign 與 Session 要到 P2-C / P2-E 才存在，目前沒有任何 history 會 reference Character，因此「已被 reference 就不得永久刪除」無從驗證。現行保護只有 Owner-only 加上 archived-only 兩層。P2-C / P2-E 建立 reference 後必須回頭補這條 guard 與對應測試，不能因為 P2-B 已勾選就視為已完成。
- **Room Hard Delete 的確認 modal 沒有告知會刪掉幾個角色。** human smoke 期間使用者在 claim legacy data 之後刪除 Room，連帶永久刪除了兩隻角色。文案有寫「包括其中的角色與草稿」，但確認輸入框只要求輸入 Room 名稱，沒有顯示實際受影響的 Character / Draft 數量，也沒有先行提示匯出。行為符合契約（Room Hard Delete 是 Owner 的 destructive exception），但這是目前 P2 最容易造成不可逆資料遺失的入口，建議在 P2-F polish 補上數量顯示。
- **`display_name` 已收集但全站無任何呈現。** Create / Enter Room 表單都有「玩家顯示名稱（選填）」，值也存進 `room_access_sessions.display_name` 並在 `RoomAccessGrant` 回傳，但前端只送不讀，沒有任何畫面消費它。要到 P2-D 的 Lobby / Seat presence 才有去處。目前使用者填了會得到零反饋，建議 P2-D 之前先在欄位旁說明用途，或在 Room workspace header 顯示。
- **`characterWorkspace.ts` 以 module-level singleton 保存 Room context，且在 `App` render 期間設定。** 這取代了 P2-B 初版的 `window.fetch` monkeypatch，是明確的改善，但仍不是 React context；`configureCharacterWorkspaceApi()` 在 render body 內呼叫屬 render side-effect。目前只有單一 Room 同時 active，行為正確；若日後出現同頁多 Room 或 SSR，需改為真正的 context。
- **E2E global setup 現在無條件 `DELETE FROM characters`。** 舊版以「名稱開頭非 ASCII」保留專案擁有者自己的角色，新版移除該規則並改用 `ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1` 環境變數當閘門（CI 上以 `GITHUB_ACTIONS` 自動放行）。CI 跑在拋棄式 volume 上沒有問題，但本機開發者若在有真實資料的 DB 上設了這個變數，資料會直接消失。本次驗證期間即為此在 `e2e_backup` schema 手動備份與還原真實資料。
- **KI-P1D-001 未解。** 本次全套 E2E 完全綠燈、沒有出現該簽章，但根因仍未確認，`已知問題.md` 的處置條文明訂不得以重跑通過推論根因已修復。它會繼續影響後續 Subphase 關門。
- **P2-A 的 Room 層取捨全數延續。** throttle 為 process-local、`POST /api/rooms` 無 throttle 無授權、Room access token 以明文存 `localStorage` 且無到期機制。P2-B 未處理，亦未加深。

## Handoff

P2-B 已完成並關門。下一步是 **P2-C — Campaign & Party Roster**。

P2-C 直接繼承以下 substrate，不得再造第二套：

- **`RoomCharacterWorkspaceService` 與 `TransactionBoundEngine`。** 需要讓既有 neutral service 參與 Room transaction 時，沿用 `_bound_services()` 的做法，不要讓 Campaign / Roster 自己開第二套 transaction 管理。
- **`RoomWorkspaceRepository` 的 association 樣式。** Roster 與 Campaign 的 same-Room invariant 應該用同一種 association table join 過濾，而不是在 API 層事後篩。
- **`_require_owner()` 與 `room_owner_required`。** Campaign lifecycle 的 Owner-only 檢查沿用同一個 helper 與 error code，並記得 DM Key 本身不得取得 Campaign lifecycle 權限。
- **`web_room_support.py` 的 `WebRoomTestClient`。** 新的 Web backend regression 一律以 `app.main` 加 Room context 驗證，不改綁 `app.standalone`。
- **`e2e/support/roomTest.ts` 的三層 proxy。** `request`、`page.request` 都已代理；頁內原生 `fetch` 沒有代理層，新 spec 不要再用 `page.evaluate` + `fetch` 打 API。
- **`roomMessages.ts` 的 error code → 雙語訊息 SSOT。** P2-C 新增的 code 加進同一份，不另開第二套。

P2-C 若讓 Campaign / Roster 產生對 Character 的 history reference，必須同時補上本檔「已知限制」第一條所指的 permanent delete guard 與測試。
