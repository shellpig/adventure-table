# P2-C Closeout Checklist

P2-C — Campaign & Party Roster closeout scope。編號對應 [實作規格](實作規格.md) 的「Campaign 完成條件」、「Party Roster 完成條件」與「State ownership」。

## Campaign 完成條件

- [x] 1. Owner 可在 Room 建立 / archive / select Campaign；持有 DM Key 不取得 Campaign lifecycle 權限。`_require_owner()` 沿用 P2-B 的 `room_owner_required` error code，member 與 DM 一律 403。
- [x] 2. Campaign status 為已拍板的 `draft` / `active` / `completed` / `archived`，並由 DB CheckConstraint `ck_campaigns_status` 鎖住。
- [x] 3. Campaign 最低建立資料只有 Name + Ruleset。沒有 `adventure_id`、沒有 Adventure stub、沒有 `leveling_mode` / `diagonal_rule` / `rules_json`。
- [x] 4. Room 可有多個 ongoing Campaign，但 `rooms.active_campaign_id` 一次只指向一個。`campaign.status` 與 `room.active_campaign_id` 是兩件事：把已選中的 Campaign 設為 `active` 不改變選擇，設為 `archived` 才連帶清除選擇。
- [x] 5. Campaign archive / lifecycle 不刪 Character。archive 只改 `campaigns.status` 並清 `active_campaign_id`；draft hard delete 只 cascade 掉自己的 roster 列。
- [x] 6. P2 未新增 generic Campaign Rules blob，也未持久化 `Leveling` / `Diagonal`。`campaigns` 的欄位就是 `id / room_id / name / ruleset / status / created_at / updated_at`，由 schema 契約測試逐欄鎖定。

## Party Roster 完成條件

- [x] R1. 只有 Owner / DM authority 可管理 Roster；member 的所有 Roster mutation 被拒。
- [x] R2. 只能加入同 Room Character。`add_roster_entry_same_room()` 在同一個 `engine.begin()` 內比對 `campaign.room_id` 與 `room_characters.room_id`，跨 Room 回 `character_not_in_room`。DB FK 只能證明 Character 存在，因此 same-Room invariant 由 service 在 transaction 內把關。
- [x] R3. 同一 Character 可同時存在多個同 Room Campaign 的 Roster。
- [x] R4. Roster status 不改 Character Current State，反向亦然。
- [x] R5. 沒有任何「未出席自動改 status」的路徑；status 只在明確的 PATCH 下改變。
- [x] R6. `retired` / `dead` 是保留資料的 status，不是刪除。
- [x] R7. 復活／回鍋就是把 status 改回 `active`，沒有 resurrection workflow。
- [x] R8. 不建立 Character ownership transfer。

Roster duplicate add 的契約選 **idempotent**：重複加入回傳既有 entry 而非衝突。並發下兩個 transaction 都可能看不到既有列而撞上 `(campaign_id, character_id)` unique key，敗方 rollback 後改讀已 commit 的勝方，不讓 IntegrityError 變成 500。

## State ownership

- [x] S. `Campaign Roster ≠ Campaign copy of CharacterState`。`campaign_roster_entries` 只有 `campaign_id / character_id / status / added_at / updated_at`，schema 契約測試明確斷言不存在 `state_payload` / `build_payload` / `inventory` / `hp`。Campaign A / B reference 同一 Character 時，HP、Inventory、Prepared Spell、Resource 四項各改一個代表值後，兩邊讀到同一份 `character_states`。

## 承接 P2-B 的未結清項目

- [x] **P2-B 驗收條目 13 的 history-reference guard 已補上對象。** P2-B 關門時 Campaign / Session 尚不存在，「已被 reference 就不得永久刪除」是空條件。P2-C 建立 Roster reference 後補上兩層保護：`campaign_roster_entries.character_id` 的 FK 為 `ON DELETE RESTRICT`（DB 層），以及 `_HistoryGuardedCharacterRepository` 在 Web 唯一的 permanent delete 路徑回 409 `character_history_referenced`（service 層）。Owner 的 Room Hard Delete 仍是明確例外，在同一 transaction 內先清 `active_campaign_id`、roster、campaigns，再刪 scoped Character。

