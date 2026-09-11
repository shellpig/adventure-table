# M04-A Web Chat MCP Preflight

This directory is a deliberately standalone measurement harness for **M04-A**. It does not import `app.*`, does not use the Adventure Table database, and must never be shipped as part of the product server.

It exists to measure a real web-chat connector's OAuth discovery, dynamic client registration, MCP protocol shape, read/write behavior, tool-cache refresh, re-authorization, token refresh, and long-poll tolerance before M04-B chooses a production design.

## Safety boundary

- Public listener: `0.0.0.0:8787` by default. The HTTPS tunnel must forward **only this port**.
- Admin listener: defaults to `127.0.0.1:8788`. Startup validates `M04A_ADMIN_HOST` as a literal loopback IP and refuses non-loopback values; `/admin/*` is also absent from the public app and protected by loopback middleware.
- `logs/m04a-preflight.jsonl` is ignored by git. Do not commit raw logs.
- Request and response records use the same `redact()` function. Secret-bearing token/code/verifier/challenge/password fields stay masked. A narrow evidence allowlist keeps non-secret protocol metadata visible (`token_type`, `token_endpoint*`, `code_challenge_method`, `code_challenge_methods_supported`) and preserves numeric JSON-RPC `error.code`.
- OAuth `client_id` stays visible because it is an identifier, not a credential. `Authorization` stays fully masked.
- Each request with an Authorization header also records `observation.authorization_fingerprint`, a truncated SHA-256 fingerprint. Use it only to compare whether two requests used the same access credential; it is not an access token and cannot be used for authentication.
- OAuth state is volatile memory only. Restarting the process clears clients, codes, token families, notes, and the `late_tool` flag.

## Install and start (Windows PowerShell 5.1)

From the repo root:

```powershell
cd .\tools\m04a-webchat-preflight
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

Open a second terminal and expose **port 8787 only** with the same HTTPS-tunnel shape used for P3-F E1. For example, if Cloudflare Tunnel is available:

```powershell
cloudflared tunnel --url http://127.0.0.1:8787
```

Cloudflare Quick Tunnel is acceptable for the basic A.1 smoke and initial JSON probe, but record the exact tunnel provider/mode in the evidence. Cloudflare documents Quick Tunnels as testing/development only and explicitly says they do **not** support Server-Sent Events (SSE). Therefore, if `M04A_FORCE_SSE=1` is needed, or if A.6 reaches 90/120 seconds, cross-check with Tailscale Funnel or a stable/named tunnel before attributing a failure to the chat platform. A Quick Tunnel-only failure is **transport-confounded**, not a platform timeout.

Copy the resulting public `https://...` origin, then start the harness in the first terminal:

```powershell
$env:M04A_PUBLIC_BASE_URL="https://YOUR-PUBLIC-HOST"
$env:M04A_TEST_PASSWORD="choose-a-temporary-test-password"
.\.venv\Scripts\python.exe .\server.py
```

Optional environment variables:

```text
M04A_HOST=0.0.0.0
M04A_PORT=8787
M04A_ADMIN_HOST=127.0.0.1
M04A_ADMIN_PORT=8788
M04A_LOG_PATH=logs/m04a-preflight.jsonl
M04A_ACCESS_TTL_SECONDS=300
M04A_REFRESH_TTL_SECONDS=86400
M04A_FORCE_SSE=0
```

For the A.5 refresh probe, it is useful to restart the harness with a short access TTL such as:

```powershell
$env:M04A_ACCESS_TTL_SECONDS="30"
```

`M04A_FORCE_SSE=0` is intentional: even when the client advertises `text/event-stream`, the first measurement returns JSON. If the real platform rejects that behavior, set `M04A_FORCE_SSE=1` and repeat the affected step; record both attempts in `docs/M04/M04-A_PREFLIGHT.md`.

## Automated self-checks

The repo-root `.venv` carries the development test dependencies. Run the M04-A tests separately:

```powershell
cd .\tools\m04a-webchat-preflight
..\..\.venv\Scripts\python.exe -m pytest .\test_redact.py .\test_server_contract.py -q

cd ..\..\apps\server
$p3Regression = @(
    Get-ChildItem .\tests\test_p3d_*.py
    Get-ChildItem .\tests\test_p3e_*.py
) | ForEach-Object { $_.FullName }
..\..\.venv\Scripts\python.exe -m pytest .\tests\test_m04a_preflight_isolation.py $p3Regression -q
```

PowerShell 5.1 does **not** expand wildcard path arguments for native executables, so do not pass `test_p3d_*.py` directly to `python.exe`; the `Get-ChildItem` expansion above intentionally converts them into explicit paths.

