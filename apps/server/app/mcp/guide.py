from __future__ import annotations

from typing import Literal, cast

from app.content.localization import require_content_locale
from app.domain.rooms.ai_guidance import (
    WAIT_RETRY_COUNT,
    WAIT_TIMEOUT_SECONDS,
    render_briefing,
    role_rule,
    wait_rule,
)
from app.mcp.guide_tool_names import guide_tool_names
from app.mcp.protocol import MCP_PROTOCOL_VERSION
from app.mcp.tools import tool_reference_rows

Locale = Literal["en", "zh-TW"]


def _validated_locale(locale: str) -> Locale:
    return cast(Locale, require_content_locale(locale))


def _python_client_example(locale: Locale) -> str:
    names = guide_tool_names()
    heading = (
        "最小 Python 3 stdlib client 範例（約 40 行；提供 call / wait）"
        if locale == "zh-TW"
        else "Minimal Python 3 stdlib client example (~40 lines; provides call / wait)"
    )
    comments = (
        "# 僅適用於可直接對外連網的 code-execution client；網頁版 chat 請走 connector。"
        if locale == "zh-TW"
        else "# Only for code-execution clients with outbound network access; web chat should use the connector."
    )
    return f'''{heading}:
```python
import json
import os
import urllib.request

URL = os.environ.get("AT_MCP_URL", "https://<host>/mcp")
TOKEN = os.environ.get("AI_JOIN_TOKEN", "<AI_JOIN_TOKEN>")
VERSION = "{MCP_PROTOCOL_VERSION}"
{comments}

def call(name, arguments=None):
    body = {{
        "jsonrpc": "2.0",
        "id": name,
        "method": "tools/call",
        "params": {{"name": name, "arguments": arguments or {{}}}},
        "_meta": {{
            "io.modelcontextprotocol/protocolVersion": VERSION,
            "clientCapabilities": {{}},
        }},
    }}
    req = urllib.request.Request(
        URL,
        data=json.dumps(body).encode(),
        headers={{
            "Authorization": f"Bearer {{TOKEN}}",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": VERSION,
            "Mcp-Method": "tools/call",
            "Mcp-Name": name,
        }},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=135) as response:
        return json.load(response)

def wait(after_seq, timeout=120):
    return call("{names.wait_event}", {{
        "after_seq": after_seq,
        "limit": 50,
        "timeout": timeout,
    }})

context = call("{names.context}")
print(json.dumps(context, ensure_ascii=False, indent=2))
```
'''


def _response_examples(locale: Locale) -> str:
    if locale == "zh-TW":
        return '''【三種回應形態】
成功（讀 `result.structuredContent.data`）：
```json
{"jsonrpc":"2.0","id":"get_session_context","result":{"structuredContent":{"ok":true,"data":{"mode":"active_session"}},"isError":false}}
```
業務錯誤（HTTP 可為 200；讀 `result.isError` 與 `structuredContent.error`）：
```json
{"jsonrpc":"2.0","id":"request_check","result":{"structuredContent":{"ok":false,"error":{"code":"permission_denied","messages":{"en":"...","zh-TW":"..."}}},"isError":true}}
```
協定錯誤（JSON-RPC `error`，並帶穩定 code）：
```json
{"jsonrpc":"2.0","id":null,"error":{"code":-32600,"message":"...","data":{"code":"mcp_invalid_request"}}}
```
'''
    return '''[Three response shapes]
Success (read `result.structuredContent.data`):
```json
{"jsonrpc":"2.0","id":"get_session_context","result":{"structuredContent":{"ok":true,"data":{"mode":"active_session"}},"isError":false}}
```
Business error (HTTP may still be 200; read `result.isError` and `structuredContent.error`):
```json
{"jsonrpc":"2.0","id":"request_check","result":{"structuredContent":{"ok":false,"error":{"code":"permission_denied","messages":{"en":"...","zh-TW":"..."}}},"isError":true}}
```
Protocol error (JSON-RPC `error` with a stable code):
```json
{"jsonrpc":"2.0","id":null,"error":{"code":-32600,"message":"...","data":{"code":"mcp_invalid_request"}}}
```
'''


