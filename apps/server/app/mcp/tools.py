from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.domain.rooms.ai_tools import (
    AIToolApplicationService,
    CharacterStateToolInput,
    EventsInput,
    PhysicalRollInput,
    QuickRollToolInput,
    RequestCheckToolInput,
    RollPendingInput,
    StageTextInput,
    TextActionInput,
    WaitEventsInput,
)
from app.domain.rooms.exploration import ExplorationInputKind
from app.domain.rooms.rolls import CheckReferenceInvalidError


class _NoArguments(StrictModel):
    pass


_WHEN_TO_USE: dict[str, tuple[str, str]] = {
    "get_session_context": (
        "Call first on connection and again whenever Session state, visible events, pending rolls, or control may have changed. Connection status must never be inferred from tool discovery or a connector rescan; call this tool and use its actual result.",
        "連線後第一個呼叫；Session 狀態、可見事件、待擲骰或控制權可能改變時再次讀取。連線狀態不可從工具清單或重新掃描推測，必須實際呼叫本工具並依其結果判定。",
    ),
    "start_session": (
        "Use only with a pre-session AI DM grant after get_session_context reports mode=pre_session.",
        "只在 get_session_context 回報 mode=pre_session，且目前是開場前 AI DM grant 時使用。",
    ),
    "get_character_context": (
        "Use when an AI Player needs its own active Character build/context before deciding an action.",
        "AI Player 需要確認自己目前角色資料再決定行動時使用。",
    ),
    "post_dialogue": (
        "Use for words spoken by a Character; a DM acting for a Player must identify that subject Seat.",
        "角色實際說出口的話使用；DM 代 Player 說話時要指定 subject Seat。",
    ),
    "post_action": (
        "Use for an intended in-world action before any formal Check is requested.",
        "描述角色想做的世界內行動；正式 Check 建立前先用這個表達意圖。",
    ),
    "post_ooc": (
        "Use only for table-facing out-of-character coordination, not narration or private DM communication.",
        "只用於桌上可見的場外協調，不取代敘事或私下 DM 訊息。",
    ),
    "whisper_dm": (
        "Player-only private communication to the current DM when information should not be public.",
        "Player 要私下告知目前 DM、且內容不應公開時使用。",
    ),
    "post_narration": (
        "DM uses this for player-facing narration and table responses; do not leave the response only in host chat.",
        "DM 對玩家的敘事與桌面回應使用；不要只回在承載 AI 的聊天視窗。",
    ),
    "set_stage_text": (
        "DM uses this when the persistent Main Stage text itself should change; never place secrets there.",
        "DM 需要修改持續顯示的 Main Stage 文字時使用；秘密資訊不可放入 Stage。",
    ),
    "request_check": (
        "DM uses this to create a formal ability/skill/check roll after a Player has described the attempt. A successful call automatically posts the scoped roll prompt to table chat; do not call post_narration merely to ask for the same roll. skill_ref takes a skill index like 'investigation'; ability_ref takes an ability like 'dexterity'.",
        "Player 描述嘗試後，DM 要建立正式能力／技能／檢定擲骰時使用。成功後會自動在桌上聊天顯示符合權限範圍的擲骰提示；不要只為重複要求同一次擲骰而另呼叫 post_narration。skill_ref 用技能名如 'investigation'，ability_ref 用屬性如 'dexterity'。",
    ),
    "roll_pending": (
        "Use only to resolve a visible pending formal roll with server RNG.",
        "只用來以 server RNG 完成目前可見且待處理的正式擲骰。",
    ),
    "submit_physical_roll": (
        "Use only when resolving a pending formal roll from physical d20 values supplied by the human.",
        "人類提供實體 d20 點數、要完成待處理正式擲骰時使用。",
    ),
    "quick_roll": (
        "Player convenience dice for non-formal situations; never substitute it for a DM-created formal Check.",
        "Player 的便利骰，只適用非正式情境；不可取代 DM 建立的正式 Check。",
    ),
    "update_character_state": (
        "Use for legal Current State changes such as HP or conditions; never edit Character Build with it.",
        "HP、狀態等合法 Current State 變更使用；不可拿來修改 Character Build。",
    ),
    "get_pending_events": (
        "Use to catch up durable visible events after a known cursor without waiting.",
        "已有 cursor 且要立即補抓之後的 durable 可見事件、不需等待時使用。",
    ),
    "wait_for_event": (
        "Use after processing all known events to wait for new visible table activity; advance the cursor monotonically.",
        "已處理完已知事件後等待新的可見桌面活動；cursor 只能往前。",
    ),
}


