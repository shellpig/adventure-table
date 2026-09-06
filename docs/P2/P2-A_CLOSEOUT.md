# P2-A Closeout Checklist

P2-A — Room Foundation & Web Entry closeout scope。編號對應 [實作規格](實作規格.md) 的「完成後必須為真」。

- [x] 1. Web 可以 Create Room。`POST /api/rooms` 回 201 與一次性憑證。
- [x] 2. Web 可以用 Room Password Enter Room。`POST /api/rooms/enter` 依 elevated key 給 `member` / `dm` / `owner`。
- [x] 3. Room code 格式／entropy、Password KDF 與 failed-attempt throttle 已固定並有測試：code 為 CSPRNG 產生的 10 碼 Crockford Base32（排除 I L O U）、canonical uppercase、lowercase 輸入可正規化；password 為 scrypt(N=2^14, r=8, p=1) + 32 byte salt，長度 6–128 code points，前後空白不被 silent trim；失敗以 `(room_code, remote_addr)` 計入 5 分鐘 fixed window，第 11 次起回 429 `room_access_throttled`，成功登入清窗，`X-Forwarded-For` 不被信任（只取 `request.client.host`）。
- [x] 4. Owner / DM elevated access 有可用的 MVP credential flow；raw key 只在 create response 出現，DB 只存 hash，DTO 不含任何 hash / salt。
- [x] 5. 已交付最小 RoomAccess heartbeat：`POST /api/rooms/{room_id}/access/heartbeat` 以 server time 更新 `last_seen_at`，不建立新 session、不 rotate token、不建立 Seat 或 game event。
- [x] 6. Web 首頁只提供 Create / Enter Room 與 Recent Rooms，不再從首頁提供 Character Workshop。
- [x] 7. Room 有最小可用 workspace shell（`/rooms/{roomId}`），後續 Subphase 可逐步加功能。
- [x] 8. Web capability `room=true`；Standalone `room=false`。`build_capabilities()` 單一來源，前端不散落 channel 判斷。
- [x] 9. Standalone 不 mount Room router；手動打開 `/rooms/...` 經 `protectedCapabilityForPath()` 得到 capability-disabled UX。
- [x] 10. 最後的 M03 realistic `unstable` fixture 已在修改 exporter 前由舊 exporter 產出並先行 commit（`cb86d7d`，早於切 v1 的 `b4457c8`）。
- [x] 11. Importer 可讀該 fixture 並 normalize 到 v1。
- [x] 12. M03 import-boundary gate 已對應 P2 實際採用的 module names，並證明 standalone reachable graph 不觸及 `app.*.rooms`。
- [x] 13. Alembic shared-character / web-multiplayer tracks 已分離；Standalone 只升 `character@head`，Web 升 `heads`。
- [x] 14. repo 中沒有會因 multiple heads 直接失敗的 repo-global single-head 假設；掃描由自動 gate 覆蓋 `.github/workflows/**`、`scripts/**` 與 `apps/server/tests/**`。
- [x] 15. M03 SQLite schema parity 已收斂成 explicit Character table allowlist，先 import Room tables 也不影響結果。
- [x] 16. `P2 Non-E2E` workflow 已存在並提供真 PostgreSQL migration gate。
- [x] 17. 既有 Web Playwright suite 與 `app.main` Character / Builder HTTP regression 在 Room-first 首頁上線後仍完整執行，仍作為 Web channel regression；沒有整批 skip / fixme。
- [x] 18. 未建立 Campaign、Seat、Session business logic。

## Verification evidence

分支 `p2-a-room-foundation-web-entry`，最終 SHA `d8f1354`。

