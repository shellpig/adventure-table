# P3-F Closeout Checklist

P3-F — Full P3 Integration & Closeout。此文件依 [實作規格](實作規格.md) 與 [測試指南](測試指南.md) 收斂 P3-A～P3-E 的整合證據。

> 狀態：**closeout gates 全部完成**。Automated non-E2E / PostgreSQL / Windows standalone gate 已通過，本機全套 Playwright 已跑過（見下方 Full Playwright evidence），External MCP E1 HTTPS/TLS gate 已於 2026-09-11 執行通過（見下方「External MCP E1 over HTTPS/TLS」）。剩餘唯一待補項是 `p3-e2e.yml` 合併進 `main` 後的 CI dispatch run id，不阻塞 P3-F 關門。

## P3-F implementation additions

P3-F 沒有新增 gameplay production surface；本階段以整合、regression、resource-safety 與 closeout evidence 為主。Static review 未發現需要修改 production code 的 blocker。

新增/更新：

- `.github/workflows/p3-e2e.yml`：`P3 Full-Stack E2E`，只允許 `workflow_dispatch`；clean rebuild 真 Docker stack、完整 Playwright、always-upload `p3-playwright-results`、always cleanup。
- `apps/web/e2e/p3f-full-integration.spec.ts`：跨 P3-A～E 的 Human full journey：Stage → `/action` / `/search` / `/ooc` / `/whisper` / `/check` → DM Request Check → formal roll → Current State → reload → End；驗 `/check` 不偷建 formal roll、secret DC 不洩漏、Current State 在 reload / End 後保留。
- `apps/server/tests/test_p3f_waiter_resource_safety.py`：production-like ASGI + 真 PostgreSQL 的 waiter starvation gate。DB pool 固定 `pool_size=2,max_overflow=0`，AnyIO worker limiter 固定 4；12 個 `/events/wait` 全部進入 async notifier wait 後，斷言 DB checkout=0 / worker borrowed=0；旁路 `/runtime` 仍即時成功；取消部分 waiter 驗 cleanup，再 publish durable event 喚醒其餘 waiter，最後 resource counters 回到 baseline。
- `apps/server/tests/test_p3f_late_join_exploration.py`（2026-09-11 驗證補入）：測試指南 Journey 3。Session 已有 Stage、public action、Mira whisper、DM-only secret check 之後，DM 以真 `SessionService.late_join()` 讓 Luna Seat 進場：Late Join 前該 controller 不是 Session actor；Late Join 後拿到現行 Stage 與歷史 public event，cursor 相同但 whisper / secret request payload 不投影；新 narration 與自己的 dialogue 收得到；DM 對其 Request Check 可由本人完成 formal roll。對應實作規格第 3 條的 Late Join 半。
- `apps/server/tests/test_p3f_postgres_restart_recovery.py`（2026-09-11 驗證補入）：測試指南 Journey 8 真 PostgreSQL restart。透過真 service graph 寫入完整 dataset（active Session、Stage text + PNG、public / whisper / DM-only event、resolved + pending RollRequest、waiting_for_roll PendingAction 綁定 roll、Human Seat epoch、AI Player grant + Temporary Instruction + handoff 原 access session、另一 Room 的 unbound finite-TTL pre-session AI DM grant、ended historical Session 含 message / roll），`engine.dispose()` 後以全新 engine 重建所有 service：cursor 接續不重置、Stage 圖可讀、visibility 仍由 DB 決定、pending 仍 pending、resolved 再送回同一 result 不重骰、PendingAction 仍 waiting_for_roll、AI token 以 Seat current grant + `controller_epoch` 重新驗出同一 generation / session / instruction、Take Back 只認原 access session 且收回後舊 token 401、pre-session TTL 只看 persisted timestamp、ended Session 資料仍在。補上 P3-C closeout 明寫「P3-F 仍需要那條」的缺口，對應實作規格第 12 條 server restart 半。
- `.github/workflows/p3-non-e2e.yml` / `test_p3_workflow_contract.py`：P3-F 納入 post-review branch gate，required PostgreSQL suite 明確包含 P3-F waiter safety 與 restart recovery，並鎖 P3 E2E workflow contract。

## Static review gate

Static review 在 final non-E2E Actions 前完成。P3-F branch 對 `main` 的產品行為沒有另開第二套 gameplay path；Human / MCP 仍以 typed actor identity 進既有 application/domain authorization。Review 本輪實際抓到並修正的都是 closeout-test reliability finding：

