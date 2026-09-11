# M04-A — Web Chat MCP Preflight Record

> Phase: **M04-A — Web Chat MCP Preflight**  
> Status: **IN PROGRESS — A.0/A.1 code + CI complete; real-tunnel smoke and Claude web A.2–A.6 pending**  
> Measurement date started: **2026-09-11**

This file is the evidence record required by `實作規格.md` A.0–A.7 and `測試指南.md`. A.2–A.6 are real-platform gates and must not be filled from mocks, local clients, or assumptions.

---

## A.0 — Platform ladder and prerequisite record

### Official support check — 2026-09-11

| Ladder | Plan | Official support observed | M04-A result |
|---|---|---|---|
| 1 | ChatGPT Plus personal | OpenAI's current developer-mode documentation says full MCP, including modify/write actions, is available to Business and Enterprise/Edu. The same page separately says Pro can connect MCPs with read/fetch permissions but full MCP is not available to Pro. Plus is therefore not a write-capable full-MCP target under the M04 requirement. | **Plan limitation — not an Adventure Table protocol failure. Skip live A.2–A.6 and continue to ladder step 2.** |
| 2 | Claude chat personal | Anthropic's current remote-MCP documentation says custom remote MCP connectors are available to Free, Pro, Max, Team, and Enterprise users and that a connected Claude can access services and take action in them. | **Candidate target platform. Real A.2–A.6 still required.** |

Sources checked on 2026-09-11:

- OpenAI Help Center — Developer mode and MCP apps in ChatGPT: https://help.openai.com/en/articles/12584461
- Anthropic Help Center — Get started with custom connectors using remote MCP: https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp

No Business, Enterprise, or Edu workspace is used to make M04 pass.

### Harness and HTTPS entry

- Branch: `m04a-webchat-preflight`
- Standalone harness path: `tools/m04a-webchat-preflight/`
- Hardened core server commit: `682ba1eb4d72ca481b2f326bd50c8bc7b21cd6c8`
- Focused non-E2E CI head: `03d31ee193c86eaccd1f4c96def3d971c0b5ea37`
- GitHub Actions run: `34615184815` — **success**
- Public listener: `0.0.0.0:8787`
- Admin listener: `127.0.0.1:8788` only
- Public entry shape for the real run: `https://<temporary-tunnel-origin>/mcp`; the tunnel must forward public port 8787 only. The origin and credentials are intentionally not committed.
- One-line server command after environment setup: `.\.venv\Scripts\python.exe .\server.py`

Ladder progress:

```text
ChatGPT Plus
  -> official-plan check: full MCP/write unavailable
  -> classified as Plan Limitation
Claude chat personal
  -> candidate
  -> real A.2–A.6 pending
Target platform
  -> not final until Claude A.2–A.6 complete
```

---

## A.1 — Standalone harness and self-check

Implemented files:

- `tools/m04a-webchat-preflight/server.py`
- `tools/m04a-webchat-preflight/admin.py`
- `tools/m04a-webchat-preflight/authorize.html`
- `tools/m04a-webchat-preflight/requirements.txt`
- `tools/m04a-webchat-preflight/README.md`
- `tools/m04a-webchat-preflight/logs/.gitignore`
- `tools/m04a-webchat-preflight/test_redact.py`
- `tools/m04a-webchat-preflight/test_server_contract.py`
- `apps/server/tests/test_m04a_preflight_isolation.py`
- `.github/workflows/m04a-non-e2e.yml`

Implemented contract:

- RFC-style protected-resource metadata and authorization-server metadata.
- Dynamic client registration at `POST /register`.
- Minimal role/password authorization form at `GET/POST /authorize`.
- Authorization-code + PKCE and refresh-token grants at `POST /token`.
- Authorization code is consumed only after client/redirect/PKCE validation succeeds; a failed verifier does not destroy a valid code.
- Volatile hashed access/refresh token families with revoke-all support.
- Access-token TTL is configurable with `M04A_ACCESS_TTL_SECONDS` (default 300) so the real run can force refresh behavior without changing code.
- `GET /mcp` probe plus `POST /mcp` JSON-RPC handling for `initialize`, `notifications/initialized`, `server/discover`, `tools/list`, `tools/call`, and `ping`.
- `get_context`, `post_note`, `dm_only_ping`, `wait_seconds`, and dynamically enabled `late_tool`.
- Role-scoped discovery and server-side DM-only call enforcement.
- JSONL request/response logging with one shared redaction function and explicit observations for protocol version, session-id presence, SSE accept, JSON-RPC method, and `_meta`.
- `Authorization` remains fully redacted, while `observation.authorization_fingerprint` stores only a deterministic truncated SHA-256 fingerprint so A.5 can compare whether two conversations used the same access credential without logging the credential itself.
- OAuth `client_id` is left visible for correlation because it is an identifier rather than a secret; access token, refresh token, authorization code, PKCE verifier/challenge, client secret, password, Authorization, and cookie values remain masked.
- Separate loopback-only admin listener; `/admin/*` is absent from the public app.
- Optional `M04A_FORCE_SSE=1` single-event SSE response mode for a second measurement only if the real client rejects JSON while advertising SSE.
- Bidirectional isolation gate: the preflight tool cannot import `app.*`, and Adventure Table `app/*` cannot import or reference the standalone preflight tool.

Focused CI validation against the exact pushed branch:

```text
GitHub Actions: M04-A Non-E2E Regression / run 34615184815    SUCCESS
python -m py_compile server.py admin.py                       PASS
pytest test_redact.py + test_server_contract.py               5 passed
pytest test_m04a_preflight_isolation.py + P3-D/P3-E suite     PASS
```

The standalone contract tests cover DCR, PKCE code exchange, failed-PKCE non-consumption, refresh, arbitrary requested protocol version, DM catalog, `get_context`, `post_note`, dynamic `late_tool`, Player catalog filtering, public-admin 404, loopback admin success, revoke-all, and secret redaction. The P3-D/P3-E regression suite remained green. This is **engineering self-check only** and does not substitute for A.2–A.6.

### A.1 real-tunnel smoke evidence

Pending execution with the temporary HTTPS tunnel. Use `tools/m04a-webchat-preflight/README.md` and record the resulting JSONL line numbers here.

| Check | Expected | Result | JSONL line(s) |
|---|---|---|---|
| protected-resource metadata | 200 | pending | pending |
| authorization-server metadata | 200 | pending | pending |
| DCR | returns `client_id` | pending | pending |
| authorize form | 200 | pending | pending |
| DM code -> token | success | pending | pending |
| DM `tools/list` | contains `dm_only_ping` | pending | pending |
| `post_note` | returns seq | pending | pending |
| public `/admin/add-tool` | 404 | pending | pending |
| loopback `/admin/add-tool` | 200 | pending | local-only |
| Player `tools/list` | omits `dm_only_ping` | pending | pending |
| token response log | no plaintext access/refresh token | pending | pending |

---

# ChatGPT Plus — ladder step 1

## A.2 OAuth

**Not run by design.** The 2026-09-11 official support check establishes that ChatGPT Plus is not eligible for the full MCP/write capability required by M04. Per the M04 platform ladder this is recorded as a plan limitation, not a protocol failure, and measurement moves to Claude chat personal.

## A.3 Scan Tools / protocol

Not applicable after the plan-limitation decision.

## A.4 Read + write

Not applicable. The write-capable requirement is the blocker.

## A.5 Tool cache / refresh / re-auth

Not applicable after the plan-limitation decision.

## A.6 Long-poll tolerance

Not applicable after the plan-limitation decision.

---

# Claude chat personal — ladder step 2

> **Real web measurement required.** Fill this section only from the Claude web connector using the temporary public HTTPS endpoint. Raw JSONL stays uncommitted; paste only redacted evidence and line numbers.

## A.2 OAuth

Status: **PENDING REAL WEB RUN**