@dataclass(frozen=True)
class MCPToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    roles: frozenset[str]
    pre_session: bool = False

    def _parameter_summary(self) -> str:
        schema = self.input_model.model_json_schema()
        definitions = schema.get("$defs", {})

        def resolved_variants(value: dict[str, Any]) -> list[dict[str, Any]]:
            variants = [value]
            variants.extend(
                item for item in value.get("anyOf", []) if isinstance(item, dict)
            )
            resolved: list[dict[str, Any]] = []
            for item in variants:
                ref = item.get("$ref")
                if isinstance(ref, str) and ref.startswith("#/$defs/"):
                    target = definitions.get(ref.removeprefix("#/$defs/"))
                    if isinstance(target, dict):
                        resolved.append(target)
                resolved.append(item)
            return resolved

        parts: list[str] = []
        for name, raw_property in schema.get("properties", {}).items():
            if not isinstance(raw_property, dict):
                parts.append(name)
                continue
            variants = resolved_variants(raw_property)
            details: list[str] = []
            enum_values: list[Any] = []
            for variant in variants:
                values = variant.get("enum")
                if isinstance(values, list):
                    enum_values.extend(
                        value for value in values if value not in enum_values
                    )
            if enum_values:
                details.append("enum=" + "|".join(str(value) for value in enum_values))
            minimum = next(
                (variant["minimum"] for variant in variants if "minimum" in variant),
                None,
            )
            maximum = next(
                (variant["maximum"] for variant in variants if "maximum" in variant),
                None,
            )
            if minimum is not None or maximum is not None:
                lower = minimum if minimum is not None else "-∞"
                upper = maximum if maximum is not None else "∞"
                details.append(f"range={lower}..{upper}")
            if "default" in raw_property:
                details.append(f"default={raw_property['default']}")
            parts.append(f"{name} ({'; '.join(details)})" if details else name)
        return ", ".join(parts) if parts else "none"

    def rich_description(self) -> str:
        schema = self.input_model.model_json_schema()
        required = schema.get("required", [])
        parameter_text = self._parameter_summary()
        required_text = ", ".join(required) if required else "none"
        role_text = ", ".join(sorted(self.roles))
        description_en, separator, description_zh = self.description.partition(" / ")
        if not separator:
            description_zh = self.description
        when_en, when_zh = _WHEN_TO_USE[self.name]
        availability_en, availability_zh = self._availability()
        return (
            f"{description_en} When to use: {when_en} {availability_en} "
            f"Key parameters and legal values: {parameter_text}; required: {required_text}. "
            f"Allowed roles: {role_text}. Respect the current scoped Seat, returned cursor/state, "
            "and idempotency fields when present. / "
            f"{description_zh} 使用時機：{when_zh}{availability_zh} 關鍵參數與合法值：{parameter_text}；"
            f"必填：{required_text}；可用角色：{role_text}。必須遵守目前 scoped Seat、"
            "回傳的 cursor／state，以及存在時的 idempotency 欄位。"
        )

    def _availability(self) -> tuple[str, str]:
        # The catalog is the same before and after start_session (see tool_catalog),
        # so each description states when the call is actually accepted.
        if self.name == "start_session":
            return (
                "Available only before the Session starts; afterwards it returns pre_session_only.",
                "只在 Session 開始前可用；開始後回 pre_session_only。",
            )
        if self.pre_session:
            return (
                "Available both before and after the Session starts.",
                "Session 開始前後皆可用。",
            )
        return (
            "Requires an active Session; before start_session it returns active_session_required.",
            "需要 active Session；start_session 之前呼叫會回 active_session_required。",
        )

    def wire(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.rich_description(),
            "inputSchema": self.input_model.model_json_schema(),
        }