The tool-side suite covers symmetric secret masking, safe evidence-field preservation, actual JSONL secret absence, loopback bind/admin protection, metadata, DCR, OAuth+PKCE, failed-PKCE code preservation, refresh, role-scoped catalog, read/write calls, dynamic tool addition, and revoke behavior. The app-side isolation test is bidirectional: the preflight tool may not import `app.*`, and Adventure Table `app/*` may not import/reference this standalone tool.

The focused GitHub Actions workflow is `.github/workflows/m04a-non-e2e.yml`. It intentionally runs no Playwright/E2E tests.

## A.1 curl smoke

Keep the server and tunnel running. These commands use `curl.exe` so PowerShell does not substitute `Invoke-WebRequest`.

Set the public origin and verify the two metadata endpoints plus the unauthenticated MCP probe:

```powershell
$base = $env:M04A_PUBLIC_BASE_URL
curl.exe -sS -o NUL -w "%{http_code}`n" "$base/.well-known/oauth-protected-resource"
curl.exe -sS -o NUL -w "%{http_code}`n" "$base/.well-known/oauth-authorization-server"
curl.exe -sS "$base/mcp"
```

Expected: `200`, `200`, then `MCP endpoint`.

The following helper performs DCR, PKCE authorization, and code-to-token exchange for a chosen simulated role. It deliberately does not follow the callback redirect.

```powershell
function New-M04APreflightToken([string]$Role) {
    $redirect = "https://client.example/callback"
    $registrationJson = '{"redirect_uris":["https://client.example/callback"],"token_endpoint_auth_method":"none"}'
    $registration = curl.exe -sS -X POST "$base/register" `
        -H "Content-Type: application/json" `
        --data $registrationJson | ConvertFrom-Json
    $clientId = $registration.client_id

    $verifier = "v" * 64
    $sha256 = [Security.Cryptography.SHA256]::Create()
    $digest = $sha256.ComputeHash([Text.Encoding]::ASCII.GetBytes($verifier))
    $challenge = [Convert]::ToBase64String($digest).TrimEnd('=').Replace('+','-').Replace('/','_')

    $authorizeUrl = "$base/authorize?client_id=$([uri]::EscapeDataString($clientId))&redirect_uri=$([uri]::EscapeDataString($redirect))&response_type=code&scope=$([uri]::EscapeDataString('mcp:read mcp:write mcp:dm'))&state=smoke&code_challenge=$([uri]::EscapeDataString($challenge))&code_challenge_method=S256"
    curl.exe -sS -o NUL -w "%{http_code}`n" $authorizeUrl

    $headers = curl.exe -sS -D - -o NUL -X POST "$base/authorize" `
        -H "Content-Type: application/x-www-form-urlencoded" `
        --data-urlencode "client_id=$clientId" `
        --data-urlencode "redirect_uri=$redirect" `
        --data-urlencode "response_type=code" `
        --data-urlencode "scope=mcp:read mcp:write mcp:dm" `
        --data-urlencode "state=smoke" `
        --data-urlencode "code_challenge=$challenge" `
        --data-urlencode "code_challenge_method=S256" `
        --data-urlencode "role=$Role" `
        --data-urlencode "password=$env:M04A_TEST_PASSWORD"

    $locationLine = ($headers -split "`r?`n" | Where-Object { $_ -match '^location:' } | Select-Object -First 1)
    $location = $locationLine.Substring($locationLine.IndexOf(':') + 1).Trim()
    $encodedCode = [regex]::Match($location, '[?&]code=([^&]+)').Groups[1].Value
    $code = [uri]::UnescapeDataString($encodedCode)

    $token = curl.exe -sS -X POST "$base/token" `
        -H "Content-Type: application/x-www-form-urlencoded" `
        --data-urlencode "grant_type=authorization_code" `
        --data-urlencode "client_id=$clientId" `
        --data-urlencode "redirect_uri=$redirect" `
        --data-urlencode "code=$code" `
        --data-urlencode "code_verifier=$verifier" | ConvertFrom-Json

    return @{ client_id = $clientId; access_token = $token.access_token; refresh_token = $token.refresh_token }
}
```

Authorize as DM, then check discovery plus read/write:

```powershell
$dm = New-M04APreflightToken "dm"
$auth = "Authorization: Bearer $($dm.access_token)"