| Request order | Endpoint / method | Key request fields after redaction | Key response fields after redaction | JSONL line |
|---|---|---|---|---|
| 1 | pending | pending | pending | pending |

Record after the run:

- Metadata endpoints actually requested: pending
- Dynamic client registration used: pending
- Redirect URI shape: pending
- PKCE present / method: pending
- Requested scope: pending
- Token grant type: pending
- Refresh token later used: pending

## A.3 Scan Tools and protocol record

Status: **PENDING REAL WEB RUN**

| Order | JSON-RPC method | `MCP-Protocol-Version` | `Mcp-Session-Id` | `Accept` / SSE | `_meta` | JSONL line |
|---|---|---|---|---|---|---|
| 1 | pending | pending | pending | pending | pending | pending |

Record whether the client accepts the server's `initialize.protocolVersion`, whether JSON is accepted when SSE is advertised, and whether the `M04A_FORCE_SSE=1` retry is needed.

## A.4 Read and write

Status: **PENDING REAL WEB RUN**

| Tool | Expected | Platform result | Confirmation UX | JSONL line |
|---|---|---|---|---|
| `get_context` | returns role + note count + time | pending | n/a | pending |
| `post_note` | writes volatile note, returns seq | pending | pending | pending |

Also record whether write confirmation can be disabled or remembered.

## A.5 Tool cache / refresh / re-auth

Status: **PENDING REAL WEB RUN**

| Step | Operation | Tool list / platform behavior | User action required | JSONL line(s) |
|---|---|---|---|---|
| 1 | DM authorize -> Scan Tools | pending | pending | pending |
| 2 | loopback `POST /admin/add-tool`, no re-auth | pending | pending | pending |
| 3 | re-authorize as Player | pending; verify `dm_only_ping` disappears | pending | pending |
| 4 | loopback `POST /admin/revoke-all` | pending: refresh / re-auth / error | pending | pending |
| 5 | two conversations, same connector | pending: compare `authorization_fingerprint` values to determine shared/separate access credential | pending | pending |

## A.6 Long-poll tolerance

Status: **PENDING REAL WEB RUN**

| `wait_seconds` | Result | Platform timeout/error | JSONL line |
|---:|---|---|---|
| 10 | pending | pending | pending |
| 30 | pending | pending | pending |
| 60 | pending | pending | pending |
| 90 (only if 60 passes) | pending | pending | pending |
| 120 (only if 90 passes) | pending | pending | pending |

Highest successful value: **pending**  
First platform timeout: **pending**

---

## A.7 — Architecture conclusions for M04-B

These six conclusions are deliberately **not finalized** until Claude A.2–A.6 are complete.

### Target platform

**Pending.** ChatGPT Plus is eliminated by a documented plan limitation. Claude chat personal is the active candidate and requires the real web gate.

### OAuth endpoints required

**Pending Claude evidence.** The harness exposes protected-resource metadata, authorization-server metadata, DCR, authorize, and token endpoints so the live request trace can determine the minimum production set.

### Protocol version & methods

**Pending Claude evidence.** The harness accepts any requested protocol version and records the first method order plus session/SSE behavior; M04-B must follow the observed contract rather than assume a version.

### Catalog presentation

**Pending Claude A.5 evidence.** M04-B will choose among role-scoped catalog as-is, role-scoped catalog with documented Refresh, or the union-catalog/per-role-URL decision path only after the cache/re-auth measurement.

### `wait_for_event` timeout cap

**Pending Claude A.6 evidence.** No production cap is selected from the local/CI smoke.

### Blockers

**Current blocker to M04-A closeout:** A.2–A.6 require a real Claude chat personal-plan connector against the temporary public HTTPS harness. Local/CI clients are explicitly insufficient evidence under the M04 test contract. A.1 real-tunnel smoke should be captured in the same run.

Until those observations are recorded, **M04-A code is implemented and CI-green but the subphase is not closed**, M04-B must not begin, and no M04-B production OAuth/catalog design may be declared final.

---

## A.8 — Optional compatibility measurement

Claude Desktop: **not measured**. This item is non-gating.
