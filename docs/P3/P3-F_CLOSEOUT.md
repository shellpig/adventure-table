# P3-F Closeout Checklist

P3-F — Full P3 Integration & Closeout。此文件依 [實作規格](實作規格.md) 與 [測試指南](測試指南.md) 收斂 P3-A～P3-E 的整合證據。

> 狀態：**closeout in progress**。Automated non-E2E / PostgreSQL / Windows standalone gate 已通過；Full-Stack E2E workflow 與 External MCP E1 HTTPS/TLS human gate 尚未執行，因此 P3-F / P3 **尚不可標為 closed**。

## P3-F implementation additions

P3-F 沒有新增 gameplay production surface；本階段以整合、regression、resource-safety 與 closeout evidence 為主。Static review 未發現需要修改 production code 的 blocker。

新增/更新：

- `.github/workflows/p3-e2e.yml`：`P3 Full-Stack E2E`，只允許 `workflow_dispatch`；clean rebuild 真 Docker stack、完整 Playwright、always-upload `p3-playwright-results`、always cleanup。
- `apps/web/e2e/p3f-full-integration.spec.ts`：跨 P3-A～E 的 Human full journey：Stage → `/action` / `/search` / `/ooc` / `/whisper` / `/check` → DM Request Check → formal roll → Current State → reload → End；驗 `/check` 不偷建 formal roll、secret DC 不洩漏、Current State 在 reload / End 後保留。
- `apps/server/tests/test_p3f_waiter_resource_safety.py`：production-like ASGI + 真 PostgreSQL 的 waiter starvation gate。DB pool 固定 `pool_size=2,max_overflow=0`，AnyIO worker limiter 固定 4；12 個 `/events/wait` 全部進入 async notifier wait 後，斷言 DB checkout=0 / worker borrowed=0；旁路 `/runtime` 仍即時成功；取消部分 waiter 驗 cleanup，再 publish durable event 喚醒其餘 waiter，最後 resource counters 回到 baseline。
- `.github/workflows/p3-non-e2e.yml` / `test_p3_workflow_contract.py`：P3-F 納入 post-review branch gate，required PostgreSQL suite 明確包含 P3-F waiter safety，並鎖 P3 E2E workflow contract。

## Static review gate

Static review 在 final non-E2E Actions 前完成。P3-F branch 對 `main` 的產品行為沒有另開第二套 gameplay path；Human / MCP 仍以 typed actor identity 進既有 application/domain authorization。Review 本輪實際抓到並修正的都是 closeout-test reliability finding：

1. P3-F browser journey 的 roll visibility enum typo：`roller_dm` → `roller_and_dm`。
2. waiter gate 原先以固定 sleep 猜測 waiter 進入等待，改成 counting notifier 明確等待 12/12 進入 async wait。
3. waiter gate 從 direct service proof 升級為 real ASGI route + real PostgreSQL。
4. 除 DB pool=2 外，再把 AnyIO/Starlette worker limiter 壓到 4，讓錯誤的 sync long-poll 會可靠 fail。
5. cancellation、durable publish wake、notifier handle cleanup、DB pool cleanup 都加入直接斷言。

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

### 1. P3 Full-Stack E2E

必須手動 dispatch `.github/workflows/p3-e2e.yml`，branch 選 `p3-f-full-integration-closeout`，取得：

- workflow name `P3 Full-Stack E2E`
- exact tested SHA / run id
- complete Playwright result
- `p3-playwright-results` artifact
- clean Docker rebuild / readiness / cleanup evidence

此 workflow 刻意保持 `workflow_dispatch` only；不得為了自動觸發而改成 push / PR trigger。

### 2. External MCP E1 over HTTPS/TLS

依 `P3-E_CLOSEOUT.md` 的 **External MCP auth / wire preflight** 執行。預定 external client：**Claude Code CLI 2.1.260（Windows）**；Codex CLI 0.147.0 已因 legacy `2025-06-18 initialize` preflight failure 排除。

E1 必須以真 HTTPS/TLS external endpoint + fresh scoped AI Join Token，並記錄：

- exact client name/version/platform/date
- static `Authorization: Bearer <AI Join Token>` 設定方式（secret 不進 repo/log）
- raw wire `MCP-Protocol-Version: 2026-07-28`
- `_meta.protocolVersion` / `clientCapabilities`
- `Mcp-Method` 與至少一次真 `tools/call` 的 `Mcp-Name`
- 不依賴 legacy initialize / `Mcp-Session-Id`
- context → event → action → formal roll/check → Take Back 或 End → next old-token call rejected

完成後需回寫 `P3-E_CLOSEOUT.md` 第 14 條為完成，並把本文件此項補成實際 evidence。

## Closeout status

- Automated implementation / static review：✅
- P3 Non-E2E：✅ (`34554209708` @ `d3251f2`)
- Real PostgreSQL concurrency/resource gate：✅
- Windows frozen standalone：✅
- P3 Full-Stack E2E：⏳ pending manual workflow dispatch
- External MCP E1 HTTPS/TLS：⏳ pending real external-client execution
- **P3-F / P3 overall：⏳ NOT CLOSED until both pending gates are green**
