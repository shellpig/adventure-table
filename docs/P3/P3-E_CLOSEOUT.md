# P3-E Closeout Checklist

P3-E — AI Tool Surface & Event Delivery closeout scope。編號對應 [實作規格](實作規格.md) 的「完成後必須為真」。**automated implementation gate 已全部收斂（含本機 E2E 與 external client wire preflight）；第 14 條真實 external MCP client E1 原依 2026-09-11 決定延至 P3-F closeout 與 P3-F 實作規格第 11 條合併驗收，已於 2026-09-11 P3-F closeout 期間以 Claude Code 2.1.260 經 Tailscale HTTPS 入口執行完成（見下方「External MCP E1 執行結果」），本 Subphase 至此關門 ✅。**

- [x] 1. Web channel 提供 `/mcp`，以 MCP `2026-07-28` modern stateless contract 為唯一基準；不要求 legacy `initialize` / `notifications/initialized`，也不建立 `Mcp-Session-Id` correctness dependency。`test_p3e_mcp_protocol.py` 鎖 protocol/header/meta/cache/error contract。
- [x] 2. 每個 MCP request 都重新以 Adventure Table AI Join Token resolve current scope。`authenticate_request()` 呼 `AIControllerService.authenticate(..., touch=True)`；transport 不保存 authorization session。`test_p3e_mcp_token_lifecycle.py` 直接驗 wrong secret、rotate/revoke、expired、wrong Seat、stale epoch。
- [x] 3. MCP handler 只作 adapter，action / roll / state / event 都委派既有 application/domain service。`test_p3e_architecture_boundary.py` 禁止 `app.mcp.*` / `ai_tools.py` 直接 import persistence mutation；`test_p3e_shared_action_integration.py` 與 `test_p3e_shared_roll_integration.py` 證明 Human / AI 共用 canonical state。
- [x] 4. AI Player context / events由 Server projection過濾。`test_p3e_ai_event_projection.py` 直接證明 DM-only / other-seat private payload不會出現在 AI Player結果，cursor仍按 durable raw sequence前進。
- [x] 5. AI DM只得到 DM-role table surface，不取得 Owner destructive authority，也沒有 Character Build mutation tool。`test_p3e_mcp_tools.py` 鎖 Player / DM / pre-session catalog；Room-management endpoint仍只接受 Human Room access context。
- [x] 6. P3 gameplay tool surface已包含 context、own Character、Dialogue / Action / OOC / Whisper、Narration、Stage、Request Check、formal/physical/quick roll、Current State、events / wait；role catalog由同一 `_TOOL_DEFINITIONS` 產生。
- [x] 7. Temporary Handoff Instruction只在有效 generation context中可見。`test_p3e_temporary_instruction_context.py` 驗 handoff → context → Take Back拒舊 token → next handoff不沿用舊 instruction；browser/MCP journey test code亦包含 instruction。
- [x] 8. `get_pending_events` / `wait_for_event` 直接使用 P3-A `TableEventService.list_after()` / `wait_after()`。`test_p3e_ai_event_projection.py::test_ai_reconnect_replays_events_missed_while_no_process_local_waiter_exists` 以重建 service objects + durable cursor直接驗 disconnect期間事件可補回。
- [x] 9. wait timeout是正常 empty result，等待本身沿用 P3-A async/no-DB-hold path。MCP入口 token DB auth已改用 `run_in_threadpool`；direct async facade的 `_actor()` 也在 await 前 `asyncio.to_thread`。`test_p3e_mcp_event_loop.py` 直接斷言兩條 auth/actor resolution都不在 running event loop執行。
- [x] 10. Tool success/error有 stable structured shape與雙語 stable error code。除既有 protocol/tools tests外，`test_p3e_official_mcp_client.py` 使用官方 MCP Python SDK v2解析 `tools/list` 與 `call_tool().structured_content`，並鎖 protocol version為 `2026-07-28`。
- [x] 11. Catalog schema只暴露 typed input，不提供 SQL/raw-state escape hatch；`resolve_action` 不在 catalog。architecture/tool tests持續鎖住此邊界。
- [x] 12. P3-E 沒有高階 `resolve_action()`。AI DM維持 Narration / Request Check / Current State等細粒度共用 tools，P6/P7邊界未提前侵入。
- [x] 13. Web/MCP transport沒有呼叫 LLM API、沒有外部模型 API key storage，也不主動喚醒外部 conversation；AI只以 scoped inbound bearer request進入。
- [x] 14. **External MCP client E1 HTTPS journey 已於 2026-09-11 執行完成（P3-F closeout 合併驗收）。** Client：Claude Code 2.1.260（Claude Desktop Code tab，Windows 11；wire `User-Agent: claude-code/2.1.260 (claude-desktop, agent-sdk/0.3.260)`）。static Bearer 以 `claude mcp add table <https url>/mcp --transport http --scope local --header "Authorization: Bearer <AI Join Token>"` 設定，token 只存本機 `~/.claude.json` local scope，不進 repo / log。HTTPS/TLS 入口：`https://greengrape.tail16ce3a.ts.net/mcp`（Tailscale serve，Let's Encrypt 憑證，tailnet only）→ 本機 wire logging proxy `127.0.0.1:8765` → `:8000`。完整 journey：context → events → action → DM Request Check → formal roll → wait timeout → Take Back → 舊 token `tools/call` 401 → End，wire 摘要見下方「External MCP E1 執行結果」。
- [x] 15. Client disconnect不破壞 Server State；重連靠 canonical DB + cursor恢復。`test_p3e_ai_event_projection.py` 已補 disconnect期間無 waiter/notifier、重建 service後仍補回 missed event的直接證據。
- [x] 16. Tool surface集中在 transport-neutral `AIToolApplicationService`；未來 Site Tools / agent transport可以包同一 service，不需複製 gameplay logic。
- [x] 17. Standalone不 mount MCP。除 M03 import boundary外，`test_p3e_standalone_mcp.py` 直接斷言 `/mcp` 不在 standalone OpenAPI，且 POST `/mcp` 只會得到 SPA fallback 的 404/405、不含 JSON-RPC envelope。

