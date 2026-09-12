# M04-B Closeout Checklist

M04-B — Adventure Table Web Chat Integration。此文件依 [實作規格](實作規格.md) B.1～B.8 與 [測試指南](測試指南.md) B.1～B.9 收斂證據。

> 狀態：**closeout gates 全部完成。** 自動 gate（B.1～B.7、B.9 回歸）與 B.8 真實 ChatGPT Web DM + Player 兩場皆於 2026-09-12 完成，證據見下。

## 自動 gate 證據（B.1～B.7、B.9）

- Branch：`m04-b-web-chat-integration`
- Verified implementation SHA：`04f9527`（`e272b9c` + public origin 修正；測試加速 commit `ddc2806` 不動產品碼）
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
- 平台方案／可辨識版本：ChatGPT Web，個人 Plus（與 M04-A 同一帳號）；connector 名稱 `AT mcp`；DCR `client_name: "ChatGPT"`
- Protocol version：`2026-07-28`（依 M04-A）
- 認證形態：OAuth authorization-code + PKCE S256，DCR public client，authorize 頁貼 AI Join Token
- 時間限制：pre-session AI DM grant TTL 15 分鐘（`DEFAULT_PRE_SESSION_DM_TTL`）；authorization code 5 分鐘；access token 1 小時；refresh 30 天。

## B.8 DM 場（2026-09-12 06:12–06:28 UTC）

Room `666` / Campaign `test-1` / DM Seat「AI」；Session `16d3efa6`。時間取自 server access log（UTC）與 `session_events.created_at`；token、code、state、PKCE 均未落地，log 只有路徑與狀態碼。

| 步驟 | 證據 |
|---|---|
| Lobby 產生 AI DM 憑證 | pre-session grant `38b4a583`（generation 1）；Owner 於 Lobby DM Seat 面板產生，token 只顯示一次 |
| ChatGPT 加 connector、OAuth 貼 token | 06:12 `GET /.well-known/oauth-protected-resource` 200、`GET /.well-known/oauth-authorization-server` 200 → `POST /mcp/oauth/register` 201 → `GET /mcp/oauth/authorize?…&ui_locales=zh-TW` 200（雙語頁，zh-TW）→ `POST /mcp/oauth/authorize` 302 → `POST /mcp/oauth/token` 200；DB：`ai_oauth_clients` 1 筆（ChatGPT）、`ai_oauth_authorizations` `6a521785` 綁 grant `38b4a583`、access + refresh 各 1 筆只有 hash |
| Scan Tools 看到的清單 | start_session 前：`get_session_context`、`start_session`（pre-session DM 最小 catalog，與 P3-E 一致，測試指南 2.3 第二列）|
| `get_session_context` → `start_session` | 06:16:26 `server/discover`、`tools/list` → 06:17:05 `get_session_context` → 06:19:06 `start_session`；Session `16d3efa6` active。AI 從 connector 加好到第一次成功 `get_session_context` 的 tool call 次數：**1** |
| catalog 更新 | start_session 後 DM catalog 變成完整工具集；舊對話看不到新工具（AI 自述「只暴露兩個工具」）。connector **Refresh + 新對話**後可見 `post_narration`／`wait_for_event`，與 M04-A A.5 結論一致 |
| `post_narration` → `wait_for_event` → Human Player 回應 → AI 再回應 | 06:19:32 seq 1 `exploration.narration` → 06:19:39–06:20:39 `wait_for_event` 60s 逾時（正常空回傳）→ 06:21:01 再 wait → 06:21:35 Human「灰」送 `/action` seq 2 `exploration.action`，**wait 同秒回傳** → 06:23:56 seq 3 `exploration.narration`（AI 回應）|
| Owner revoke → AI 下一次呼叫失效；refresh 也被拒 | DM Seat 在 Session 進行中不可改 controller（`_require_mutable_controller`），Owner 非本場 DM 只有 Abandon：06:27:40.861 seq 5 `session.abandoned`；`ai_controller_grants.revoked_at` 與 `ai_oauth_authorizations.revoked_at` **同一 timestamp**（同 transaction）→ 06:27:54 AI `get_session_context` `POST /mcp` **401** → 06:27:55 ChatGPT 自動 refresh `POST /mcp/oauth/token` **400** `oauth_invalid_grant` → ChatGPT 顯示「你的 AT mcp 連線已過期。請先重新連線」|