```text
Branch / final SHA
  p2-a-room-foundation-web-entry @ d8f1354

Alembic heads
  0008_m03c_import_records (branchpoint)
    -> 0009_p2a_character_head (character) (head)
    -> 0010_p2a_web_rooms (web) (head)
  以 `alembic branches` 實測，非檔名推導。

Backend pytest
  993 collected, exit 0, 4 skipped
  cwd apps/server，直譯器 ..\..\.venv\Scripts\python.exe
  執行於 4d6e2cc；4d6e2cc..d8f1354 未觸及 apps/server 產品碼，故未重跑。

PostgreSQL migration gate
  tests/test_p2a_postgres_migration.py 2 passed
  本機 dedicated DB adventure_table_p2_test，P2_POSTGRES_URL / DATABASE_URL 同時設定
  覆蓋 fresh Web upgrade heads + readiness、legacy 0008 fixture upgrade heads 後 Character payload 等價

Frontend unit
  167 passed / 34 files

TypeScript / build
  npm run build（tsc --noEmit && vite build）exit 0

Full Web Playwright
  npm run test:e2e:docker exit 0
  第一輪 105 tests：102 passed / 0 failed / 3 skipped
  第二輪 xge-less M03-C 子集：7 passed
  第二輪能執行本身即代表第一輪通過（e2e-docker.mjs 在第一輪失敗時直接 exit）

Standalone import boundary
  tests/test_p2a_room_import_boundary.py：production standalone graph 不觸及 app.*.rooms
  negative fixture app.api.rooms.characters / app.domain.rooms.sessions 被抓，app.content.roommate 不誤判
  tests/test_p2a_standalone_room_boundary.py：standalone 不 mount /api/rooms，capability room=false

Fresh + legacy migration
  PostgreSQL：見上
  SQLite：alembic upgrade character@head → alembic_version = 0009_p2a_character_head，rooms / room_access_sessions 不存在（本機實測）

Character schema parity allowlist
  tests/test_m03d_schema_parity.py，含全套 backend pytest

Single-head assumption scan
  tests/test_p2a_migration_command_contract.py 4 passed
  掃 .github/workflows/**（.yml/.yaml）與 scripts/**（.py/.cmd/.ps1/.sh）的 `alembic upgrade head`
  AST 掃 scripts/** 與 apps/server/tests/** 的 get_current_head() / upgrade(..., 'head') / len(heads) == 1

Existing Web regression migration
  28 支既有 spec 改接 e2e/support/room.ts 的 enterRoom() / openCharacterWorkshop()
  全數在 Web channel 執行，無新增 skip / fixme

Room access authorization / throttle
  tests/test_p2a_room_access.py 12 tests
  含 wrong elevated key、code collision retry、password 長度邊界、token entropy、
  success 清窗、X-Forwarded-For 不可繞過、Room A token 打 Room B、revoked token、fake-clock heartbeat

Character JSON v1
  tests/test_p2a_character_json_v1.py 4 tests + tests/test_p2a_legacy_fixture.py 1 test
  e2e/m03b-character-export.spec.ts 瀏覽器下載實測 schema_version=1 / schema_status=locked / export_type=character

docker compose config
  exit 0（驗於 5907a80；docker-compose.yml 至 d8f1354 未再變動）

Known skips
  3 skipped：2 個為 m03c-character-import.spec.ts 保留給 xge-less 第二輪的案例（該輪已通過），
  1 個為既有 KI-M01J-001 的 test.fixme()
  4 個 backend skip 為既有 M03 條件式 skip
```

`P2 Non-E2E` workflow 已建立（`.github/workflows/p2-non-e2e.yml`，含 `postgres:17-alpine` service 與 `P2_POSTGRES_URL`），但本次 closeout 的 PostgreSQL 證據取自上列本機執行，未引用特定 Actions run id。

## 關門過程中修正的問題

驗證期間發現 7 項，全部已修並重新驗證。