def _desc(en: str, zh: str) -> str:
    return f"{en} / {zh}"


_TOOL_DEFINITIONS = (
    MCPToolDefinition(
        "get_session_context",
        _desc(
            "Read the current scoped table context and visible recent state.",
            "讀取目前 scoped 桌面情境與可見的近期狀態。",
        ),
        _NoArguments,
        frozenset({"player", "dm"}),
        pre_session=True,
    ),
    MCPToolDefinition(
        "start_session",
        _desc(
            "Start the Session using a valid unbound pre-session AI DM grant.",
            "使用有效且尚未綁定 Session 的 AI DM grant 開始 Session。",
        ),
        _NoArguments,
        frozenset({"dm"}),
        pre_session=True,
    ),
    MCPToolDefinition(
        "get_character_context",
        _desc(
            "Read the AI Player's own active Character context.",
            "讀取 AI Player 自己目前使用中的角色資料。",
        ),
        _NoArguments,
        frozenset({"player"}),
    ),
    MCPToolDefinition(
        "post_dialogue",
        _desc("Post Character dialogue.", "送出角色對話。"),
        TextActionInput,
        frozenset({"player", "dm"}),
    ),
    MCPToolDefinition(
        "post_action",
        _desc("Post an Exploration action.", "送出探索行動。"),
        TextActionInput,
        frozenset({"player", "dm"}),
    ),
    MCPToolDefinition(
        "post_ooc",
        _desc("Post an out-of-character message.", "送出場外 OOC 訊息。"),
        TextActionInput,
        frozenset({"player", "dm"}),
    ),
    MCPToolDefinition(
        "whisper_dm",
        _desc("Send a private whisper to the current DM.", "傳送只有自己與目前 DM 可見的密語。"),
        TextActionInput,
        frozenset({"player"}),
    ),
    MCPToolDefinition(
        "post_narration",
        _desc("Post DM narration.", "送出 DM 敘事。"),
        TextActionInput,
        frozenset({"dm"}),
    ),
    MCPToolDefinition(
        "set_stage_text",
        _desc("Replace Main Stage text while retaining its current image.", "更新 Main Stage 文字並保留目前圖片。"),
        StageTextInput,
        frozenset({"dm"}),
    ),
    MCPToolDefinition(
        "request_check",
        _desc("Create one formal Check request group.", "建立一組正式 Check 請求。"),
        RequestCheckToolInput,
        frozenset({"dm"}),
    ),
    MCPToolDefinition(
        "roll_pending",
        _desc("Complete a visible pending formal roll with server RNG.", "用 Server RNG 完成可見且待處理的正式擲骰。"),
        RollPendingInput,
        frozenset({"player", "dm"}),
    ),
    MCPToolDefinition(
        "submit_physical_roll",
        _desc("Submit raw physical d20 values for a pending formal roll.", "提交實體骰的 raw d20 點數來完成正式擲骰。"),
        PhysicalRollInput,
        frozenset({"player", "dm"}),
    ),
    MCPToolDefinition(
        "quick_roll",
        _desc("Roll convenience dice for the AI Player's controlled Seat.", "替 AI Player 自己控制的 Seat 擲便利骰。"),
        QuickRollToolInput,
        frozenset({"player"}),
    ),
    MCPToolDefinition(
        "update_character_state",
        _desc("Apply a legal Current State patch; never edits Character Build.", "套用合法 Current State 變更；不修改 Character Build。"),
        CharacterStateToolInput,
        frozenset({"player", "dm"}),
    ),
    MCPToolDefinition(
        "get_pending_events",
        _desc("Read visible durable table events after a cursor.", "讀取指定 cursor 之後可見的 durable 桌面事件。"),
        EventsInput,
        frozenset({"player", "dm"}),
    ),
    MCPToolDefinition(
        "wait_for_event",
        _desc("Wait asynchronously for visible events after a cursor.", "以非同步方式等待指定 cursor 之後的可見事件。"),
        WaitEventsInput,
        frozenset({"player", "dm"}),
    ),
)