## Review fixes

本輪針對 P3-E review finding額外收斂：

- MCP async endpoint不再直接在 ASGI event loop執行同步 token DB authorization；入口使用短 `run_in_threadpool`。
- MCP request已取得的 `AIControllerAuthView` 會傳入 tool facade，避免同一 `tools/call` 因 actor construction再做一次完整 token/current-scope lookup。`get_session_context` 不再因 actor conversion與 Temporary Instruction各自重做 authorization。
- `wait_for_event` 若由 transport外直接呼叫，actor resolution也先 offload，再進真正 async wait；等待期間仍不持有 DB connection / transaction或 sync worker。
- P3-E 直接補 End Session、administrative reassignment、wrong-session後的 `tools/call get_session_context` → `401 ai_token_unauthorized`。revoked token原本已由 `test_p3e_mcp_token_lifecycle.py` 的 rotate→old token `/mcp` 401直接覆蓋。
- reconnect cursor與 Standalone `/mcp` 從間接證據提升成 P3-E 專屬直接斷言。

## E2E test code

`apps/web/e2e/p3e-mcp-browser-integration.spec.ts` 已存在，涵蓋：

```text
Human Player Let AI Control + Temporary Instruction
→ MCP tools/list without legacy initialize
→ get_session_context
→ MCP post_action
→ Human DM browser sees canonical action
→ Human DM Request Check
→ MCP get_pending_events (no secret DC)
→ MCP roll_pending
→ Human DM browser sees same resolved result
→ origin Human Take Back
→ old MCP token rejected
→ Human DM End
```

此 spec 已於 2026-09-11 以 `npm run test:e2e:docker -- e2e/p3e-mcp-browser-integration.spec.ts` 在本機 Docker Linux dev server 跑過兩次（`efa71e1` 與 review fixes 後的 `207fc88`），皆 1 passed。spec 檔頭亦明確註記它不是 External E1 evidence。

## External MCP auth / wire preflight

在架 HTTPS tunnel / reverse proxy之前，必須先對實際要用的 external AI host/client做 runtime preflight：