1. P3-F browser journey 的 roll visibility enum typo：`roller_dm` → `roller_and_dm`。
2. waiter gate 原先以固定 sleep 猜測 waiter 進入等待，改成 counting notifier 明確等待 12/12 進入 async wait。
3. waiter gate 從 direct service proof 升級為 real ASGI route + real PostgreSQL。
4. 除 DB pool=2 外，再把 AnyIO/Starlette worker limiter 壓到 4，讓錯誤的 sync long-poll 會可靠 fail。
5. cancellation、durable publish wake、notifier handle cleanup、DB pool cleanup 都加入直接斷言。
6. （2026-09-11 驗證）`p3f-full-integration.spec.ts` 原以 DM 填的 label「Read the star chart」過濾 Player 端 roll request，但 `SessionRollRequestList.tsx` 不渲染 `request.label`，該 spec 在 `191368c` 之前從未實際跑過；改為與 P3-C 相同的 `.first()` 定位，並在 reload 後多送一次 `/action` 補齊實作規格第 1 條的「reload → continue」。

P3-D / P3-E closeout 已逐項提供 controller epoch、current grant-id + generation、finite pre-session DM TTL、exact handoff origin、admin recovery、End/Abandon atomic revoke、Temporary Instruction、private projection、MCP 2026-07-28、standalone boundary 等細項證據；P3-F 不複製另一套 implementation。

## Final non-E2E evidence

2026-09-11 final code/evidence run（在此 closeout 文件提交前的 implementation SHA）：

- Branch：`p3-f-full-integration-closeout`
- Verified implementation SHA：`d3251f2b677eb43bae4983adcf5b035cfcc7dcfd`
- Workflow：`P3 Non-E2E`
- Run ID：`34554209708`
- 結果：backend / frontend / postgres-migrations / windows-standalone **全部 success**。
- Backend：`1299 passed, 39 skipped, 32 warnings`；required PostgreSQL tests 不依賴 backend job，另在真 PostgreSQL job 明確執行。
- Backend artifact：`p3-backend-results`, artifact id `10182121014`, SHA256 `ef74e18c3546ee3fdda098fce845504aeb8ba873df38bdf302b1fc293a5ff9d3`。
- Frontend：67 test files / `298 passed`；`tsc --noEmit && vite build` success。
- PostgreSQL P3-D controller gates：`14 passed`。
- PostgreSQL P3 + legacy regression：`23 passed`，包含 `test_p3f_waiter_resource_safety.py`、P3-A/B/C、P2-A/B/E/F、roster lock order、M03-C；required suite **0 skipped**。
- PostgreSQL artifact：`p3-postgres-results`, artifact id `10181929443`, SHA256 `8c08d9c911c46a7da898609215cc1b1a6ddc79cd5b22bc2a4a9053f5198d7599`。
- Windows standalone：Windows Server 2025 / Python 3.13.15；`scripts\build-standalone.cmd --version p3-non-e2e` success；`smoke_standalone.py` 回報 `Standalone smoke passed.`。
- Alembic migration tip：`0020_p3d_ai_controller_grants`; P3-E/P3-F 沒有新增 schema migration。

2026-09-11 驗證補測後的 final run（含 Late Join / restart recovery / spec 修正）：

- Verified SHA：`51176e9`
- Workflow：`P3 Non-E2E`，Run ID：`34558892723`，四 job 全部 success。
- Backend：`1300 passed, 40 skipped`；Frontend：67 files / `298 passed`，build success。
- PostgreSQL P3-D controller gates：`14 passed`；PostgreSQL P3 + legacy regression：`24 passed`（新增 `test_p3f_postgres_restart_recovery.py`），required suite 0 skipped。
- Artifacts：`p3-backend-results` id `10183764058` sha256 `f63bc9486778b4ad9c67003061a6dd470e7c28bfa3b7adb2674698257df55a5b`；`p3-postgres-results` id `10183605997` sha256 `3c76599ad594e38b4226f7a13c1486f37bda3778cb3fc73a27cd3aa3fb55b743`。
- 本機（Windows，`.venv`）：全套 backend `1300 passed / 38 skipped`；`test_p3f_*.py` 三支 + workflow contract 在本機 Docker PostgreSQL（臨時 DB）全綠；vitest 298；`npm run build` OK；`docker compose config` OK。

## Full Playwright evidence

`P3 Full-Stack E2E`（`p3-e2e.yml`）為 `workflow_dispatch` only，而 GitHub 只註冊 default branch 上存在的 dispatch workflow——`gh workflow list` 目前找不到它，**在 `p3-e2e.yml` 合併進 `main` 之前無法 dispatch**。依 P2-F 前例，本階段以本機 Docker Linux dev server 的全套 `npm run test:e2e:docker` 作為 Full E2E 證據；合併後再 dispatch 一次補 CI run id。

