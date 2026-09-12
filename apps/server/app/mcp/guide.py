from __future__ import annotations

from typing import Literal

from app.domain.rooms.ai_tools import WaitEventsInput
from app.mcp.protocol import MCP_PROTOCOL_VERSION
from app.mcp.tools import tool_reference_rows

Locale = Literal["en", "zh-TW"]

WAIT_RETRY_COUNT = 5
WAIT_TIMEOUT_SECONDS = int(
    WaitEventsInput.model_json_schema()["properties"]["timeout"]["maximum"]
)

_DM_RULE_EN = (
    "As DM, use post_narration for table-facing responses. Use request_check to create formal checks. "
    "Do not answer a player only in the host chat; write the response back to the table."
)
_DM_RULE_ZH = (
    "DM 回應玩家時一律用 post_narration 寫回桌上；正式檢定由 request_check 建立。"
    "不要只在承載 AI 的對話視窗回覆。"
)
_PLAYER_RULE_EN = (
    "As Player, use post_dialogue for speech and post_action for intended actions. Player does not have "
    "request_check; describe the attempt with post_action, wait for the DM to create the Check, then use "
    "roll_pending or submit_physical_roll."
)
_PLAYER_RULE_ZH = (
    "Player 用 post_dialogue 說話、用 post_action 描述行動意圖。Player 沒有 request_check；"
    "需要檢定時先 post_action，等 DM 建立 Check，再用 roll_pending 或 submit_physical_roll。"
)


def _wait_rule(locale: Locale) -> str:
    if locale == "zh-TW":
        return (
            f"等待規則：wait_for_event 每次 timeout 最多 {WAIT_TIMEOUT_SECONDS} 秒；逾時沒有事件就直接再等。"
            f"連續最多等 {WAIT_RETRY_COUNT} 次（約 10 分鐘）；仍無事件就停下並告知人類『桌上沒有動靜，需要時叫我』。"
            "收到事件並完成回應後，連續等待計數歸零。"
        )
    return (
        f"Wait rule: call wait_for_event with timeout up to {WAIT_TIMEOUT_SECONDS} seconds. On an empty timeout, wait again immediately. "
        f"Stop after {WAIT_RETRY_COUNT} consecutive empty waits (about 10 minutes) and tell the human that the table is quiet and to call you when needed. "
        "Reset the consecutive-wait count after receiving and responding to an event."
    )


def render_briefing(*, role: str, mode: str) -> str:
    if role not in {"dm", "player"}:
        raise ValueError("unsupported role")
    if mode not in {"pre_session", "active_session"}:
        raise ValueError("unsupported mode")

    if mode == "pre_session":
        return (
            "EN: Read this context, then call start_session. After start_session, refresh/rescan the connector if the host still shows the pre-session tool set. "
            "Full guide: GET /mcp/guide?locale=en.\n"
            "zh-TW：先讀取此 context，再呼叫 start_session。若開始後承載平台仍顯示 pre-session 工具，請 Refresh／重新掃描工具。"
            "完整指引：GET /mcp/guide?locale=zh-TW。"
        )

    role_en = _DM_RULE_EN if role == "dm" else _PLAYER_RULE_EN
    role_zh = _DM_RULE_ZH if role == "dm" else _PLAYER_RULE_ZH
    return (
        f"EN: {role_en} {_wait_rule('en')} Full guide: GET /mcp/guide?locale=en. "
        "If temporary_instruction is non-empty, follow it as an additional temporary instruction.\n"
        f"zh-TW：{role_zh} {_wait_rule('zh-TW')} 完整指引：GET /mcp/guide?locale=zh-TW。"
        "temporary_instruction 若非空，將它視為額外的暫時指示。"
    )[:1200]