```text
1. 記錄 client name / exact version / OS platform / 測試日期。
2. 證明該版本可安全注入 static `Authorization: Bearer <AI Join Token>`，token不得進 repo/log。
3. 對 loopback或安全測試入口觀察真實 client wire：
   - MCP-Protocol-Version = 2026-07-28
   - body _meta protocolVersion + clientCapabilities
   - Mcp-Method 正確
   - named operation Mcp-Name 正確
   - 不送 Mcp-Session-Id
4. 只有 runtime preflight pass後才架 HTTPS/TLS入口並執行完整 E1 journey。
```

官方 MCP Python SDK v2只作 automated Tier-1 protocol/parser gate，**不能**被記成 external AI host/client E1。候選 external client即使文件宣稱支援 custom Authorization header，也必須以 exact version/platform真的連一次後才可勾選第 14 條。

### Preflight 結果（2026-09-11，loopback，branch @ `f74c2fe`）

以 logging proxy（`127.0.0.1:8765 → 8000`）夾在中間，用丟棄 Room 的 pre-session AI DM grant 讓兩個真實 client 連 `/mcp`：

| Client | auth 設定方式 | 觀察到的 wire | 結果 |
|---|---|---|---|
| **Claude Code CLI 2.1.260**（Windows） | `--mcp-config` JSON：`type: "http"` + `headers.Authorization: "Bearer <token>"` | `MCP-Protocol-Version: 2026-07-28`、`Mcp-Method`、body `_meta` 含 `protocolVersion` / `clientInfo` / `clientCapabilities`；不送 legacy `initialize`、不送 `Mcp-Session-Id` | `server/discover` 與 `tools/list` 皆 200，pre-session catalog 正確 → **通過 wire preflight** |
| Codex CLI 0.147.0（Windows） | `mcp_servers.<name>.bearer_token_env_var` | 送 legacy `initialize` + `protocolVersion: 2025-06-18` | server 回 `-32022 mcp_protocol_version_unsupported` → **不可作 E1 client** |

未觀察到的項目：兩個 CLI 當次都沒有成功的 model turn（子 Claude Code OAuth session 過期、Codex 要求升級），所以只有啟動時的 discover / tools-list，**沒有 `tools/call`，`Mcp-Name` header 尚無 wire 證據**。P3-F E1 時第一個 `tools/call` 就會補上。

P3-F E1 的預定 client 為 **Claude Code CLI**（Claude Desktop 未驗證）。實際執行改用 Claude Desktop Code tab 內建的同一版 Claude Code 2.1.260（CLI `-p` 當時 `loggedIn: false` 不可用），見下節。

### External MCP E1 執行結果（2026-09-11，Tailscale HTTPS，branch `p3-f-full-integration-closeout`）

- **入口形態**：`https://greengrape.tail16ce3a.ts.net/mcp`，Tailscale serve 終結 TLS（Let's Encrypt 真憑證，tailnet only）→ `http://127.0.0.1:8765` wire logging proxy（`tls_wire_proxy.py --plain`，Authorization 只留 `Bearer at_ai...[redacted]`）→ `http://127.0.0.1:8000`。每筆 wire 都帶 `X-Forwarded-Proto: https`、`X-Forwarded-Host: greengrape.tail16ce3a.ts.net`、`Tailscale-User-Login` 作 TLS 入口證據。
- **Client**：Claude Code 2.1.260，Claude Desktop Code tab（Windows 11）；`User-Agent: claude-code/2.1.260 (claude-desktop, agent-sdk/0.3.260)`。MCP server 以 `claude mcp add table <url> --transport http --scope local --header "Authorization: Bearer <token>"` 註冊，token 為 P3-D Player Seat `Let AI Control` 產生的 fresh scoped AI Join Token（generation 2），附 Temporary Handoff Instruction。
- **Wire contract**（全部 request）：`MCP-Protocol-Version: 2026-07-28`、`Mcp-Method`、body `_meta` 含 `io.modelcontextprotocol/protocolVersion: 2026-07-28`、`clientInfo {name: claude-code, version: 2.1.260}`、`clientCapabilities {roots.listChanged, elicitation}`；**沒有 legacy `initialize`、沒有 `Mcp-Session-Id`**。每個 `tools/call` 都帶 `Mcp-Name: <tool>`（補上 preflight 缺的證據）。
- **Journey（UTC）**：

