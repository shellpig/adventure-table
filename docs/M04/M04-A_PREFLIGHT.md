# M04-A — Web Chat MCP Preflight Record

> Phase: **M04-A — Web Chat MCP Preflight**  
> Status: **CLOSED — ChatGPT Web Plus selected; A.0–A.7 complete**  
> Measurement window: **2026-09-11～2026-09-12**

This file is the closeout evidence record required by `實作規格.md` A.0–A.7 and `測試指南.md`. A.2–A.6 below come from the real ChatGPT Web connector against the temporary public HTTPS harness; local/CI tests are recorded separately and do not substitute for those live gates.

Raw JSONL stays uncommitted. Where the retained export preserved the harness line number, this record uses that line number. Later excerpts were copied as individual redacted JSON objects, so those observations use their UTC request timestamp instead of inventing a JSONL line number.

---

## A.0 — Platform ladder and prerequisite record

### Support check and actual ladder result

The 2026-09-11 official-document check suggested that full MCP/write support was documented for Business / Enterprise / Edu and separately described Pro read/fetch support. That was treated only as a support-scope inference, not as proof that a personal Plus account could not execute tools.

The live Developer Mode run on the actual **ChatGPT Plus personal** account subsequently succeeded end-to-end for custom MCP OAuth, discovery, a read tool, and a write tool. Therefore the live measurement overrides the earlier support-scope inference for this project/account and the platform ladder stops at step 1.

| Ladder | Plan | Live result | M04-A decision |
|---|---|---|---|
| 1 | ChatGPT Plus personal | Custom connector creation, OAuth/DCR, `server/discover`, `tools/list`, read/write, refresh/reconnect, role-scoped catalog and long-poll all measured successfully | **TARGET PLATFORM** |
| 2 | Claude chat personal | Not needed after step 1 passed | Non-gating / not measured |

Sources checked on 2026-09-11:

- OpenAI Help Center — Developer mode and MCP apps in ChatGPT: https://help.openai.com/en/articles/12584461-developer-mode-apps-and-full-mcp-connectors-in-chatgpt-beta
- Anthropic Help Center — custom remote MCP connectors: https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp

### Harness and HTTPS entry

- Branch: `m04a-webchat-preflight`
- Standalone harness: `tools/m04a-webchat-preflight/`
- HTTPS transport used for the live run: **Tailscale Funnel**, public port 8787 only; the temporary hostname and test password are intentionally not committed here.
- Admin listener: loopback only, default `127.0.0.1:8788`.
- Hardening restoration: `b7b7c07644e2315b1272f04fc09cf65ed40d41da`
- Hardening regression tests: `f14ae662afd8cf6f78654e4d66ebe5d1802f516a`
- ChatGPT `2026-07-28` discovery-shape fix: `2c02049fdc8a45331e8ca9c7a40b3e7db276db89`
- Final closeout CI code head: `2b78acf138e7d5d67b325187db724dc7997b5de9`
- Closeout Actions run: `34663200995` — **SUCCESS**

The temporary synthetic hardening PR #37 was closed unmerged during closeout. No M04-A production `apps/server/app/*` code was introduced.

---

## A.1 — Standalone harness and self-check

Implemented surface:

- OAuth Protected Resource Metadata and Authorization Server Metadata
- dynamic client registration (`POST /register`)
- minimal `GET/POST /authorize`
- authorization-code + PKCE and refresh-token grants at `POST /token`
- public `POST /mcp` plus separate loopback-only admin listener
- `get_context`, `post_note`, `dm_only_ping`, `wait_seconds`, dynamic `late_tool`
- symmetric request/response JSONL redaction and non-reversible Authorization fingerprint
- no import dependency in either direction between the harness and `app.*`

Real-tunnel evidence retained from the run:

| Check | Result | Evidence locator |
|---|---|---|
| authorization-server metadata | PASS, 200; advertised authorize/token/register, S256, scopes | JSONL line 2; ChatGPT repeats at lines 7/11/13 |
| protected-resource discovery | PASS; ChatGPT followed the Bearer resource metadata challenge | live OAuth trace around JSONL lines 5–7 |
| DCR | PASS; returned `client_id` | JSONL line 15 |
| authorize form | PASS, 200 | JSONL line 16 |
| DM authorize POST | PASS, 302 to ChatGPT callback | JSONL line 18 |
| authorization-code token exchange | PASS, 200 | JSONL line 19 |
| refresh grant | PASS, 200 | JSONL line 24 |
| DM role catalog / `dm_only_ping` | PASS | live A.5, tool call timestamp `2026-09-12T00:23:05Z` |
| Player role catalog omits `dm_only_ping` | PASS | live A.5 UI + Player call result |
| `post_note` | PASS, `seq: 1` | live A.4 UI |
| loopback `/admin/add-tool` | PASS; enabled `late_tool` for A.5 | live A.5 operator action |
| public admin boundary | public app has no `/admin/*`; POST 404 locked by contract test and isolation design | `test_server_contract.py` + separate listener design |
| token log redaction | PASS; access/refresh/code/password remain masked | `test_redact.py` + live JSONL samples |