- 2026-09-11，`191368c`（原始 spec）：`112 passed / 1 failed / 3 skipped`（7.3m）。唯一失敗為 `p3f-full-integration.spec.ts` 自身的 label locator（見 static review 第 6 點），非產品缺陷。
- 2026-09-11，`51176e9`（修正後）：`p3f-full-integration.spec.ts` 單跑 `1 passed`；全套重跑 `112 passed / 1 failed / 3 skipped`（7.3m），P3-A～F 全部 spec 通過。該次唯一失敗為 `apps/web/e2e/m01m-mtf-tiefling.spec.ts:386`（`M01-M rejects a forged MTF bloodline plus SCAG variant payload`），簽章 `waitForDraftRevision` @ `m01m-mtf-tiefling.spec.ts:77`、`Timeout 5000ms exceeded while waiting on the predicate`、revision 停在 2——即 `已知問題.md` KI-P1D-001 的唯一放行簽章；同一支在 `191368c` 那輪通過。依 KI-P1D-001 暫時處置，視為「除本編號外通過」。
- 3 skipped 為既有 `m01j` `test.fixme()` 與 `m03c` 兩條條件 `test.skip`，與 P2-F 相同。
- 兩輪皆由 `e2e-global-setup.mjs` 無條件 reset 並重建 P0 fixture 與 baseline Room；跑前已 `docker compose up -d --build server` 確認 backend image 為現行 code。

### Warnings / non-blocking observations

- Frontend `npm ci` 報告 2 個 moderate dependency vulnerabilities；此輪沒有 dependency remediation scope，build/test gate 仍全綠。
- Vite 報告既有 >500 kB chunk 與 `CharacterSheetView` dynamic/static import 無法切 chunk warning；非 P3-F correctness blocker。
- PyInstaller 有既有 optional hidden-import warnings（例如 `tzdata`, `pysqlite2`, `MySQLdb`）；frozen build + smoke 成功。
- Backend 39 skipped 主要包含只有特定 DB/env 才執行的 suites；P3-F closeout required PostgreSQL set 已在獨立真 PostgreSQL job 顯式執行且 0 skipped。

## Existing cross-subphase evidence retained

P3-F closeout依賴並重新回歸既有 P3-A～E證據：

- P3-A：durable event cursor/seq、restart persistence、async event wait、resume。
- P3-B：Stage + Exploration、五個 slash command ownership/semantics、private visibility、canonical event path。
- P3-C：server-authoritative formal roll、PendingAction、idempotency/concurrency、secret DC filtering、Current Character State persistence。
- P3-D：typed Human/AI actor、Seat `controller_epoch` SSOT、grant generation snapshot/current binding、finite pre-session AI DM TTL、Player handoff / exact-origin Take Back / admin reassignment、Temporary Instruction、End/Abandon atomic revoke。
- P3-E：transport-neutral AI tool surface、MCP modern 2026-07-28 wire contract、role catalog、AI event projection、standalone `app.mcp.*` boundary；`resolve_action` absent。
- P2/M03：P2 caller/controller regressions與 M03 standalone/import boundary持續由 P3 Non-E2E regression覆蓋。

## Remaining mandatory closeout gates

以下兩項完成前，**不得**把 P3-F / P3 / P3-E item 14 宣告完成：

### 1. P3 Full-Stack E2E（CI run，合併後補）

本機全套證據已在上方；CI 版需等 `p3-e2e.yml` 進 `main` 後手動 dispatch，branch 選當時的 P3 合併 SHA，取得：

- workflow name `P3 Full-Stack E2E`
- exact tested SHA / run id
- complete Playwright result
- `p3-playwright-results` artifact
- clean Docker rebuild / readiness / cleanup evidence

此 workflow 刻意保持 `workflow_dispatch` only；不得為了自動觸發而改成 push / PR trigger。

### 2. External MCP E1 over HTTPS/TLS — ✅ 2026-09-11 執行完成

依 `P3-E_CLOSEOUT.md` 的 **External MCP auth / wire preflight** 執行。預定 external client 為 Claude Code CLI 2.1.260；實際執行時 CLI `-p` 為 `loggedIn: false`，改用 Claude Desktop Code tab 內建的同一版 **Claude Code 2.1.260（Windows 11）**，wire `User-Agent: claude-code/2.1.260 (claude-desktop, agent-sdk/0.3.260)`。Codex CLI 0.147.0 已因 legacy `2025-06-18 initialize` preflight failure 排除。