| # | 端 | wire | 結果 |
|---|---|---|---|
| 0 | client 啟動 | `server/discover` 200 → `tools/list` 200 | Player catalog；session instructions 雙語 |
| 1 | AI | `tools/call get_session_context` 200 | `mode=active_session`、caller role player、`temporary_instruction` 原文可見、`recent_events` cursor 2 |
| 1 | AI | `tools/call get_pending_events(after_seq=0)` 200 | seq 1 `stage.updated`、seq 2 `controller.changed(human_handoff→ai)` |
| 1 | AI | `tools/call post_action` 200 | seq 3 `exploration.action`，acting/subject = AI Player Seat，`execution_mode=self` |
| 2 | Human DM（REST） | Request Check Investigation DC 14，visibility `roller_and_dm` | 201 |
| 3 | AI | `tools/call get_pending_events(after_seq=3)` 200 | seq 4 `roll.requested`（`seat_private`），**payload 無 `dc`** |
| 3 | AI | `tools/call roll_pending` 200 | `source=server`、`1d20+1`、raw `[5]`、total 6 |
| 3 | AI | `tools/call wait_for_event(after_seq=5, timeout=3)` 200 | timeout 回 `events: []`（正常 empty result） |
| 3 | Human DM（REST） | list requests | `status=resolved`、`dc=14`、version 2 |
| 4 | Human Player（REST） | Take Back Control | 204 |
| 5 | raw probe（HTTPS） | `tools/call` with old token | 401 `-32001 ai_token_unauthorized` |
| 6 | AI | `tools/call get_session_context` | **401 `ai_token_unauthorized`**；client 回報 `MCP server "table" requires re-authorization`，tool 不可用 |
| 7 | Human DM（REST） | End Session | 200 `status=ended` |

- 步 3 另有一筆 `wait_for_event` 帶錯誤參數名（`timeout_seconds`）→ server 回 `invalid_arguments` 雙語 structured error，schema validation 正常，非契約問題。
- 步 6 與 CLI preflight 觀察不同：client 已持有 modern 連線，直接對 `tools/call` 收 401，**沒有退回 legacy `initialize`**，屬更乾淨的拒絕路徑。
- 原始 `wire.jsonl`（token 已 redact）與 `e1_state.json` 留在本機 scratchpad，不進 repo。

## Verification status

- Branch：`p3-e-ai-tool-surface-event-delivery`，final code SHA `f74c2fe`。
- 本機（2026-09-11，Windows，`.venv` 已安裝 `[dev]` extra 含 `mcp 2.2.0`）：全套 backend pytest 於 `207fc88` 為 `1 failed, 1297 passed, 37 skipped`，唯一紅燈 `test_p3e_standalone_mcp.py` 為斷言寫錯（standalone SPA fallback 讓 POST `/mcp` 回 405 而非 404），已於 `f74c2fe` 修正，P3-E focused 41 passed；前端 vitest 298 passed、`npm run build` 成功；`docker compose config` OK。
- Playwright P3-E E2E：本機 Docker 跑過兩次皆 1 passed（見上）。
- GitHub `P3 Non-E2E`：`207fc88` run `34503603243` 只有 backend 因同一條測試 failure，frontend / postgres-migrations / windows-standalone success；`f74c2fe` run `34545415406` **全綠**：backend / frontend / postgres-migrations / windows-standalone 皆 success。
- External MCP E1：**✅ 2026-09-11 完成**（Claude Code 2.1.260 經 Tailscale HTTPS，見「External MCP E1 執行結果」）；loopback wire preflight 見上表。

## Boundary / remaining closeout

P3-E automated implementation已具備 modern MCP transport、scoped auth、role tools、canonical action/roll、durable event delivery、async wait與Standalone boundary；實作規格第 14 條的真 external HTTPS/TLS AI client evidence 已於 2026-09-11 由 Claude Code 2.1.260 經 Tailscale HTTPS 入口補齊（同時滿足 P3-F 實作規格第 11 條）。**P3-E 關門 ✅。**