def render_guide(locale: Locale) -> str:
    rows = tool_reference_rows(None)
    if locale == "zh-TW":
        intro = "Adventure Table AI 接入指引（網頁版 chat／MCP client／純 HTTP）"
        web = (
            "【1. 網頁版 chat／connector】\n"
            "新增 Adventure Table connector，URL 指向 https://<host>/mcp；OAuth 授權頁出現時貼上 AI Join Token。"
            "若 start_session 後工具仍未更新，請 Refresh／重新掃描工具，必要時開新對話。"
        )
        bearer = "【2. MCP client（Bearer）】\n以 Authorization: Bearer <AI_JOIN_TOKEN> 連到 /mcp。"
        http = (
            "【3. 有 shell 或可對外連網 code execution 的 AI：純 HTTP】\n"
            "本段只適用於能直接對外連網的 AI。網頁版 chat sandbox 通常不能直接連外，請改用 connector。"
        )
        flow = (
            "【進場與事件迴圈】\n先 get_session_context；mode=pre_session 時呼叫 start_session，mode=active_session 時直接續場。"
            "事件 cursor 使用 runtime.last_event_seq／回傳 next cursor；不要倒退。"
        )
        rules = f"【DM 守則】\n{_DM_RULE_ZH}\n【Player 守則】\n{_PLAYER_RULE_ZH}"
        unauth = "收到 401 ai_token_unauthorized 時停止並告知使用者，不要重試。"
    else:
        intro = "Adventure Table AI Join Guide (web chat / MCP client / raw HTTP)"
        web = (
            "[1. Web chat / connector]\nAdd the Adventure Table connector with URL https://<host>/mcp. When OAuth asks for the AI Join Token, paste it there. "
            "After start_session, Refresh/rescan tools if the host still exposes the pre-session catalog; opening a new chat may be required."
        )
        bearer = "[2. MCP client (Bearer)]\nConnect to /mcp with Authorization: Bearer <AI_JOIN_TOKEN>."
        http = (
            "[3. AI with shell or outbound-network code execution: raw HTTP]\n"
            "This section is only for an AI that can make outbound network requests. A web-chat sandbox should use the connector instead."
        )
        flow = (
            "[Entry and event loop]\nCall get_session_context first. If mode=pre_session call start_session; if mode=active_session continue the table. "
            "Advance from runtime.last_event_seq / returned cursors and never move the cursor backwards."
        )
        rules = f"[DM rules]\n{_DM_RULE_EN}\n[Player rules]\n{_PLAYER_RULE_EN}"
        unauth = "On 401 ai_token_unauthorized, stop and tell the user. Do not retry."

    tool_lines = ["[Tools]" if locale == "en" else "【工具表】"]
    for row in rows:
        required = ", ".join(row["required_params"]) or "-"
        roles = ", ".join(row["roles"])
        tool_lines.append(f"- {row['name']} | required: {required} | role: {roles} | {row['description']}")

    contract = f"""[HTTP contract]
POST /mcp
Authorization: Bearer <AI_JOIN_TOKEN>
Content-Type: application/json
MCP-Protocol-Version: {MCP_PROTOCOL_VERSION}
Mcp-Method: tools/call
Mcp-Name: get_session_context
Do not send Mcp-Session-Id. initialize is not required.
Body _meta must include io.modelcontextprotocol/protocolVersion and clientCapabilities.

Example tools/call:
{{"jsonrpc":"2.0","id":"1","method":"tools/call","params":{{"name":"get_session_context","arguments":{{}}}},"_meta":{{"io.modelcontextprotocol/protocolVersion":"{MCP_PROTOCOL_VERSION}","clientCapabilities":{{}}}}}}

Success: result.structuredContent.data
Business error: result.isError=true with structuredContent.error
Protocol error: JSON-RPC error payload with stable error code
"""

    return "\n\n".join(
        [
            intro,
            web,
            bearer,
            http,
            contract,
            "\n".join(tool_lines),
            flow,
            _wait_rule(locale),
            rules,
            unauth,
        ]
    ) + "\n"


__all__ = [
    "WAIT_RETRY_COUNT",
    "WAIT_TIMEOUT_SECONDS",
    "render_briefing",
    "render_guide",
]
