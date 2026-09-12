# M04-B Closeout Checklist

M04-B — Adventure Table Web Chat Integration。此文件依 [實作規格](實作規格.md) B.1～B.8 與 [測試指南](測試指南.md) B.1～B.9 收斂證據。

> 狀態：**B.8 真實目標平台 gate 尚未執行。** 自動 gate（B.1～B.7、B.9 回歸）已於 2026-09-12 全綠；本文件目前只登錄自動證據與 B.8 執行前的準備結果，B.8 兩場完成後再補表。

## 自動 gate 證據（B.1～B.7、B.9）

- Branch：`m04-b-web-chat-integration`
- Verified implementation SHA：`e272b9c`（測試加速 commit `ddc2806` 不動產品碼）
- 本機全套 backend pytest：0 failed（clean worktree @ `e272b9c`）
- `docker compose config`：OK
- CI `M04-B Non-E2E Regression` run `34673796557`：success；含 PostgreSQL 上 `0021_m04b_ai_oauth` upgrade → downgrade → re-upgrade
- E2E：diff 未碰 `apps/web/src`，依測試指南 1.1 不需新 Playwright

| 契約 | 測試檔 |
|---|---|
| B.1 | `tests/test_m04b_oauth_endpoints.py`、`tests/test_m04b_oauth_http.py` |
| B.2 | `tests/test_m04b_oauth_grant_binding.py`、`tests/test_m04b_oauth_authority_states.py`、`tests/test_m04b_mcp_auth.py` |
| B.3 | `tests/test_m04b_oauth_seat_invariant.py`、`tests/test_m04b_oauth_schema.py` |
| B.4 | 不適用（M04-A 結論：不需相容層） |
| B.5 | `tests/test_p3e_mcp_tools.py` 既有 scope 測試 + `test_m04b_oauth_grant_binding.py` |
| B.6 | `tests/test_m04b_wait_timeout_cap.py`（既有上限 60s ≤ 實測 120s，不下修） |
| B.7 | `tests/test_m04b_readme.py` |
| Standalone | `tests/test_p3e_standalone_mcp.py`、`tests/test_m03d_schema_parity.py` |

## B.8 執行前準備（2026-09-12）

- **Public origin 修正**：`request.base_url` 在 Tailscale 之後只看得到 `http://127.0.0.1:8000`，metadata 與 401 challenge 會廣播 loopback URL。新增 `Settings.mcp_public_origin`（env `ADVENTURE_TABLE_MCP_PUBLIC_ORIGIN`）與 `app/mcp/public_origin.py`，`oauth.py` 兩個 metadata endpoint 與 `server.py` 的 `WWW-Authenticate` 共用；`docker-compose.yml` 透傳；測試 `tests/test_m04b_public_origin.py`。
- **Tailscale `--set-path` 實測**：target 不帶路徑時（`--set-path /mcp http://127.0.0.1:8000`）Tailscale 會剝掉 mount 前綴，後端收到 `/`／`/oauth/authorize`；target 帶同一路徑（`http://127.0.0.1:8000/mcp`）則完整保留。未 mount 的 `/`、`/api/rooms`、`/mcpx` 在 Tailscale 端即 404，Room UI 不露出。轉發 header：`X-Forwarded-Proto: https`、`X-Forwarded-Host: <node>.ts.net`、`Host` 為公網 hostname。
- **Tailnet-only 驗證（`tailscale serve`）**：`GET /.well-known/oauth-protected-resource` 與 `/.well-known/oauth-authorization-server` 的 origin 為公網 https；未帶 Bearer 的 `server/discover` 回 401 + `WWW-Authenticate: Bearer resource_metadata="https://<node>.ts.net/.well-known/oauth-protected-resource"`；DCR → `GET /mcp/oauth/authorize?locale=zh-TW` 回 200 雙語表單。DCR 留下一筆 `client_name=prep-probe` 測試 client。
- 入口形態：Tailscale Funnel（public）→ `http://127.0.0.1:8000`，只 mount `/mcp`、`/.well-known/oauth-protected-resource`、`/.well-known/oauth-authorization-server`；指令見 README「讓網頁版 chat 連進來」。
- 平台方案／可辨識版本：（B.8 執行時填）
- Protocol version：`2026-07-28`（依 M04-A）
- 認證形態：OAuth authorization-code + PKCE S256，DCR public client，authorize 頁貼 AI Join Token
- 時間限制：pre-session AI DM grant TTL 15 分鐘（`DEFAULT_PRE_SESSION_DM_TTL`）；authorization code 5 分鐘；access token 1 小時；refresh 30 天。

## B.8 DM 場

| 步驟 | 證據 |
|---|---|
| Lobby 產生 AI DM 憑證 | |
| ChatGPT 加 connector、OAuth 貼 token | |
| Scan Tools 看到的清單 | |
| `get_session_context` → `start_session` | |
| `post_narration` → `wait_for_event` → Human Player 回應 → AI 再回應 | |
| Owner revoke → AI 下一次呼叫失效；refresh 也被拒 | |

- AI 從 connector 加好到第一次成功 `get_session_context` 的 tool call 次數：

## B.8 Player 場

| 步驟 | 證據 |
|---|---|
| Human DM 開場、Player Seat `Let AI Control` | |
| ChatGPT OAuth 貼 token | |
| Scan Tools 看到的清單 | |
| `post_dialogue` | |
| Human DM `request_check` → AI `roll_pending` | |
| Human `Take Back Control` → AI 下一次呼叫失效；refresh 也被拒 | |

- AI 從 connector 加好到第一次成功 `get_session_context` 的 tool call 次數：

## Closeout status

- B.1～B.7、B.9：✅ 自動證據見上
- B.8 DM 場：⬜
- B.8 Player 場：⬜