def _http_contract(locale: Locale) -> str:
    names = guide_tool_names()
    if locale == "zh-TW":
        header = "【HTTP 契約】"
        notes = (
            "不要送 Mcp-Session-Id；不需要 initialize。Body 的 _meta 必須包含 "
            "io.modelcontextprotocol/protocolVersion 與 clientCapabilities。"
        )
    else:
        header = "[HTTP contract]"
        notes = (
            "Do not send Mcp-Session-Id; initialize is not required. Body _meta must include "
            "io.modelcontextprotocol/protocolVersion and clientCapabilities."
        )
    return f'''{header}
POST /mcp
Authorization: Bearer <AI_JOIN_TOKEN>
Content-Type: application/json
MCP-Protocol-Version: {MCP_PROTOCOL_VERSION}
Mcp-Method: tools/call
Mcp-Name: {names.context}
{notes}

{_python_client_example(locale)}
{_response_examples(locale)}'''


def render_guide(locale: Locale | str) -> str:
    locale = _validated_locale(locale)
    names = guide_tool_names()
    rows = tool_reference_rows(None)

    if locale == "zh-TW":
        intro = "Adventure Table AI 接入指引（ChatGPT Web／MCP client／純 HTTP）"
        web = (
            "【1. ChatGPT Web／connector】\n"
            "新增 Adventure Table connector，URL 指向 https://<host>/mcp；OAuth 授權頁出現時貼上 AI Join Token。"
            "換 Seat／Role 必須重新 authorize；開始 Session 或換 Role 後若工具仍是舊快照，請 Refresh／重新掃描工具，必要時開新對話。"
        )
        bearer = "【2. MCP client（Bearer）】\n以 Authorization: Bearer <AI_JOIN_TOKEN> 連到 /mcp。"
        http = (
            "【3. 有 shell 或可對外連網 code execution 的 AI：純 HTTP】\n"
            "只適用於能直接對外連網的 AI；網頁版 chat sandbox 通常不能直接連外，請改走 connector。"
        )
        flow = (
            f"【進場與事件迴圈】\n第一步永遠呼叫 {names.context}。mode=pre_session 時再呼叫 {names.start}；"
            "mode=active_session 時直接續場。事件 cursor 使用 runtime.last_event_seq／回傳 cursor，永遠只往前。"
        )
        rules = f"【DM 守則】\n{role_rule(role='dm', locale=locale)}\n\n【Player 守則】\n{role_rule(role='player', locale=locale)}"
        unauth = "收到 401 ai_token_unauthorized 時停止並告知使用者，不要重試；token 用完或不再需要時請由人類撤銷。"
        tool_heading = "【工具表】"
    else:
        intro = "Adventure Table AI Join Guide (ChatGPT Web / MCP client / raw HTTP)"
        web = (
            "[1. ChatGPT Web / connector]\n"
            "Add the Adventure Table connector at https://<host>/mcp and paste the AI Join Token when OAuth asks for it. "
            "Changing Seat/Role requires a new authorization. After Session start or a role change, Refresh/rescan if the host still shows a stale tool snapshot; a new chat may be required."
        )
        bearer = "[2. MCP client (Bearer)]\nConnect to /mcp with Authorization: Bearer <AI_JOIN_TOKEN>."
        http = (
            "[3. AI with shell or outbound-network code execution: raw HTTP]\n"
            "Only use this path when the client can make outbound requests. Web-chat sandboxes should use the connector instead."
        )
        flow = (
            f"[Entry and event loop]\nAlways call {names.context} first. If mode=pre_session, call {names.start}; "
            "if mode=active_session, continue the table. Advance from runtime.last_event_seq / returned cursors and never move the cursor backwards."
        )
        rules = f"[DM rules]\n{role_rule(role='dm', locale=locale)}\n\n[Player rules]\n{role_rule(role='player', locale=locale)}"
        unauth = "On 401 ai_token_unauthorized, stop and tell the user; do not retry. Ask the human to revoke the token when it is no longer needed."
        tool_heading = "[Tools]"

    tool_lines = [tool_heading]
    for row in rows:
        required = ", ".join(row["required_params"]) or "-"
        roles = ", ".join(row["roles"])
        tool_lines.append(f"- {row['name']} | required: {required} | role: {roles} | {row['description']}")

    return "\n\n".join(
        [
            intro,
            web,
            bearer,
            http,
            _http_contract(locale),
            "\n".join(tool_lines),
            flow,
            wait_rule(locale),
            rules,
            unauth,
        ]
    ) + "\n"


__all__ = [
    "Locale",
    "WAIT_RETRY_COUNT",
    "WAIT_TIMEOUT_SECONDS",
    "render_briefing",
    "render_guide",
]