The later `Select-String` evidence export did not preserve a standalone live public-admin request line, so none is fabricated here. The public 404 behavior remains directly covered by the same public FastAPI app used through the tunnel and by the closeout contract suite.

### Final static / automated closeout verification

`M04-A Closeout Verification` run `34663200995` on `2b78acf138e7d5d67b325187db724dc7997b5de9`:

```text
static git diff --check on M04-A code/tests                         PASS
python -m py_compile server.py admin.py test_hardening_regressions.py PASS
pytest test_redact.py + test_server_contract.py +
       test_hardening_regressions.py                                14 passed
pytest test_m04a_preflight_isolation.py + P3-D/P3-E regression      76 passed, 14 skipped
```

The first one-shot closeout run `34663169141` failed before tests because the temporary workflow used local ref `main...HEAD`; Actions checkout exposed `origin/main` instead. The workflow was corrected to `origin/main...HEAD`, then the successful run above executed every verification step. This was a CI harness error, not a code/test failure. The one-shot workflow was removed after the successful run; `.github/workflows/m04a-non-e2e.yml` remains the persistent manual non-E2E workflow.

---

# ChatGPT Web Plus — target platform

## A.2 — OAuth

**PASS — real ChatGPT Web personal Plus run.**

Observed client behavior:

- Dynamic registration body identified `client_name: "ChatGPT"`.
- Redirect URI shape: `https://chatgpt.com/connector/oauth/<opaque-id>`.
- `token_endpoint_auth_method: none`.
- Grant types: `authorization_code`, `refresh_token`.
- PKCE: **S256**.
- DM authorization requested `mcp:read mcp:write mcp:dm`.
- ChatGPT exchanged the code at `/token` and later used the refresh-token grant.
- Access and refresh values were redacted in request/response logging.

Retained JSONL locators: DCR line 15, authorize GET line 16, authorize POST line 18, code exchange line 19, refresh line 24.

The initial OAuth succeeded even before the protocol-shape fix. That distinction was useful: OAuth was not the reason the first tool scan stopped.

---

## A.3 — Scan Tools and protocol record

**PASS after one harness compatibility defect was identified and fixed.**

Observed target contract:

```text
client: openai-mcp/1.0.0
MCP-Protocol-Version: 2026-07-28
Mcp-Session-Id: absent
Accept: application/json, text/event-stream
first MCP discovery path: server/discover -> tools/list -> tools/call
legacy initialize: not used by ChatGPT in this run
response transport: ordinary JSON accepted; M04A_FORCE_SSE not needed
```

ChatGPT request `_meta` included the MCP protocol version, `clientInfo` (`openai-mcp` / `1.0.0`), client capabilities, and OpenAI-specific locale/session metadata. Live tool-call excerpts after the fix continue to show protocol `2026-07-28`, `Mcp-Session-Id` absent and SSE advertised in `Accept`.

### Compatibility defect found by the preflight

The first harness version replied to `server/discover` with a placeholder shape:

```json
{"protocolVersion":"2026-07-28","instructions":"…","capabilities":{"tools":true}}
```

ChatGPT completed OAuth but did not expose the tools after that response. The P3-E contract already used the formal `2026-07-28` response shape: `supportedVersions`, `capabilities.tools = {}`, `resultType`, optional cache fields, and `_meta.io.modelcontextprotocol/serverInfo`.

Commit `2c02049fdc8a45331e8ca9c7a40b3e7db276db89` changed the harness to mirror that proven P3-E result envelope for `server/discover`, `tools/list` and `tools/call` while leaving the legacy `initialize` probe path intact. After restart/reconnect, ChatGPT immediately discovered and invoked `get_context`.

**Conclusion:** M04-B must implement the already-existing Adventure Table `2026-07-28` stateless path, not a legacy `initialize`/session-id compatibility layer for ChatGPT Web.

---

## A.4 — Read and write

**PASS.**

Read:

```json
{"role":"dm","note_count":0,"server_time":"2026-09-12T00:13:55.201693+00:00"}
```

Write:

```text
post_note(text="chatgpt-m04a-write-test")
-> {"seq":1}
```

Verification read immediately after the write:

```json
{"role":"dm","note_count":1,"server_time":"2026-09-12T00:15:20.576672+00:00"}
```

In the observed Developer Mode UI, this `post_note` invocation did not present an additional per-call confirmation dialog beyond the connector's configured permission policy.

---

## A.5 — Tool cache, refresh, role scope, revoke and credentials

**PASS.**

