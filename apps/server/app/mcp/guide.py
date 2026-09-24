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
from app.mcp.protocol import (
    CLIENT_CAPABILITIES_META_KEY,
    MCP_PROTOCOL_VERSION,
    PROTOCOL_VERSION_META_KEY,
)
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
        "params": {{
            "name": name,
            "arguments": arguments or {{}},
            "_meta": {{
                "{PROTOCOL_VERSION_META_KEY}": VERSION,
                "{CLIENT_CAPABILITIES_META_KEY}": {{}},
            }},
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

def wait(after_seq, timeout={WAIT_TIMEOUT_SECONDS}):
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
    names = guide_tool_names()
    success = (
        '{"jsonrpc":"2.0","id":"' + names.context
        + '","result":{"structuredContent":{"ok":true,"data":{"mode":"active_session"}},"isError":false}}'
    )
    business = (
        '{"jsonrpc":"2.0","id":"' + names.request_check
        + '","result":{"structuredContent":{"ok":false,"error":{"code":"permission_denied","messages":{"en":"...","zh-TW":"..."}}},"isError":true}}'
    )
    protocol = '{"jsonrpc":"2.0","id":null,"error":{"code":-32600,"message":"...","data":{"code":"mcp_invalid_request"}}}'
    if locale == "zh-TW":
        return (
            "【三種回應形態】\n"
            "成功（讀 `result.structuredContent.data`）：\n```json\n" + success + "\n```\n"
            "業務錯誤（HTTP 可為 200；讀 `result.isError` 與 `structuredContent.error`）：\n```json\n" + business + "\n```\n"
            "協定錯誤（JSON-RPC `error`，並帶穩定 code）：\n```json\n" + protocol + "\n```\n"
        )
    return (
        "[Three response shapes]\n"
        "Success (read `result.structuredContent.data`):\n```json\n" + success + "\n```\n"
        "Business error (HTTP may still be 200; read `result.isError` and `structuredContent.error`):\n```json\n" + business + "\n```\n"
        "Protocol error (JSON-RPC `error` with a stable code):\n```json\n" + protocol + "\n```\n"
    )


def _http_contract(locale: Locale) -> str:
    names = guide_tool_names()
    if locale == "zh-TW":
        header = "【HTTP 契約】"
        notes = (
            "不要送 Mcp-Session-Id；不需要 initialize。Body 的 params._meta 必須包含 "
            f"{PROTOCOL_VERSION_META_KEY} 與 {CLIENT_CAPABILITIES_META_KEY}。"
        )
    else:
        header = "[HTTP contract]"
        notes = (
            "Do not send Mcp-Session-Id; initialize is not required. Body params._meta must include "
            f"{PROTOCOL_VERSION_META_KEY} and {CLIENT_CAPABILITIES_META_KEY}."
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
            "工具清單在 Session 開始前後相同，start_session 後不需要 Refresh。換 Seat／Role 必須重新 authorize；換 Role 後若工具仍是舊快照，請 Refresh／重新掃描工具並開新對話。"
        )
        bearer = "【2. MCP client（Bearer）】\n以 Authorization: Bearer <AI_JOIN_TOKEN> 連到 /mcp。"
        http = (
            "【3. 有 shell 或可對外連網 code execution 的 AI：純 HTTP】\n"
            "只適用於能直接對外連網的 AI；網頁版 chat sandbox 通常不能直接連外，請改走 connector。"
        )
        flow = (
            f"【進場與事件迴圈】\n第一步永遠呼叫 {names.context}。mode=pre_session 時再呼叫 {names.start}；"
            "mode=active_session 時直接續場。事件 cursor 使用 runtime.last_event_seq／回傳 cursor，永遠只往前。\n"
            f"開場後 Stage 是空的：context 的 stage_unset／next_required_action 會指出下一步。"
            f"DM 在 stage_unset 為真時先呼叫 {names.stage_text} 建立場景，再 {names.narration} 敘事。\n"
            "連線判定：只有本回合實際執行工具並取得結果才算呼叫 MCP；查看工具清單或重新掃描不算，也不可據此宣稱連線成功或失敗。"
        )
        combat = (
            f"【戰鬥】\n戰鬥進行中，以 {names.context} 或 {names.combat_context} 讀取當前回合、各戰鬥者與 pending 狀態。"
            f"Player 僅在自己的當前回合或開啟的反應窗口內以 {names.respond_reaction} 行動；"
            f"待擲骰用 {names.roll_pending}，專注豁免用 {names.roll_concentration}。"
            f"空間或規則不確定時由 Player 以 {names.request_adjudication} 提請裁定。"
            f"Attack 的距離裁定用 {names.adjudicate_attack}（in_range true/false）；"
            f"Grapple / Shove 等 reach 裁定用 {names.adjudicate_special_attack}；"
            f"AoE 法術受影響目標用 {names.resolve_aoe_spell}；"
            f"Opportunity Attack 與 Player 提請的特殊裁定用 {names.resolve_adjudication}。"
            "context 的 next_required_action 會直接指出該用哪一個。"
            f"輪到怪物時 DM 結算敵方動作並呼叫 {names.advance_turn} 推進回合；Player 回合 action 用完且無待處理事項時（next_required_action 為 advance_turn）同樣由 DM 推進。"
            f"環境或陷阱傷害用 {names.quick_roll} 擲骰再以 {names.apply_damage} 寫回，不要自行指定數字。"
            "DM 敘事只描述傷勢等級，不得說出敵人精確 HP。"
            f"每次結算後立即呼叫 {names.wait_event}，不要停在 host chat。"
        )
        world = (
            f"【Adventure 與世界狀態（DM）】\n{names.context} 的 campaign_context.attached_adventure_count 大於 0 表示 Campaign 附加了 Adventure。"
            f"用 {names.campaign_context} 讀 attached_adventures[].outline：這是 Adventure 目錄（條目 id、kind、title、visibility，不含內文），"
            f"再用 {names.adventure_entry} 依 id 讀需要的條目；dm_only 條目與秘密只給 DM，不得寫入 Stage 或公開 narration。"
            f"current_scene.kind 為 none 時，從目錄挑開場 scene，以 {names.set_current_context}（expected_revision 為 current_context_revision）設定。"
            f"跑團中世界狀態改變（門被打開、NPC 死亡、物品被取走、真相揭露）時要寫回："
            f"改變既有 Adventure 條目的現況用 {names.set_override}，新增的事實、NPC、物品用 {names.create_world_entry}。"
            "Adventure 原文（baseline）不會被改寫；下一場 Session 讀 context 時會看到寫回後的現況。\n"
            "Adventure 是底稿不是劇本：DM 保留即興與世界裁定權。Adventure 沒提供可行路徑時（例如寫了「擊敗守衛後開門」卻沒有守衛或遭遇），"
            f"不要讓桌面卡住，要像真人 DM 即興補上（新 NPC 用 {names.create_world_entry}、敵人用 Quick Combat），重要的即興內容同樣寫回。"
            "敘事、Stage 文字與寫回內容一律使用玩家使用的語言；Adventure 原文是其他語言時要轉述，不要直接照抄。"
        )
        rules = f"【DM 守則】\n{role_rule(role='dm', locale=locale)}\n\n【Player 守則】\n{role_rule(role='player', locale=locale)}"
        unauth = "收到 401 ai_token_unauthorized 時停止並告知使用者，不要重試；token 用完或不再需要時請由人類撤銷。"
        tool_heading = "【工具表】"
    else:
        intro = "Adventure Table AI Join Guide (ChatGPT Web / MCP client / raw HTTP)"
        web = (
            "[1. ChatGPT Web / connector]\n"
            "Add the Adventure Table connector at https://<host>/mcp and paste the AI Join Token when OAuth asks for it. "
            "The tool list is the same before and after the Session starts, so no Refresh is needed after start_session. Changing Seat/Role requires a new authorization; if the host still shows the old role's tools afterwards, Refresh/rescan and open a new chat."
        )
        bearer = "[2. MCP client (Bearer)]\nConnect to /mcp with Authorization: Bearer <AI_JOIN_TOKEN>."
        http = (
            "[3. AI with shell or outbound-network code execution: raw HTTP]\n"
            "Only use this path when the client can make outbound requests. Web-chat sandboxes should use the connector instead."
        )
        flow = (
            f"[Entry and event loop]\nAlways call {names.context} first. If mode=pre_session, call {names.start}; "
            "if mode=active_session, continue the table. Advance from runtime.last_event_seq / returned cursors and never move the cursor backwards.\n"
            f"After start the Stage is empty: the context's stage_unset / next_required_action name the next step. "
            f"While stage_unset is true a DM calls {names.stage_text} to set the scene before narrating with {names.narration}.\n"
            "Connection check: only an actual tool call this turn that returns a result counts as calling MCP; listing or rescanning tools does not, and connection success/failure must never be inferred from it."
        )
        combat = (
            f"[Combat]\nIn active Combat, call {names.context} or {names.combat_context} to read round, current turn, combatants, and pending actions. "
            f"A Player acts only on their own current turn or within an open reaction window via {names.respond_reaction}; "
            f"pending rolls use {names.roll_pending}, and concentration saves use {names.roll_concentration}. "
            f"When range, cover, or OA is uncertain, a Player calls {names.request_adjudication} to request DM adjudication. "
            f"Attack range adjudication uses {names.adjudicate_attack} (in_range true/false); "
            f"reach adjudication like Grapple / Shove uses {names.adjudicate_special_attack}; "
            f"AoE spell affected targets use {names.resolve_aoe_spell}; "
            f"Opportunity Attack and Player-requested special adjudications use {names.resolve_adjudication}. "
            "The context next_required_action indicates directly which one to use. "
            f"On a Monster turn the DM resolves enemy actions then calls {names.advance_turn} to advance the turn; "
            "when a Player's action is spent with nothing pending (next_required_action is advance_turn) the DM advances as well. "
            f"Environmental or trap damage: roll with {names.quick_roll}, then write it back with {names.apply_damage}; never invent the number. "
            "DM narration describes injury level only and never an enemy's exact HP. "
            f"After each resolution, immediately call {names.wait_event} and never stop in host chat."
        )
        world = (
            f"[Adventure and world state (DM)]\nIn {names.context}, campaign_context.attached_adventure_count > 0 means the Campaign has an Adventure attached. "
            f"Read attached_adventures[].outline with {names.campaign_context}: it is the Adventure's table of contents (entry id, kind, title, visibility; no bodies). "
            f"Then read the entries you need by id with {names.adventure_entry}; dm_only entries and secrets are for the DM only and never go on the Stage or in public narration. "
            f"When current_scene.kind is none, pick the opening scene from the outline and set it with {names.set_current_context} (expected_revision is current_context_revision). "
            "When the world changes during play (a door is opened, an NPC dies, an item is taken, a truth is revealed), write it back: "
            f"use {names.set_override} to change the current state of an existing Adventure entry, and {names.create_world_entry} for new facts, NPCs, or items. "
            "The Adventure text (baseline) is never rewritten; the next Session reads the written-back current state from context.\n"
            "An Adventure is a baseline, not a script: the DM keeps the right to improvise and rule on the world. When the Adventure offers no workable path "
            "(for example it says the door opens after the guardian is defeated but has no guardian or encounter), do not stall the table; "
            f"improvise like a human DM (a new NPC via {names.create_world_entry}, enemies via Quick Combat) and write back improvisations that matter. "
            "Narrate, write the Stage, and write back in the language the players use; when the Adventure text is in another language, render it rather than copying it verbatim."
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
            world,
            combat,
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