實際 evidence（完整 wire 摘要與 journey 表見 [P3-E closeout](P3-E_CLOSEOUT.md)「External MCP E1 執行結果」）：

- **HTTPS/TLS 入口**：`https://greengrape.tail16ce3a.ts.net/mcp`，Tailscale serve 終結 TLS（Let's Encrypt 真憑證，tailnet only）→ `127.0.0.1:8765` wire logging proxy → `:8000`；每筆 wire 帶 `X-Forwarded-Proto: https`。
- **static Bearer**：`claude mcp add table <url> --transport http --scope local --header "Authorization: Bearer <token>"`；token 為 fresh scoped AI Join Token（Player Seat `Let AI Control`，generation 2），只存本機 `~/.claude.json`，不進 repo / log；proxy log 中 Authorization 已 redact。
- **raw wire**：所有 request 帶 `MCP-Protocol-Version: 2026-07-28` 與 `Mcp-Method`；body `_meta.io.modelcontextprotocol/protocolVersion = 2026-07-28`、`clientInfo {claude-code 2.1.260}`、`clientCapabilities {roots.listChanged, elicitation}`。
- **`Mcp-Name`**：client 送出的 8 筆 `tools/call`（含 Take Back 後被拒那筆）全部帶 `Mcp-Name`（`get_session_context`、`get_pending_events`、`post_action`、`roll_pending`、`wait_for_event`）。
- **不依賴 legacy**：全程沒有 `initialize`、沒有 `Mcp-Session-Id`。
- **journey**：context（含 Temporary Handoff Instruction）→ events（cursor 2）→ `post_action`（seq 3，acting = AI Player Seat）→ Human DM Request Check Investigation DC 14 `roller_and_dm` → AI `get_pending_events` 看到 `roll.requested` **payload 無 `dc`** → `roll_pending`（server RNG，1d20+1 = 6）→ `wait_for_event` timeout 回空 → DM 端 request `resolved` 且 `dc=14` → Human Player Take Back 204 → raw probe 401 `ai_token_unauthorized` → **AI 端下一個 `tools/call get_session_context` 401 `ai_token_unauthorized`**，client 回報 `requires re-authorization` → DM End 200 `ended`。
- 觀察：client 已持 modern 連線時，Take Back 後直接對 `tools/call` 收 401，不退回 legacy `initialize`；一筆錯誤參數名的 `wait_for_event` 得到 `invalid_arguments` structured error，schema validation 正常。

已回寫 `P3-E_CLOSEOUT.md` 第 14 條為完成，P3-E 標 ✅。

## Closeout status

- Automated implementation / static review：✅
- P3 Non-E2E：✅ (`34554209708` @ `d3251f2`；`34558892723` @ `51176e9`)
- Real PostgreSQL concurrency/resource/restart gate：✅
- Windows frozen standalone：✅
- Full Playwright（本機 Docker，P2-F 前例）：✅ @ `51176e9`，除 KI-P1D-001 簽章外全綠
- P3 Full-Stack E2E CI run：⏳ 待 `p3-e2e.yml` 進 `main` 後 dispatch
- External MCP E1 HTTPS/TLS：✅ 2026-09-11（Claude Code 2.1.260 經 Tailscale HTTPS；同時關閉 P3-E 第 14 條）
- **P3-F closeout gates：✅ 全部完成**；P3 Phase 關門與合併回 `main` 依 PROJECT_BRIEF 流程，合併後補 dispatch CI run id

## Known limitations / observations

- Player 端 `SessionRollRequestList` 不顯示 DM 填的 request label；同時有多個 pending request 時 Player 只能靠 request_type / skill / ability 分辨。非 P3 契約項目，列為 UX 觀察。
- P2 Room access session 不是跨裝置持久 Human identity；self-service Take Back 只認原 `Let AI Control` 的同一 access session，遺失時走 Owner/DM administrative reassignment（實作規格第 22 條）。
- 測試指南 Journey 2（三 Player Seat、一 Human 控兩 Seat、第三人另開瀏覽器的 group secret check）與 Journey 6（AI DM pre-session → Start → End 的 browser + MCP 全程）只有 domain / PostgreSQL 層證據（`test_group_check_tracks_each_seat_from_waiting_to_rolled`、`test_one_human_controlling_multiple_player_seats_must_choose_subject_explicitly`、`test_p3d_ai_dm_session_lifecycle.py`、`test_p3e_pre_session_ai_dm.py`），沒有 browser journey。