def tool_reference_rows(role: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for definition in _TOOL_DEFINITIONS:
        if role is not None and role not in definition.roles:
            continue
        schema = definition.input_model.model_json_schema()
        rows.append(
            {
                "name": definition.name,
                "description": definition.rich_description(),
                "required_params": tuple(schema.get("required", [])),
                "roles": tuple(sorted(definition.roles)),
                "pre_session": definition.pre_session,
            }
        )
    return rows


def tool_catalog(auth: AIControllerAuthView) -> list[dict[str, Any]]:
    # Role-scoped only. The list is identical before and after start_session so a
    # client that snapshots tools/list once (ChatGPT connectors) can go from the
    # Lobby into the Session without a Refresh; the pre-/active-session gate stays
    # in call_tool (active_session_required / pre_session_only).
    return [
        definition.wire()
        for definition in _TOOL_DEFINITIONS
        if auth.role in definition.roles
    ]


def _definition(name: str) -> MCPToolDefinition | None:
    return next((item for item in _TOOL_DEFINITIONS if item.name == name), None)


def _structured_result(data: dict[str, Any]) -> dict[str, Any]:
    structured = {"ok": True, "data": data}
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(structured, ensure_ascii=False, separators=(",", ":")),
            }
        ],
        "structuredContent": structured,
        "isError": False,
    }


def structured_tool_error(
    code: str,
    message: str,
    message_zh_tw: str,
) -> dict[str, Any]:
    structured = {
        "ok": False,
        "error": {
            "code": code,
            "messages": {
                "en": message,
                "zh-TW": message_zh_tw,
            },
        },
    }
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(structured, ensure_ascii=False, separators=(",", ":")),
            }
        ],
        "structuredContent": structured,
        "isError": True,
    }