## Verification evidence

分支 `p2-c-campaign-party-roster`，最終 code SHA `a6bbb18`。

```text
Branch / final code SHA
  p2-c-campaign-party-roster @ a6bbb18

Alembic heads
  0009_p2a_character_head (character) (head)
  0012_p2c_campaigns (web) (head)
  0012 接在 0011_p2b_room_workspace 之後，只落在 web track；
  standalone SQLite 仍只升 character@head，不會長出 Campaign schema。

Backend pytest
  1037 collected / 157 files，exit 0
  cwd apps/server，直譯器 ..\..\.venv\Scripts\python.exe
  執行於 3036cf7；3036cf7..a6bbb18 的 backend 差異只有還原一段 P2-B 註解與
  test_p2a_postgres_migration.py 的排版回復，未重跑全套。
  focused 重跑（a6bbb18）：test_p2c_*.py + test_p2a_migration_tracks.py +
  test_m03d_schema_parity.py + test_m03e_capabilities.py +
  test_m03_import_boundary.py + test_p2a_room_import_boundary.py → 29 passed

PostgreSQL gate（本機，對拋棄式 database）
  DATABASE_URL / P2_POSTGRES_URL 指向 compose db service 上另建的 p2c_gate database，
  跑完即 DROP，不動開發資料。
    test_p2a_postgres_migration.py::test_fresh_web_postgres_upgrade_heads_and_readiness
    test_p2a_postgres_migration.py::test_legacy_m03_postgres_upgrade_heads_preserves_character_payloads
    test_p2b_postgres_workspace.py::test_concurrent_cross_room_association_has_exactly_one_winner[character]
    test_p2b_postgres_workspace.py::test_concurrent_cross_room_association_has_exactly_one_winner[draft]
    test_p2b_postgres_workspace.py::test_concurrent_legacy_claim_never_splits_unscoped_workspace_data
  5 passed, 2.95s
  第一支測試已擴充 _assert_p2c_web_schema()，在真正的 PostgreSQL 上驗
  campaigns / campaign_roster_entries 存在、rooms.active_campaign_id 存在，
  以及 roster 兩個 FK 的 CASCADE / RESTRICT ondelete。

Frontend unit
  189 passed / 39 files

TypeScript / build
  npm run build（tsc --noEmit && vite build）exit 0

Full Web Playwright
  npm run test:e2e:docker exit 0 @ a6bbb18
  第一輪 105 tests：102 passed / 0 failed / 3 skipped（7.1m）
  第二輪 xge-less M03-C 子集：7 passed（6.4s）
  執行時 compose server 已在 0012_p2c_campaigns，
  /api/meta/capabilities 回 campaign:true，確認 E2E 是對 P2-C backend 跑的。
  本次全套無 KI-P1D-001 失敗。

docker compose config
  exit 0
```

### 驗收條目 → 測試對應