| Step | Live operation | Observed ChatGPT behavior | M04-B implication |
|---|---|---|---|
| DM baseline | authorize DM, call `dm_only_ping` | `{"pong":true}` | role-scoped DM catalog is usable |
| Dynamic catalog change | loopback admin enables `late_tool` | existing conversation returns `late_tool not available` | server catalog changes do not enter an existing chat automatically |
| Wait past advertised cache TTL | retry after >40 s; response advertises `ttlMs=30000` | still unavailable | TTL did not automatically refresh the conversation tool schema |
| Manual connector Refresh | press Refresh after `late_tool` was enabled | new tool appears in connector | documented Refresh is a viable catalog-update path |
| Conversation after Refresh | call from old chat, then new chat | old chat keeps old schema; **new chat** calls `late_tool` successfully and returns `{"late_tool":true}` | schema is effectively conversation-scoped snapshot |
| Player catalog | separate connector authorized as Player | `dm_only_ping` is not exposed; `get_context` returns `role:"player"` | keep P3 role-scoped catalog; server call authorization remains SSOT |
| Revoke all | loopback `/admin/revoke-all` | both DM and Player show “connection expired / reconnect” | server revoke is authoritative; client does not silently keep working |
| Reconnect | complete OAuth again | existing DM and Player conversations resume without being recreated | credential recovery does not require a new conversation |
| Two DM conversations | same connector identity, two new chats | different access-token fingerprints | access credentials are not shared across conversations |

Retained redacted request evidence:

- DM `dm_only_ping` at `2026-09-12T00:23:05Z`, successful; protocol 2026-07-28, no MCP session id.
- Player `get_context` at `2026-09-12T00:28:21Z`, `role:"player"`.
- DM reconnect `get_context` at `2026-09-12T00:32:26Z`, `role:"dm"`.
- Player reconnect `get_context` at `2026-09-12T00:32:53Z`, `role:"player"`.
- Two DM conversations had the same connector subject but different `openai/session` values and different `authorization_fingerprint` values: `96214a4485d16126` at `00:34:40Z` and `4ce87fb9b6cebfb9` at `00:35:19Z`.

The fingerprint only proves that the access credentials differ. It does **not** prove whether the platform internally shares or separates the refresh-token family.

### Catalog decision for M04-B

This lands on the second row of the M04 decision table:

> **Keep the P3 role-scoped catalog. Catalog/authorization changes that change the visible tool set require connector Refresh, and a newly started conversation is required to consume the refreshed schema.**

Reconnect alone is sufficient for credential recovery when the tool schema has not changed. Regardless of discovery presentation, `tools/call` server-side authorization remains the only security boundary.

---

## A.6 — Long-poll tolerance

**PASS through the full harness range using Tailscale Funnel.**

| `wait_seconds` | Result |
|---:|---|
| 10 | PASS |
| 30 | PASS |
| 60 | PASS |
| 90 | PASS |
| 120 | PASS |

Highest successful value: **120 seconds**  
First platform timeout: **not observed within the harness range**

M04-A therefore establishes only that ChatGPT Web tolerated at least 120 seconds over this Tailscale Funnel path. It does not claim behavior beyond 120 seconds.

---

## A.7 — Architecture conclusions for M04-B

### Target platform

**ChatGPT Web on the tested personal Plus account.** The real run passed OAuth, discovery, read/write, role-scoped tools, reconnect and 120-second long-poll. Claude chat is no longer a gating ladder step for M04.

### OAuth endpoints required

M04-B needs Protected Resource Metadata, Authorization Server Metadata, dynamic client registration, authorize and token endpoints, with authorization-code + PKCE S256 and refresh-token support. OAuth must bind to an already-existing P3-D grant/Seat; production OAuth must not reproduce the preflight role picker, create a Seat, select a Seat, or switch Seat/role.

### Protocol version and methods

Use the existing **MCP `2026-07-28` stateless contract**: `server/discover`, `tools/list`, `tools/call`; no `initialize` requirement and no `Mcp-Session-Id`. Responses must keep the formal P3-E result envelope (`resultType`, `_meta.io.modelcontextprotocol/serverInfo`, and cache fields where appropriate). ChatGPT advertising SSE does not force SSE; JSON responses worked.

### Catalog presentation

Use the existing **role-scoped catalog**. When the visible catalog changes, user guidance must say: **Refresh the connector, then start a new conversation**. Reconnect after credential expiry/revoke can restore an existing conversation when the schema is unchanged. Server-side role/grant authorization at `tools/call` remains authoritative.

### `wait_for_event` timeout cap

The platform/tunnel combination passed **120 seconds**, the maximum tested value. M04-B may safely retain a cap up to 120 seconds on the evidence available here; do not infer support beyond 120 seconds. There is no preflight evidence requiring a cap below 60 seconds.

### Blockers

**None for starting M04-B.** The initial ChatGPT failure was a harness `server/discover` response-shape defect, not a demonstrated Plus-plan block; it was fixed and the same Plus account then passed the real gates. Claude compatibility remains optional/non-gating for later compatibility work.

---

## A.8 — Optional compatibility measurement

Claude chat / Claude Desktop: **not measured for M04-A after ChatGPT Plus passed the first ladder step.** Non-gating.

---

## Closeout

M04-A is **closed**. It changed only the standalone measurement harness, M04-A tests/workflow and documentation; Adventure Table production app code was not modified. The next implementation subphase is **M04-B — Adventure Table Web Chat Integration**, using the A.7 decisions above as its required design input.