$tools = curl.exe -sS -X POST "$base/mcp" -H $auth -H "Content-Type: application/json" `
    --data '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | ConvertFrom-Json
$tools.result.tools | ForEach-Object { $_.name }

curl.exe -sS -X POST "$base/mcp" -H $auth -H "Content-Type: application/json" `
    --data '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_context","arguments":{}}}'

curl.exe -sS -X POST "$base/mcp" -H $auth -H "Content-Type: application/json" `
    --data '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"post_note","arguments":{"text":"smoke"}}}'
```

The DM list must contain `dm_only_ping`; `post_note` must return `seq: 1`.

Now prove the admin boundary and dynamic tool:

```powershell
curl.exe -sS -o NUL -w "%{http_code}`n" -X POST "$base/admin/add-tool"
curl.exe -sS -X POST "http://127.0.0.1:8788/admin/add-tool"

$tools2 = curl.exe -sS -X POST "$base/mcp" -H $auth -H "Content-Type: application/json" `
    --data '{"jsonrpc":"2.0","id":4,"method":"tools/list","params":{}}' | ConvertFrom-Json
$tools2.result.tools | ForEach-Object { $_.name }
```

Expected: public admin request `404`, loopback admin `{"ok":true,"tool":"late_tool"}`, and the next raw `tools/list` contains `late_tool`.

Authorize again as Player and confirm the server-side catalog no longer contains the DM-only tool:

```powershell
$player = New-M04APreflightToken "player"
$playerAuth = "Authorization: Bearer $($player.access_token)"
$playerTools = curl.exe -sS -X POST "$base/mcp" -H $playerAuth -H "Content-Type: application/json" `
    --data '{"jsonrpc":"2.0","id":5,"method":"tools/list","params":{}}' | ConvertFrom-Json
$playerTools.result.tools | ForEach-Object { $_.name }
```

`dm_only_ping` must be absent.

Finally, verify the token response was logged without plaintext secrets. These searches must return no matching line:

```powershell
Select-String -Path .\logs\m04a-preflight.jsonl -SimpleMatch $dm.access_token
Select-String -Path .\logs\m04a-preflight.jsonl -SimpleMatch $dm.refresh_token
```

For line-numbered evidence:

```powershell
$i = 0
Get-Content .\logs\m04a-preflight.jsonl | ForEach-Object { $i++; "{0,5}: {1}" -f $i, $_ }
```

Record the relevant line numbers in `docs/M04/M04-A_PREFLIGHT.md`.

## A.2-A.6 real web-chat procedure

Follow the platform ladder in the M04 contract. As of 2026-09-11, the official-document check in `M04-A_PREFLIGHT.md` already classifies ChatGPT Plus as plan-limited for full MCP/write, so the live protocol probe moves to **Claude chat personal plan**.

Use the connector URL:

```text
https://YOUR-PUBLIC-HOST/mcp
```

For Claude web, add the remote custom connector under Customize → Connectors, connect it, and complete the OAuth page served by this harness. Then record each step below with the corresponding JSONL line numbers; do not commit the raw log.

1. **A.2 OAuth** — complete one DM authorization. Record which metadata paths were called, whether `/register` was called, redirect URI shape, PKCE, scopes, token grant type, and whether refresh is later used.
2. **A.3 Scan Tools** — record JSON-RPC method order, `MCP-Protocol-Version`, `Mcp-Session-Id` presence, `Accept`, and `_meta`. The server accepts any requested protocol version and supports `initialize`, `notifications/initialized`, `server/discover`, `tools/list`, `tools/call`, and `ping`.
3. **A.4 Read + write** — ask Claude to call `get_context`, then `post_note`. Record the write-confirmation UX and whether confirmation can be disabled.
4. **A.5 cache / refresh / re-auth** — while still authorized as DM, call loopback `POST /admin/add-tool`; observe whether `late_tool` appears without user action. Then re-authorize as Player and observe whether `dm_only_ping` disappears and what refresh/reconnect action is required. Next call loopback `POST /admin/revoke-all` and observe whether the platform refreshes, asks to authorize again, or surfaces an error. Finally compare two conversations using the same connector: compare their JSONL `observation.authorization_fingerprint` values to determine whether the same access credential was used without exposing the credential itself.
5. **A.6 long poll** — call `wait_seconds` with 10, 30, and 60. If 60 succeeds, continue with 90 and 120. Record the tunnel provider/mode for every attempt. Any 90/120 failure seen only through a Quick Tunnel must be repeated through Tailscale Funnel or a stable/named tunnel before it is classified as a platform timeout.

Do not infer M04-B behavior until those observations are written into `docs/M04/M04-A_PREFLIGHT.md` under the six fixed architecture-conclusion headings.