| 條目 | 證據 |
|---|---|
| 1 | `test_p2c_campaign_policy.py::test_campaign_lifecycle_is_owner_only`（member / DM 參數化皆 403 `room_owner_required`） |
| 2, 6 | `test_p2c_persistence_contract.py::test_p2c_campaign_schema_matches_contract`（欄位順序、`room_id` CASCADE、status CheckConstraint） |
| 3 | 同上：`campaigns.c.keys()` 逐欄鎖定，無 adventure / rules 欄位；`test_campaign_router_exposes_only_p2c_surfaces` 另確認 router 未提前長出 `/sessions`、`/lobby`、`/seats` |
| 4 | `test_p2c_campaign_policy.py::test_campaign_service_separates_status_from_room_selection` |
| 5 | 同上（archive 清 selection 不刪 Character）＋ `test_p2c_campaign_integration.py` 末段 draft hard delete |
| R1 | `test_p2c_campaign_policy.py::test_roster_management_allows_owner_and_dm_but_not_member` |
| R2 | `test_p2c_campaign_policy.py::test_cross_room_character_cannot_enter_roster`、`test_p2c_campaign_integration.py` 的 Room B Character 加入 Room A Campaign 被拒 |
| R3, S | `test_p2c_campaign_integration.py::test_real_campaign_rosters_share_one_character_state_and_preserve_history` |
| R4, R5, R6, R7 | 同上（status 改 `retired` 後 Character State 不變、archive Character 後 roster history 仍可 query）＋ `test_same_room_roster_is_idempotent_and_status_is_roster_only` |
| R8 | `test_p2c_persistence_contract.py::test_p2c_roster_schema_is_reference_only_and_protects_history`（roster 無 owner 欄位、無 state 欄位） |
| Roster idempotent | `test_p2c_campaign_policy.py::test_same_room_roster_is_idempotent_and_status_is_roster_only`、整合測試的 duplicate add |
| archived campaign / non-draft delete | `test_p2c_campaign_policy.py::test_archived_campaign_cannot_be_selected_and_non_draft_cannot_hard_delete` |
| P2-B 條目 13 補完 | `test_p2c_campaign_policy.py::test_web_character_delete_history_guard_blocks_roster_reference`、`test_p2c_room_hard_delete.py::test_roster_fk_restricts_direct_character_delete_and_room_delete_cleans_history_first` |
| Room Hard Delete 清除順序 | 同上（Room A 全清、Room B 的 Campaign / roster / Character / `active_campaign_id` 完好） |
| capability 旗標 | `test_p2c_capabilities.py` 兩條、`test_m03e_capabilities.py::test_web_capabilities_enable_room_and_campaign_for_p2c` |
| standalone 不長 Campaign schema | `test_m03d_schema_parity.py`（`campaigns` / `campaign_roster_entries` 已加入 `FORBIDDEN_MULTIPLAYER_TABLES`）、`test_m03_import_boundary.py`、`test_p2a_room_import_boundary.py` |
| migration track 分離 | `test_p2a_migration_tracks.py` 三條（`WEB_REVISIONS` 已納入 `0012_p2c_campaigns`） |
| 前端 route / 權限 / 文案 | `RoomCampaignPage.test.ts` 四條、`campaigns.test.ts` 三條、`routes.test.ts`、`hardcodedUiCopy.test.ts`（`RoomCampaignPage.tsx` 已納入掃描清單） |

## 關門過程中修正的問題

Static review 提出 7 項，6 項已修並重新驗證，1 項判定為非違規而保留。

1. **使用者可見文案洩漏內部 Phase 代號。** `campaignCopy.ts` 的 `eyebrow` 是 `P2-C · Campaign & Party Roster`，直接印在 Campaign 列表與詳細兩個畫面上。P2-B 才剛把 Room landing 的 eyebrow 拿掉，這裡又加回來且帶開發代號。已移除該 copy key 與兩處 JSX，並在 `RoomCampaignPage.test.ts` 斷言兩個 locale 的 copy 都不含 `P2-C`。

2. **誤刪 P2-B 的 race 註解。** `persistence/rooms/repository.py` 中說明「concurrent first-Room bootstrap 為什麼要當成 allocation conflict 重試」的五行註解被移除。行為未變但理由消失，且與 P2-C 無關。已還原原文。

3. **`test_p2a_postgres_migration.py` 被無關重排版。** 多個 `text("""...""")` 被壓成單行超長 statement，屬 P2-A 測試的格式 churn。已回復，相對 `main` 只剩 +24/-1 的 P2-C schema 斷言。

4. **`Lv{character.level}` 未進 copy table。** Roster 加入下拉是本檔唯一未本地化的使用者可見字串，兩個 locale 都顯示 `Lv`。已改用 `copy.levelLabel`（`Level` / `等級`），並把 `RoomCampaignPage.tsx` 納入 `hardcodedUiCopy.test.ts` 的掃描清單，避免同類遺漏再次發生。

5. **Roster remove 沒有確認。** 依設計 Roster 就是 Campaign history，移除是不可逆的，但 UI 是一鍵刪除。已加上 `window.confirm(copy.removeConfirm)`，文案雙語齊備並說明「稍後重新加入會建立新的名冊項目」。