async def call_tool(
    service: AIToolApplicationService,
    *,
    token: str,
    auth: AIControllerAuthView,
    name: str,
    arguments: Any,
) -> dict[str, Any]:
    definition = _definition(name)
    if definition is None:
        return structured_tool_error(
            "tool_not_found",
            "Tool is not exposed by Adventure Table",
            "Adventure Table 未提供此工具",
        )
    if auth.role not in definition.roles:
        return structured_tool_error(
            "permission_denied",
            "Current AI Seat role cannot use this tool",
            "目前 AI Seat role 不可使用此工具",
        )
    if auth.session_id is None and not definition.pre_session:
        return structured_tool_error(
            "active_session_required",
            "This tool requires an active Session binding",
            "此工具需要已綁定的 active Session",
        )
    if auth.session_id is not None and definition.name == "start_session":
        return structured_tool_error(
            "pre_session_only",
            "Start is only available before Session binding",
            "Start 只可在 Session 綁定前使用",
        )
    if not isinstance(arguments, dict):
        return structured_tool_error(
            "invalid_arguments",
            "Tool arguments must be an object",
            "工具 arguments 必須是 object",
        )

    try:
        parsed = definition.input_model.model_validate(arguments)

        if name == "get_session_context":
            data = await asyncio.to_thread(
                service.get_session_context,
                token,
                authenticated=auth,
            )
        elif name == "start_session":
            data = await asyncio.to_thread(
                service.start_session,
                token,
                authenticated=auth,
            )
        elif name == "get_character_context":
            data = await asyncio.to_thread(
                service.get_character_context,
                token,
                authenticated=auth,
            )
        elif name == "post_dialogue":
            data = await asyncio.to_thread(
                service.post_text,
                token,
                kind=ExplorationInputKind.DIALOGUE,
                input=parsed,
                authenticated=auth,
            )
        elif name == "post_action":
            data = await asyncio.to_thread(
                service.post_text,
                token,
                kind=ExplorationInputKind.ACTION,
                input=parsed,
                authenticated=auth,
            )
        elif name == "post_ooc":
            data = await asyncio.to_thread(
                service.post_text,
                token,
                kind=ExplorationInputKind.OOC,
                input=parsed,
                authenticated=auth,
            )
        elif name == "whisper_dm":
            data = await asyncio.to_thread(
                service.post_text,
                token,
                kind=ExplorationInputKind.WHISPER_DM,
                input=parsed,
                authenticated=auth,
            )
        elif name == "post_narration":
            data = await asyncio.to_thread(
                service.post_text,
                token,
                kind=ExplorationInputKind.NARRATION,
                input=parsed,
                authenticated=auth,
            )
        elif name == "set_stage_text":
            data = await asyncio.to_thread(
                service.set_stage_text,
                token,
                parsed,
                authenticated=auth,
            )
        elif name == "request_check":
            data = await asyncio.to_thread(
                service.request_check,
                token,
                parsed,
                authenticated=auth,
            )
        elif name == "roll_pending":
            data = await asyncio.to_thread(
                service.roll_pending,
                token,
                parsed,
                authenticated=auth,
            )
        elif name == "submit_physical_roll":
            data = await asyncio.to_thread(
                service.submit_physical_roll,
                token,
                parsed,
                authenticated=auth,
            )
        elif name == "quick_roll":
            data = await asyncio.to_thread(
                service.quick_roll,
                token,
                parsed,
                authenticated=auth,
            )
        elif name == "update_character_state":
            data = await asyncio.to_thread(
                service.update_character_state,
                token,
                parsed,
                authenticated=auth,
            )
        elif name == "get_pending_events":
            data = await asyncio.to_thread(
                service.get_pending_events,
                token,
                parsed,
                authenticated=auth,
            )
        elif name == "wait_for_event":
            data = await service.wait_for_event(
                token,
                parsed,
                authenticated=auth,
            )
        else:  # pragma: no cover - catalog and dispatch are kept exhaustive above.
            return structured_tool_error(
                "tool_not_implemented",
                "Tool dispatch is not implemented",
                "工具 dispatch 尚未實作",
            )
    except ValidationError:
        return structured_tool_error(
            "invalid_arguments",
            "Tool arguments failed schema validation",
            "工具 arguments 未通過 schema 驗證",
        )
    except PermissionError:
        return structured_tool_error(
            "permission_denied",
            "Current AI controller is not permitted to perform this action",
            "目前 AI controller 無權執行此動作",
        )
    except LookupError:
        return structured_tool_error(
            "not_found",
            "Requested table object was not found in the current scope",
            "目前 scope 找不到指定的桌面物件",
        )
    except CheckReferenceInvalidError as exc:
        return structured_tool_error(
            "unknown_check_ref",
            f"Unknown skill/ability reference: {exc}. Use a skill index like "
            "'investigation' or an ability like 'dexterity'.",
            f"無法解析的技能／屬性參照：{exc}。技能用如 'investigation' 的名稱，屬性用如 'dexterity'。",
        )
    except ValueError:
        return structured_tool_error(
            "invalid_arguments",
            "Tool arguments are not valid for the current table state",
            "工具 arguments 不符合目前桌面狀態",
        )
    except RuntimeError:
        return structured_tool_error(
            "table_conflict",
            "The table state changed or does not allow this action",
            "桌面狀態已變更或目前不允許此動作",
        )

    return _structured_result(data)


__all__ = [
    "MCPToolDefinition",
    "call_tool",
    "structured_tool_error",
    "tool_catalog",
    "tool_reference_rows",
]