1. **`enterRoom()` 用 `addInitScript` 常駐覆寫 locale，打壞六條 M02 測試。** `addInitScript` 對該 page 每次 navigation 與 reload 都重跑，而 `roomTest.ts` 把 `enterRoom` 註冊成 `auto` fixture，於是任何測試切到 `zh-TW` 後只要 reload 或 `openCharacterWorkshop()` 就被寫回 `en`。`m02a`、`m02b` 與四條 `m02h` 因此失敗。已改為讀取既有 locale、只在完全沒有時才點 `en`，helper 選擇器改成中英雙語 regex；並新增 `p2a-room-bootstrap.spec.ts` 的「locale 跨導覽與 reload 保留」回歸鎖。`playwright.config.ts` 的 `use.storageState` 本來就種了 `en`，該 init script 從一開始就是重複的。

2. **`m03b-character-export.spec.ts` 仍斷言 `schema_version === 'unstable'`。** backend 的 `test_m03b_export_api.py` 已同步改成 v1，同一份契約的 E2E 只改了 route 沒改斷言，切 v1 後成為確定性失敗。已改為 v1 期待並更新測試名稱。

3. **`.github/workflows/m01n-non-e2e.yml` 留著裸 `alembic upgrade head`。** 兩個 head 下實測 `FAILED: Multiple head revisions are present`。測試指南 §5.8 列的 8 個舊 workflow 都改對了，`m01n-non-e2e.yml` 是 P2 文件寫完後才新增的，不在那份清單裡。第一次修正改成 `heads`，但該步驟是 Fresh SQLite migration，實測會在 SQLite 建出 `rooms` / `room_access_sessions`，與 §5.5 相違且是 repo 裡唯一走 `heads` 的 SQLite 步驟；最終改為 `character@head`，與 `m03a` / `m03b` 對齊。

4. **single-head 靜態 gate 掃描範圍不足（第 3 項的根因）。** 原本只檢查 `README.md`、`docker-compose.yml`、`app/launcher.py` 三個檔，而 §5.6／§5.8 要求至少涵蓋 `apps/server/tests/**`、`scripts/**`、`.github/workflows/**`。已擴充成字串掃描 workflows / scripts 加上 AST 掃描 Python operational path。

5. **六個 Room error code 沒有進雙語 message SSOT。** `room_not_found` 等六個 code 只存在於 server API 層，前端把 `RoomApiError.code` 解出來後直接丟掉，一律顯示同一句「Room request failed.」，使用者無法分辨密碼錯、房號不存在與被 throttle 擋。已新增 `apps/web/src/i18n/roomMessages.ts`（6 code × `zh-TW` / `en`），`RoomLandingPage` 與 `RoomWorkspacePage` 改用 `localizedRoomRequestMessage()`，未知 code 的 fallback 不外露 raw code。

6. **測試指南 §6.1 有六條驗收條目沒有對應測試。** wrong elevated key 拒絕、code collision retry、password 長度邊界、`X-Forwarded-For` 不可繞過、success 清窗、token entropy。程式碼本來就正確，缺的是證據。已補齊，`test_p2a_room_access.py` 從 6 個測試增為 12 個。

7. **E2E globalSetup 沒清 P2-A 新增的 Room 表。** `roomTest.ts` 的 `enterRoom` 是 `auto` fixture，每條測試建一個 Room，跑一次全套 +105 且只增不減，驗證期間累積到 331 筆。實測影響：`rooms` 在 331 筆時 `character-builder.spec.ts` 連三次全敗，清空後回到偶發水準。已在 `e2e-global-setup.mjs` 補 `DELETE FROM room_access_sessions;` → `DELETE FROM rooms;`（順序不可反，後者被前者以 FK 參照）。

## Boundary

- P2-A 不建立 Campaign / Seat / Session business logic，也不做 WebSocket / Chat / Roll / AI Join Token。
- Room scope 不進 Character schema。Character JSON 保持 Room-neutral，envelope 不含 `room_id` / `room_code` / `campaign_id` / `seat_id` / `session_id`。
- Character branch ancestry 不含 web branch；跨 branch dependency 只允許 Web → Character，不做 merge revision。
- `app.standalone` 不得 import `app.main` 或任何 `app.*.rooms`。
- 舊 Web `/characters` 與 `/api/characters` 是**明確的 migration compatibility window**，只活到 P2-B。Web 首頁已不導流，P2-A 的 Room 功能沒有建立對 global Character identity 的依賴。