6. **P2 Non-E2E workflow 未涵蓋本分支。** 已把 `p2-c-campaign-party-roster` 加進 push trigger 的 branches 清單。

7. **Server 不擋 archived Character 加入 Roster（保留，非違規）。** 前端靠 `listRoomCharacters` 預設 `archived=false` 過濾，但 `CampaignService.add_character()` 本身沒驗 archived。[實作規格](實作規格.md) 的 8.4 只要求「archived Character 不可成為新 Session selection」，那是 P2-E 的 Seat / Session 契約；P2-C 沒有任何條文禁止 archived Character 留在 Roster，而 archive 後 roster history 必須可查更是明訂要求。因此維持現狀，不在 P2-C 加上規格沒有要求的限制。P2-E 實作 Seat selection 時必須在 server 端擋 archived，不能沿用前端過濾。

## Boundary

- P2-C 不建立 Seat / Session / Lobby business logic，也不接 AI。`test_campaign_router_exposes_only_p2c_surfaces` 明確斷言 router 沒有 `/sessions`、`/lobby`、`/seats`。
- `campaign_seats`、`sessions`、`session_participants`、`active_character_session_leases` 一律不在 P2-C 建立；`0012_p2c_campaigns` 只新增 `campaigns`、`campaign_roster_entries` 兩張表與 `rooms.active_campaign_id` 一個 nullable 欄位。
- Campaign scope 不進 Character schema。Character core 不知道 Campaign 的存在，依賴方向維持 Room / Campaign → Character 單向。
- `_HistoryGuardedCharacterRepository` 刻意住在 `app.api.rooms.dependencies`，是 Web-only 的 delegating adapter，不把 Campaign history 觀念塞進 `CharacterRepository`。Standalone 的 `app.api.characters` 仍是未包裝的 Room-less 路徑，且 standalone SQLite 沒有 roster 表。
- Character JSON 保持 Room / Campaign-neutral，envelope 不含 `campaign_id`。
- `app.standalone` 不 import `app.main` 或任何 `app.*.rooms`。`test_m03_import_boundary.py` 的 `FORBIDDEN_MODULE_RE` 既有 pattern 已涵蓋新增的 `app.api.rooms.campaigns`、`app.domain.rooms.campaigns`、`app.persistence.rooms.campaigns`，本 Subphase 未擴充該 regex；`EXACT_PROTECTED_MODULES` 亦未變動。
- Adventure 不提前建立。P6 到來前不做 Adventure stub，也不用 raw string 假裝有 FK。

## 已知限制