## B.8 Player 場（2026-09-12 06:32–06:40 UTC）

同 Room／Campaign；Human 坐 DM Seat 與 Player Seat「灰」開新 Session `049c9865`，再於 Session 畫面把「灰」交給 AI。

| 步驟 | 證據 |
|---|---|
| Human DM 開場、Player Seat `Let AI Control` | 06:32:46 seq 1 `controller.changed` `human_handoff` → ai；grant `4931a3d6`（generation 4，綁進行中 Session，無 pre-session TTL）|
| ChatGPT OAuth 貼 token | 06:33:25 舊 access token `POST /mcp` 401 → 06:33:26 refresh 400（DM 場 family 已死）→ 按「重新連線」：06:33:30 `GET /mcp/oauth/authorize` 200 → 06:33:47 `POST` 302 → 06:33:50 `POST /mcp/oauth/token` 200。**同一個 DCR `client_id`、新 authorization `dfea656a`**（B.3：client_id 非授權識別，一張 grant 一個 family）|
| Scan Tools 看到的清單 | Refresh + 新對話後為 Player catalog（`post_dialogue`、`roll_pending`、`wait_for_event`…，無 DM 工具）|
| `post_dialogue` | 06:34:02 `get_session_context`（reconnect 後第 1 次呼叫即成功）→ 06:34:13 seq 3 `exploration.dialogue` |
| Human DM 回應 → AI wait 收到 | 06:34:31 Human DM narration seq 4，AI `wait_for_event` 同秒回傳；06:35:33 seq 5 narration |
| Human DM `request_check` → AI `roll_pending` | 06:37:49 seq 6 `roll.requested`（WIS，roll_request `c0f4ed88`）→ 06:38:19 AI `roll_pending` → seq 7 `roll.resolved`，`1d20+0` = 8，`source: server`，roll_result **`64f906e8`** |
| Human `Take Back Control` → AI 下一次呼叫失效；refresh 也被拒 | 06:39:35.180 seq 8 `controller.changed` `take_back` → human，Seat `controller_epoch` 4 → 5；06:39:35.182 grant `4931a3d6` 與 authorization `dfea656a` 同一 timestamp revoked → 06:39:55 AI `POST /mcp` **401** → 06:39:56 refresh **400** `oauth_invalid_grant` → ChatGPT「重新連接」對話框 |

- AI 從 connector 加好（reconnect）到第一次成功 `get_session_context` 的 tool call 次數：**1**

## 觀察（非 blocker，交 M04-C）

1. ChatGPT 在每次 401 後先探 `GET /.well-known/oauth-protected-resource/mcp` 與 `GET /mcp/.well-known/oauth-protected-resource`（RFC 9728 路徑變體）各 404，才退回根路徑 200。可考慮同時提供路徑變體。
2. ChatGPT 每次連線的第一個 `POST /mcp` 回 **400**（非 401），推測是缺 `_meta` 或 legacy 探針；ChatGPT 仍自行走 discovery，未阻塞。M04-C 若要精確記錄該探針形狀需加 wire log。
3. AI 收到 `wait_for_event` 事件後傾向直接在 ChatGPT 對話回覆、不呼叫 `post_narration`；被提醒後又多貼一句「收到玩家回應：…」（seq 4）。這正是 M04-C `briefing`／tool description 要解決的行為缺口。
4. start_session 前後 DM catalog 不同，需要 Refresh + 新對話；M04-C 的 kit／guide 應明寫這一步。
5. Owner 非本場 DM 時 UI 只提供 Abandon；AI DM 的「revoke」實際路徑是 Abandon／End，行為符合 B.2。

## Closeout status

- B.1～B.7、B.9：✅ 自動證據見上
- B.8 DM 場：✅ 2026-09-12
- B.8 Player 場：✅ 2026-09-12
- Subphase 關門 gate：全套 backend pytest 0 failed、`docker compose config` OK、diff 未碰 `apps/web/src` 故不跑 E2E

**M04-B 關門 ✅。** 下一步 M04-C。