## 已知限制

- **KI-P1D-001 未解，且範圍比原記錄廣。** Builder 對 Draft 寫入後前端顯示沒跟上的競態，至少影響 `character-builder.spec.ts:133`、`m01e-half-elf-variants.spec.ts:60`、`m01m-mtf-tiefling.spec.ts:77` 三支 spec，失敗的是哪一支不固定。P2-A 驗證期間連跑三次全套，每次都剛好一條失敗，直到清掉 Room 殘留後才取得完整綠燈。本 Subphase 已同步擴大 `已知問題.md` 的登記範圍並改寫其處置條文（改為逐條核對失敗簽章），但**根因仍未確認**，最終那次綠燈不作為根因已修復的證據。它會持續影響 P2-B 以後每一次 Subphase 關門。
- **Throttle 是 process-local。** `FixedWindowThrottle` 存在 `app.state`，多 worker 部署下防護會被稀釋。P2-A 契約未要求共享儲存，留給實際需要多 worker 時處理。
- **`POST /api/rooms` 無 throttle、無授權。** 任何人可無限建 Room。契約未要求，但這是 Web 目前唯一無授權的寫入端點。
- **Room access token 存在 `localStorage`。** `adventure-table.recent-rooms.v1` 以明文保存 access token，屬朋友間私人專案可接受的取捨；沒有 refresh 或到期機制。
- **測試 fixture 會污染 `app.state`。** `test_p2a_room_access.py` 的 `_client()` 直接改 module-level `app.state` 且不還原，throttle 測試更把 fake-clock throttle 留在上面。全套目前綠燈，但屬於 M03-G closeout 已記錄的 `Settings()` 測試污染同一類順序相依風險。
- **PostgreSQL gate 沒有引用 Actions run id。** `P2 Non-E2E` workflow 已建立且可用，但本次證據取自本機 dedicated test DB。

## Handoff

P2-A 已完成並關門。下一步是 **P2-B — Room Character Workspace**。

P2-B 直接繼承以下 substrate，不得再造第二套：

- **Alembic 兩條 track。** 新的 shared Character migration 一律接在 `character` branch，Web multiplayer schema 一律接在 `web` branch；Web 升 `heads`、standalone 升 `character@head`。跨 branch dependency 只允許 Web → Character，不得建立 merge revision。
- **`e2e/support/room.ts` 的單一 Room bootstrap seam。** P2-B 只改 `openCharacterWorkshop()` 一處路由到 `/rooms/{roomId}/characters`，不逐一改二十多支 spec。同時要把 helper 內 P2-A transitional 的註解一併移除。
- **`roomMessages.ts` 的 error code → 雙語訊息對照。** P2-B 新增的 `room_required`、`character_not_in_room` 等 code 加進同一份 SSOT，不另開第二套。
- **`e2e-global-setup.mjs` 的資料清理。** P2-B 若讓 Character 綁 Room，要重新檢查刪除順序與 cascade——目前 `rooms` 在 characters / drafts 之後刪，一旦出現 Character → Room 的 FK 就需要調整。
- **single-head 靜態 gate。** 新增 workflow 或 script 若含 Alembic 指令，會被 `test_p2a_migration_command_contract.py` 檢查；SQLite 路徑請一律用 `character@head`。該 gate 目前只擋裸 `head`，抓不到「SQLite 誤用 `heads`」，P2-B 若想補這條規則可在同一個測試檔擴充。

P2-A 引入了實際的 `app.api.rooms` / `app.domain.rooms` / `app.persistence.rooms` package。P2-B 新增多人層 module 時，必須確認 `test_m03_import_boundary.py` 的 `FORBIDDEN_MODULE_RE` 仍能涵蓋新的命名，否則 gate 會靜默放行。