- **P2-C 沒有自己的 browser journey。** [測試指南](測試指南.md) §13 的 Journey 4（Campaign / Roster）與 Journey 7（Cross-Campaign same Character）明訂為「P2-F 前至少要有」，因此不構成本 Subphase 的關門阻擋，且對應的後端契約已由整合測試覆蓋。但 `RoomCampaignPage` 目前只有單元測試層證據，瀏覽器層是空的：Campaign 建立、選擇、Roster 增刪與 status 切換都沒有真實後端的點擊路徑驗證。P2-D 或 P2-F 必須補上，不要拖到最後一次才一起撞。
- **Campaign status 沒有 transition 規則。** `PATCH /status` 接受任意四選一，包含 `archived → draft`。[實作規格](實作規格.md) 沒有定義狀態機，所以這不是違規，但 UI 也把四個 status 一字排開成四顆按鈕，Owner 可以把已完成的 Campaign 退回草稿。若後續 Phase 要讓 status 帶有實質語意（例如只有 `active` Campaign 能開 Session），需要在該 Phase 補 transition guard。
- **draft Campaign hard delete 會 cascade 掉它的 Roster。** 這符合契約（draft 且無 Session history 才可 hard delete），但 P2-C 沒有 Session，因此「無 Session history」目前恆真：一個已經加了整隊角色的 draft Campaign 仍可被 Owner 一次刪掉，UI 沒有顯示會連帶移除幾筆 roster。P2-E 建立 Session 後 `sessions.campaign_id ON DELETE RESTRICT` 會收緊這條路徑；在那之前建議 P2-F polish 補數量提示，與 Room Hard Delete 的同類問題一起處理。
- **`rooms.active_campaign_id` 的 FK 在 SQLAlchemy metadata 用 `use_alter=True`。** `rooms` 與 `campaigns` 互相 reference，`metadata.create_all()` 需要靠 ALTER 後補這個 constraint。Web 的真實建表路徑是 Alembic，`use_alter` 只影響測試用的 `create_all()`；但這代表兩者的建立順序不完全相同，日後若在 metadata 與 migration 之間再加迴圈 FK 要留意。
- **`_HistoryGuardedCharacterRepository` 以 `__getattr__` 委派並在 dependency 中直接改寫 `service.character_repository`。** 這讓 guard 不需要動 Character core，但它是屬性覆寫而非正式的組合點；`isinstance` 檢查會失效，而且一旦有第二處建立 `RoomCharacterWorkspaceService` 而未套上 wrapper，guard 就會靜默失效。目前全 codebase 只有 `get_room_workspace_service()` 一個建立點，已確認。若 P2-D / P2-E 新增 workspace service 建立點，必須沿用同一個 wrapper。
- **KI-P1D-001 未解。** 本次全套 E2E 完全綠燈、沒有出現該簽章，但根因仍未確認，[已知問題.md](../../已知問題.md) 的處置條文明訂不得以重跑通過推論根因已修復。
- **E2E global setup 的無條件 `DELETE FROM characters` 仍在。** 本次驗證期間為此先以 `pg_dump` 備份、跑完再還原真實資料。P2-B closeout 已記錄此限制，P2-C 未改變它。
- **P2-A 的 Room 層取捨全數延續。** throttle 為 process-local、`POST /api/rooms` 無 throttle 無授權、Room access token 以明文存 `localStorage` 且無到期機制。P2-C 未處理，亦未加深。
- **CI `P2 Non-E2E` 在最終 SHA 的 run 未於本機確認。** 本機沒有 `gh` CLI，無法查詢 run 狀態。workflow 的 push trigger 已涵蓋本分支，PostgreSQL gate 的實質內容已由上方本機 run 覆蓋；但若要照 [測試指南](測試指南.md) §16 用 CI run id 作為正式 evidence，需另行補上。

## Handoff

P2-C 已完成並關門。下一步是 **P2-D — Seat, Controller & Lobby**。

P2-D 直接繼承以下 substrate，不得再造第二套：

- **`CampaignService` 與 `CampaignRepository`。** Seat 是 Campaign-owned row，same-Campaign / same-Room invariant 應沿用 `add_roster_entry_same_room()` 的做法：在同一個 transaction 內比對，而不是在 API 層事後篩。
- **`_require_owner()` 與 `_require_roster_authority()`。** DM Seat assignment 是 Owner-only，沿用前者；Lobby / Roster management 沿用後者。記得 DM Key 本身不得 self-assign 到 DM Seat。
- **`_HistoryGuardedCharacterRepository`。** Session history 會讓更多東西變成不可硬刪；新的 history guard 應該加進同一個 wrapper，而不是在 Character core 開第二套檢查。
- **`RoomWorkspaceRepository.hard_delete_room()` 的清除順序。** P2-E 建立 Session 後，Session history 必須排在 Seat / Campaign 之前清除；現有的 `campaign_ids` 區塊已標好註解與位置。
- **`campaign_roster_entries` 的 status 語意。** Seat 的 `selected_character_id` 只可指向 `active` / `inactive` 的 Roster Character；`retired` / `dead` 與 archived Character 必須在 **server 端**拒絕，不能沿用前端的 `archived=false` 過濾（見「關門過程中修正的問題」第 7 項）。
- **`campaignCopy.ts` 與 `hardcodedUiCopy.test.ts`。** 新畫面的 copy 進同一種 locale table，並把新檔案加進掃描清單。
