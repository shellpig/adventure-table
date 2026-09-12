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


class _NoArguments(StrictModel):
    pass


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
                    enum_values.extend(value for value in values if value not in enum_values)
            if enum_values:
                details.append(
                    "enum=" + "|".join(str(value) for value in enum_values)
                )
            minimum = next(
                (variant["minimum"] for variant in variants if "minimum" in variant),
                None,
            )
            maximum = next(
                (variant["maximum"] for variant in variants if "maximum" in variant),
                None,
            )
            if minimum is not None or maximum is not None:
                details.append(f"range={minimum if minimum is not None else '-∞'}..{maximum if maximum is not None else '∞'}")
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
        return (
            f"{description_en} When to use: call this only when the current table state requires "
            f"{self.name}. Key parameters and legal values: {parameter_text}; required: {required_text}. "
            f"Allowed roles: {role_text}. Respect the current scoped Seat, returned cursor/state, "
            "and idempotency fields when present. / "
            f"{description_zh} 使用時機：目前桌面流程需要 {self.name} 時才呼叫。關鍵參數與合法值：{parameter_text}；"
            f"必填：{required_text}；可用角色：{role_text}。必須遵守目前 scoped Seat、"
            "回傳的 cursor／state，以及存在時的 idempotency 欄位。"
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
    if auth.session_id is None:
        return [
            definition.wire()
            for definition in _TOOL_DEFINITIONS
            if definition.pre_session and auth.role in definition.roles
        ]
    return [
        definition.wire()
        for definition in _TOOL_DEFINITIONS
        if (not definition.pre_session or definition.name == "get_session_context")
        and auth.role in definition.roles
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
