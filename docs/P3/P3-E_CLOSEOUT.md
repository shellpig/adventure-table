# P3-E Closeout Checklist

P3-E — AI Tool Surface & Event Delivery closeout scope。編號對應 [實作規格](實作規格.md) 的「完成後必須為真」。**目前 automated implementation gate 已大致收斂，但第 14 條真實 external MCP client E1 尚未完成，因此本 Subphase 不宣告關門。**

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
- [ ] 14. **BLOCKER — External MCP client E1 尚未完成。** 目前 automated證據包含自寫 real-backend Playwright MCP journey與官方 MCP Python SDK v2 wire/parser test，但兩者都不能取代測試指南要求的「真 external AI host/client + HTTPS/TLS」。必須在關門前記錄 exact client name/version/platform、static Bearer設定方式、HTTPS/TLS入口、測試日期，並完成 context → event → action → formal roll/check → Take Back/End → next call rejected。
- [x] 15. Client disconnect不破壞 Server State；重連靠 canonical DB + cursor恢復。`test_p3e_ai_event_projection.py` 已補 disconnect期間無 waiter/notifier、重建 service後仍補回 missed event的直接證據。
- [x] 16. Tool surface集中在 transport-neutral `AIToolApplicationService`；未來 Site Tools / agent transport可以包同一 service，不需複製 gameplay logic。
- [x] 17. Standalone不 mount MCP。除 M03 import boundary外，`test_p3e_standalone_mcp.py` 直接斷言 `/mcp` 不在 standalone OpenAPI且 POST `/mcp` 為 404。

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

依目前開發要求，**P3-E Playwright E2E test code有交付，但本輪不執行 E2E**。此 spec檔頭亦明確註記它不是 External E1 evidence。

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

## Verification status

- Branch：`p3-e-ai-tool-surface-event-delivery`。
- P3 Non-E2E run `34490510364` / SHA `e7ace80` 曾完整全綠：backend `1289 passed, 38 skipped`，PostgreSQL / frontend / Windows standalone皆 success。
- 本輪 review fixes之 latest non-E2E validation需以最新 code SHA的 run為準；在其完成前不把舊 run當成新修正的 final evidence。
- Playwright P3-E E2E：**not run by request**；只有 test code + TypeScript build/static coverage。
- External MCP E1：**PENDING / BLOCKER**。

## Boundary / remaining closeout

P3-E automated implementation已具備 modern MCP transport、scoped auth、role tools、canonical action/roll、durable event delivery、async wait與Standalone boundary；但因實作規格第 14 條是產品完成條件，**沒有真 external HTTPS/TLS AI host/client evidence就不能把 P3-E 標成 closed，也不能以官方 SDK或自製 Playwright client替代。**

下一個關門動作固定是：先完成 exact external client auth/wire runtime preflight；preflight成功後才建立 HTTPS/TLS入口跑 E1，最後更新本文件的第 14 條與 exact final SHA / Actions evidence。
