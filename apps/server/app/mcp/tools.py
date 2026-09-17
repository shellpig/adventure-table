from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.domain.combat.ai_tools import (
    CombatEntryMutationToolInput,
    CombatEntryToolInput,
    CombatMutationToolInput,
    CombatRollToolInput,
)
from app.domain.combat.attacks import AttackAdjudicationInput, AttackRequestInput
from app.domain.combat.core_rolls import DeathSaveRequestInput, SavingThrowInput
from app.domain.combat.initiative import (
    FinalizeInitiativeInput,
    RequestInitiativeInput,
)
from app.domain.combat.lifecycle import (
    AddCharacterInput,
    AddMonsterInput,
    CombatActionInput,
    StartCombatInput,
)
from app.domain.combat.monster_instances import (
    CreateMonsterFromContentInput,
    CreateQuickEnemyInput,
)
from app.domain.combat.semantic_hp import SemanticDamageInput, SemanticHealingInput
from app.domain.combat.special_attacks import (
    SpecialAttackAdjudicationInput,
    SpecialAttackRequestInput,
)
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
        "Use only to resolve a visible pending non-combat formal roll with server RNG. P4-C Combat rolls use the matching combat_roll_* tool so the shared Combat transaction resolves the outcome.",
        "只用來以 server RNG 完成目前可見且待處理的非戰鬥正式擲骰。P4-C 戰鬥擲骰要使用對應 combat_roll_* 工具，才能由共用 Combat transaction 完成結果。",
    ),
    "submit_physical_roll": (
        "Use only when resolving a pending non-combat formal roll from physical d20 values supplied by the human.",
        "人類提供實體 d20 點數、要完成待處理的非戰鬥正式擲骰時使用。",
    ),
    "quick_roll": (
        "Player convenience dice for non-formal situations; never substitute it for a DM-created formal Check or Combat RollRequest.",
        "Player 的便利骰，只適用非正式情境；不可取代 DM 建立的正式 Check 或 Combat RollRequest。",
    ),
    "update_character_state": (
        "Use for legal non-Combat Current State changes. During active Combat, HP damage/healing must use combat_apply_damage/combat_apply_healing; this tool never edits Character Build.",
        "用於合法的非戰鬥 Current State 變更。Active Combat 中 HP 傷害／治療必須使用 combat_apply_damage/combat_apply_healing；本工具不修改 Character Build。",
    ),
    "get_pending_events": (
        "Use to catch up durable visible events after a known cursor without waiting.",
        "已有 cursor 且要立即補抓之後的 durable 可見事件、不需等待時使用。",
    ),
    "wait_for_event": (
        "Use after processing all known events to wait for new visible table activity; advance the cursor monotonically.",
        "已處理完已知事件後等待新的可見桌面活動；cursor 只能往前。",
    ),
    "combat_get_active": (
        "Use to read the current Campaign Quick Combat projection for this AI actor; visibility is enforced by the shared Combat service.",
        "用來讀取目前 Campaign 的 Quick Combat 投影；可見性由共用 Combat service 強制處理。",
    ),
    "combat_list_attacks": (
        "Use before declaring an Attack to obtain legal runtime source_ref values for a controlled combatant.",
        "宣告 Attack 前使用，取得受控制 combatant 合法的 runtime source_ref。",
    ),
    "combat_request_attack": (
        "Declare a formal Attack through the shared P4-C service. Quick Combat geometry may return dm_adjudication_required instead of guessing range.",
        "透過共用 P4-C service 宣告正式 Attack。Quick Combat 不猜距離，必要時會回 dm_adjudication_required。",
    ),
    "combat_adjudicate_attack": (
        "Current DM resolves a pending Quick Combat range adjudication. In-range creates the canonical formal Attack RollRequest; out-of-range spends no Attack budget.",
        "目前 DM 裁定待處理的 Quick Combat 距離。可達才建立正式 Attack RollRequest；不可達不消耗 Attack 次數。",
    ),
    "combat_roll_attack": (
        "Resolve a pending Attack RollRequest with server RNG; hit, crit, damage, HP, economy, and events are resolved by the shared atomic service.",
        "以 server RNG 完成待處理 Attack RollRequest；命中、爆擊、傷害、HP、economy 與 event 全由共用原子 service 解決。",
    ),
    "combat_apply_damage": (
        "Apply manual semantic Combat damage. Never emulate damage by absolute HP editing; Temp HP, affinities, and zero-HP consequences stay server-authoritative.",
        "套用語意化 Combat 傷害。不可用 absolute HP 編輯模擬傷害；Temp HP、抗性與 0 HP 後果由 Server authoritative 處理。",
    ),
    "combat_apply_healing": (
        "Apply manual semantic Combat healing through the same authoritative HP pipeline.",
        "透過同一 authoritative HP pipeline 套用語意化 Combat 治療。",
    ),
    "combat_request_saving_throws": (
        "Current DM creates one or more formal Combat Saving Throw requests with the canonical ability/DC/visibility rules.",
        "目前 DM 建立一個或多個正式 Combat Saving Throw，使用 canonical ability/DC/visibility 規則。",
    ),
    "combat_roll_saving_throw": (
        "Resolve one pending Combat Saving Throw RollRequest with server RNG.",
        "以 server RNG 完成一個待處理的 Combat Saving Throw RollRequest。",
    ),
    "combat_request_death_save": (
        "Create the formal Death Save RollRequest for the legal current-turn Character at 0 HP.",
        "為目前合法輪次且 HP=0 的 Character 建立正式 Death Save RollRequest。",
    ),
    "combat_roll_death_save": (
        "Resolve a pending Death Save with server RNG; counters, Nat 1/Nat 20, stable/dead, HP, and events commit atomically.",
        "以 server RNG 完成待處理 Death Save；次數、Nat 1/Nat 20、stable/dead、HP 與 event 原子提交。",
    ),
    "combat_request_special_attack": (
        "Declare a 2014 Grapple or Shove. Size/free-hand rules are validated first and reach becomes durable DM adjudication.",
        "宣告 2014 Grapple 或 Shove。先驗證 size/free-hand，再把 reach 建成 durable DM adjudication。",
    ),
    "combat_adjudicate_special_attack": (
        "Current DM resolves pending Grapple/Shove reach. Legal reach consumes one Attack budget and creates canonical opposed checks.",
        "目前 DM 裁定 Grapple/Shove reach。合法 reach 才消耗一個 Attack 次數並建立 canonical opposed checks。",
    ),
    "combat_roll_special_attack": (
        "Resolve one pending Grapple/Shove opposed RollRequest with server RNG; the second completed roll atomically applies Grappled/Prone or records the push result.",
        "以 server RNG 完成一個 Grapple/Shove opposed RollRequest；第二個擲骰完成時原子套用 Grappled/Prone 或記錄 push 結果。",
    ),
    "combat_start": (
        "Current DM initiates Quick Combat; active Session party characters are included by default unless overridden.",
        "目前 DM 啟動 Quick Combat 時使用；預設納入目前 Session 隊伍角色。",
    ),
    "combat_add_character": (
        "Current DM adds a late-joining or newly entered Session character to active Combat.",
        "目前 DM 將新進場或中途加入 Session 的角色加入目前 Combat 時使用。",
    ),
    "combat_add_monster": (
        "Current DM places an existing Monster Instance into active Combat as an enemy combatant.",
        "目前 DM 將既有的 Monster Instance 作為敵方單位加入目前 Combat 時使用。",
    ),
    "combat_create_monster": (
        "Current DM instantiates an authoritative SRD monster template for the Campaign before or during encounter play.",
        "目前 DM 在遭遇開始前或戰鬥中從權威 SRD 模板建立怪物實例時使用。",
    ),
    "combat_create_quick_enemy": (
        "Current DM quickly defines an ad-hoc enemy with custom stats without using a formal rulebook template.",
        "目前 DM 需要臨時建立自訂數值的敵方怪物、不使用正式規則模板時使用。",
    ),
    "combat_list_monster_instances": (
        "Current DM inspects all created Monster Instances in the current Campaign including hidden stats and resources.",
        "目前 DM 檢視目前 Campaign 內所有已建立的怪物實例，包含完整隱藏數值與資源。",
    ),
    "combat_request_initiative": (
        "Current DM opens initiative roll requests for PCs and rolls grouped monster initiative.",
        "目前 DM 為玩家角色建立先攻擲骰請求，並依分組計算怪物先攻時使用。",
    ),
    "combat_finalize_initiative": (
        "Current DM locks in the resolved initiative sequence and advances Combat from initiative_pending to Round 1.",
        "目前 DM 確認已完成的先攻順序，並將 Combat 從先攻等待狀態推進到第一輪時使用。",
    ),
    "combat_advance_turn": (
        "Current DM advances the active turn order, refreshing economy and incrementing rounds when cycling.",
        "目前 DM 推進戰鬥輪次，刷新行動經濟並在輪替時推進回合數。",
    ),
    "combat_end": (
        "Current DM formally concludes active Combat, clearing initiative and transient economy while preserving HP and conditions.",
        "目前 DM 正式結束目前戰鬥，清除先攻與暫時行動經濟，並保留 HP 與狀態效果。",
    ),
    "combat_remove_entry": (
        "Current DM removes an entry permanently from turn order due to death, defeat, or departure.",
        "目前 DM 因陣亡、擊潰或離場而將特定單位自先攻輪次中移除時使用。",
    ),
    "combat_roll_initiative": (
        "Resolve a pending character initiative roll request using server RNG and record the total.",
        "以 server RNG 完成待處理的角色先攻擲骰請求並記錄點數。",
    ),
    "combat_use_action": (
        "Combatant spends action economy on standard actions like Dash, Disengage, Dodge, Search, Ready, or Freeform.",
        "戰鬥單位消耗行動經濟以執行 Dash、Disengage、Dodge、Search、Ready 或 Freeform 等標準行動。",
    ),
    "combat_withdraw_entry": (
        "Current DM marks a combatant as withdrawn (fled or retreated) while keeping its entry for the record; a Player narrates the retreat and asks the DM.",
        "目前 DM 將戰鬥單位標記為退出（逃離或撤退）並保留其紀錄；Player 以敘事表達撤退並請 DM 處理。",
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
            variants.extend(item for item in value.get("anyOf", []) if isinstance(item, dict))
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
                details.append("enum=" + "|".join(str(value) for value in enum_values))
            minimum = next((variant["minimum"] for variant in variants if "minimum" in variant), None)
            maximum = next((variant["maximum"] for variant in variants if "maximum" in variant), None)
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
        _desc("Read the current scoped table context and visible recent state.", "讀取目前 scoped 桌面情境與可見的近期狀態。"),
        _NoArguments,
        frozenset({"player", "dm"}),
        pre_session=True,
    ),
    MCPToolDefinition(
        "start_session",
        _desc("Start the Session using a valid unbound pre-session AI DM grant.", "使用有效且尚未綁定 Session 的 AI DM grant 開始 Session。"),
        _NoArguments,
        frozenset({"dm"}),
        pre_session=True,
    ),
    MCPToolDefinition(
        "get_character_context",
        _desc("Read the AI Player's own active Character context.", "讀取 AI Player 自己目前使用中的角色資料。"),
        _NoArguments,
        frozenset({"player"}),
    ),
    MCPToolDefinition("post_dialogue", _desc("Post Character dialogue.", "送出角色對話。"), TextActionInput, frozenset({"player", "dm"})),
    MCPToolDefinition("post_action", _desc("Post an Exploration action.", "送出探索行動。"), TextActionInput, frozenset({"player", "dm"})),
    MCPToolDefinition("post_ooc", _desc("Post an out-of-character message.", "送出場外 OOC 訊息。"), TextActionInput, frozenset({"player", "dm"})),
    MCPToolDefinition("whisper_dm", _desc("Send a private whisper to the current DM.", "傳送只有自己與目前 DM 可見的密語。"), TextActionInput, frozenset({"player"})),
    MCPToolDefinition("post_narration", _desc("Post DM narration.", "送出 DM 敘事。"), TextActionInput, frozenset({"dm"})),
    MCPToolDefinition("set_stage_text", _desc("Replace Main Stage text while retaining its current image.", "更新 Main Stage 文字並保留目前圖片。"), StageTextInput, frozenset({"dm"})),
    MCPToolDefinition("request_check", _desc("Create one formal Check request group.", "建立一組正式 Check 請求。"), RequestCheckToolInput, frozenset({"dm"})),
    MCPToolDefinition("roll_pending", _desc("Complete a visible pending non-combat formal roll with server RNG.", "用 Server RNG 完成可見且待處理的非戰鬥正式擲骰。"), RollPendingInput, frozenset({"player", "dm"})),
    MCPToolDefinition("submit_physical_roll", _desc("Submit raw physical d20 values for a pending non-combat formal roll.", "提交實體骰的 raw d20 點數來完成非戰鬥正式擲骰。"), PhysicalRollInput, frozenset({"player", "dm"})),
    MCPToolDefinition("quick_roll", _desc("Roll convenience dice for the AI Player's controlled Seat.", "替 AI Player 自己控制的 Seat 擲便利骰。"), QuickRollToolInput, frozenset({"player"})),
    MCPToolDefinition("update_character_state", _desc("Apply a legal Current State patch; active-Combat HP uses semantic Combat tools.", "套用合法 Current State 變更；Active Combat HP 使用語意化 Combat 工具。"), CharacterStateToolInput, frozenset({"player", "dm"})),
    MCPToolDefinition("get_pending_events", _desc("Read visible durable table events after a cursor.", "讀取指定 cursor 之後可見的 durable 桌面事件。"), EventsInput, frozenset({"player", "dm"})),
    MCPToolDefinition("wait_for_event", _desc("Wait asynchronously for visible events after a cursor.", "以非同步方式等待指定 cursor 之後的可見事件。"), WaitEventsInput, frozenset({"player", "dm"})),
    MCPToolDefinition("combat_get_active", _desc("Read the active Quick Combat projection.", "讀取目前 Quick Combat 投影。"), _NoArguments, frozenset({"player", "dm"})),
    MCPToolDefinition("combat_list_attacks", _desc("List legal runtime attacks for one controlled CombatEntry.", "列出一個受控制 CombatEntry 的合法 runtime attacks。"), CombatEntryToolInput, frozenset({"player", "dm"})),
    MCPToolDefinition("combat_request_attack", _desc("Declare a formal P4-C Attack.", "宣告正式 P4-C Attack。"), AttackRequestInput, frozenset({"player", "dm"})),
    MCPToolDefinition("combat_adjudicate_attack", _desc("Resolve pending Attack range adjudication.", "裁定待處理 Attack range。"), AttackAdjudicationInput, frozenset({"dm"})),
    MCPToolDefinition("combat_roll_attack", _desc("Resolve a pending Attack RollRequest with server RNG.", "以 Server RNG 完成待處理 Attack RollRequest。"), CombatRollToolInput, frozenset({"player", "dm"})),
    MCPToolDefinition("combat_apply_damage", _desc("Apply semantic Combat damage.", "套用語意化 Combat 傷害。"), SemanticDamageInput, frozenset({"player", "dm"})),
    MCPToolDefinition("combat_apply_healing", _desc("Apply semantic Combat healing.", "套用語意化 Combat 治療。"), SemanticHealingInput, frozenset({"player", "dm"})),
    MCPToolDefinition("combat_request_saving_throws", _desc("Create formal Combat Saving Throw requests.", "建立正式 Combat Saving Throw 請求。"), SavingThrowInput, frozenset({"dm"})),
    MCPToolDefinition("combat_roll_saving_throw", _desc("Resolve a pending Combat Saving Throw with server RNG.", "以 Server RNG 完成待處理 Combat Saving Throw。"), CombatRollToolInput, frozenset({"player", "dm"})),
    MCPToolDefinition("combat_request_death_save", _desc("Create a formal Death Save request.", "建立正式 Death Save 請求。"), DeathSaveRequestInput, frozenset({"player", "dm"})),
    MCPToolDefinition("combat_roll_death_save", _desc("Resolve a pending Death Save with server RNG.", "以 Server RNG 完成待處理 Death Save。"), CombatRollToolInput, frozenset({"player", "dm"})),
    MCPToolDefinition("combat_request_special_attack", _desc("Declare a formal 2014 Grapple or Shove.", "宣告正式 2014 Grapple 或 Shove。"), SpecialAttackRequestInput, frozenset({"player", "dm"})),
    MCPToolDefinition("combat_adjudicate_special_attack", _desc("Resolve pending Grapple/Shove reach adjudication.", "裁定待處理 Grapple/Shove reach。"), SpecialAttackAdjudicationInput, frozenset({"dm"})),
    MCPToolDefinition("combat_roll_special_attack", _desc("Resolve a pending Grapple/Shove opposed roll with server RNG.", "以 Server RNG 完成待處理 Grapple/Shove opposed roll。"), CombatRollToolInput, frozenset({"player", "dm"})),
    MCPToolDefinition("combat_start", _desc("Start Quick Combat for the current Campaign.", "為目前 Campaign 啟動 Quick Combat。"), StartCombatInput, frozenset({"dm"})),
    MCPToolDefinition("combat_add_character", _desc("Add an active Session character to running Combat.", "將目前 Session 的角色加入進行中的 Combat。"), AddCharacterInput, frozenset({"dm"})),
    MCPToolDefinition("combat_add_monster", _desc("Add a Campaign monster instance into active Combat.", "將 Campaign 內的怪物實例加入目前 Combat。"), AddMonsterInput, frozenset({"dm"})),
    MCPToolDefinition("combat_create_monster", _desc("Create a Monster Instance from SRD rules content.", "從 SRD 規則內容建立 Monster Instance。"), CreateMonsterFromContentInput, frozenset({"dm"})),
    MCPToolDefinition("combat_create_quick_enemy", _desc("Create an ad-hoc Quick Enemy monster instance.", "建立臨時的 Quick Enemy 怪物實例。"), CreateQuickEnemyInput, frozenset({"dm"})),
    MCPToolDefinition("combat_list_monster_instances", _desc("List all Campaign Monster Instances with full DM stats.", "列出 Campaign 內所有怪物實例的完整 DM 資訊。"), _NoArguments, frozenset({"dm"})),
    MCPToolDefinition("combat_request_initiative", _desc("Request initiative rolls for active combatants.", "為活躍戰鬥單位發起先攻擲骰請求。"), RequestInitiativeInput, frozenset({"dm"})),
    MCPToolDefinition("combat_finalize_initiative", _desc("Finalize initiative turn order to begin Round 1.", "確認先攻順序以開始第一回合。"), FinalizeInitiativeInput, frozenset({"dm"})),
    MCPToolDefinition("combat_advance_turn", _desc("Advance Combat to the next turn or round.", "將 Combat 推進至下一個輪次或回合。"), CombatMutationToolInput, frozenset({"dm"})),
    MCPToolDefinition("combat_end", _desc("End the active Combat and clean up transient state.", "結束目前 Combat 並清除戰鬥暫態。"), CombatMutationToolInput, frozenset({"dm"})),
    MCPToolDefinition("combat_remove_entry", _desc("Remove a combatant entry completely from Combat.", "將戰鬥單位完全自 Combat 中移除。"), CombatEntryMutationToolInput, frozenset({"dm"})),
    MCPToolDefinition("combat_roll_initiative", _desc("Resolve a pending initiative RollRequest with server RNG.", "以 Server RNG 完成待處理的先攻 RollRequest。"), CombatRollToolInput, frozenset({"player", "dm"})),
    MCPToolDefinition("combat_use_action", _desc("Perform a non-attack combat action such as Dash or Dodge.", "執行 Dash 或 Dodge 等非攻擊型戰鬥行動。"), CombatActionInput, frozenset({"player", "dm"})),
    MCPToolDefinition("combat_withdraw_entry", _desc("Withdraw a combatant entry from active combat.", "將戰鬥單位標記為退出戰鬥。"), CombatEntryMutationToolInput, frozenset({"dm"})),
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
    return [definition.wire() for definition in _TOOL_DEFINITIONS if auth.role in definition.roles]


def _definition(name: str) -> MCPToolDefinition | None:
    return next((item for item in _TOOL_DEFINITIONS if item.name == name), None)


def _structured_result(data: dict[str, Any]) -> dict[str, Any]:
    structured = {"ok": True, "data": data}
    return {
        "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False, separators=(",", ":"))}],
        "structuredContent": structured,
        "isError": False,
    }


def structured_tool_error(code: str, message: str, message_zh_tw: str) -> dict[str, Any]:
    structured = {
        "ok": False,
        "error": {"code": code, "messages": {"en": message, "zh-TW": message_zh_tw}},
    }
    return {
        "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False, separators=(",", ":"))}],
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
        return structured_tool_error("tool_not_found", "Tool is not exposed by Adventure Table", "Adventure Table 未提供此工具")
    if auth.role not in definition.roles:
        return structured_tool_error("permission_denied", "Current AI Seat role cannot use this tool", "目前 AI Seat role 不可使用此工具")
    if auth.session_id is None and not definition.pre_session:
        return structured_tool_error("active_session_required", "This tool requires an active Session binding", "此工具需要已綁定的 active Session")
    if auth.session_id is not None and definition.name == "start_session":
        return structured_tool_error("pre_session_only", "Start is only available before Session binding", "Start 只可在 Session 綁定前使用")
    if not isinstance(arguments, dict):
        return structured_tool_error("invalid_arguments", "Tool arguments must be an object", "工具 arguments 必須是 object")

    try:
        parsed = definition.input_model.model_validate(arguments)

        if name == "get_session_context":
            data = await asyncio.to_thread(service.get_session_context, token, authenticated=auth)
        elif name == "start_session":
            data = await asyncio.to_thread(service.start_session, token, authenticated=auth)
        elif name == "get_character_context":
            data = await asyncio.to_thread(service.get_character_context, token, authenticated=auth)
        elif name == "post_dialogue":
            data = await asyncio.to_thread(service.post_text, token, kind=ExplorationInputKind.DIALOGUE, input=parsed, authenticated=auth)
        elif name == "post_action":
            data = await asyncio.to_thread(service.post_text, token, kind=ExplorationInputKind.ACTION, input=parsed, authenticated=auth)
        elif name == "post_ooc":
            data = await asyncio.to_thread(service.post_text, token, kind=ExplorationInputKind.OOC, input=parsed, authenticated=auth)
        elif name == "whisper_dm":
            data = await asyncio.to_thread(service.post_text, token, kind=ExplorationInputKind.WHISPER_DM, input=parsed, authenticated=auth)
        elif name == "post_narration":
            data = await asyncio.to_thread(service.post_text, token, kind=ExplorationInputKind.NARRATION, input=parsed, authenticated=auth)
        elif name == "set_stage_text":
            data = await asyncio.to_thread(service.set_stage_text, token, parsed, authenticated=auth)
        elif name == "request_check":
            data = await asyncio.to_thread(service.request_check, token, parsed, authenticated=auth)
        elif name == "roll_pending":
            data = await asyncio.to_thread(service.roll_pending, token, parsed, authenticated=auth)
        elif name == "submit_physical_roll":
            data = await asyncio.to_thread(service.submit_physical_roll, token, parsed, authenticated=auth)
        elif name == "quick_roll":
            data = await asyncio.to_thread(service.quick_roll, token, parsed, authenticated=auth)
        elif name == "update_character_state":
            data = await asyncio.to_thread(service.update_character_state, token, parsed, authenticated=auth)
        elif name == "get_pending_events":
            data = await asyncio.to_thread(service.get_pending_events, token, parsed, authenticated=auth)
        elif name == "wait_for_event":
            data = await service.wait_for_event(token, parsed, authenticated=auth)
        elif name == "combat_get_active":
            data = await asyncio.to_thread(service.combat_get_active, token, authenticated=auth)
        elif name == "combat_list_attacks":
            data = await asyncio.to_thread(service.combat_list_attacks, token, parsed, authenticated=auth)
        elif name == "combat_request_attack":
            data = await asyncio.to_thread(service.combat_request_attack, token, parsed, authenticated=auth)
        elif name == "combat_adjudicate_attack":
            data = await asyncio.to_thread(service.combat_adjudicate_attack, token, parsed, authenticated=auth)
        elif name == "combat_roll_attack":
            data = await asyncio.to_thread(service.combat_roll_attack, token, parsed, authenticated=auth)
        elif name == "combat_apply_damage":
            data = await asyncio.to_thread(service.combat_apply_damage, token, parsed, authenticated=auth)
        elif name == "combat_apply_healing":
            data = await asyncio.to_thread(service.combat_apply_healing, token, parsed, authenticated=auth)
        elif name == "combat_request_saving_throws":
            data = await asyncio.to_thread(service.combat_request_saving_throws, token, parsed, authenticated=auth)
        elif name == "combat_roll_saving_throw":
            data = await asyncio.to_thread(service.combat_roll_saving_throw, token, parsed, authenticated=auth)
        elif name == "combat_request_death_save":
            data = await asyncio.to_thread(service.combat_request_death_save, token, parsed, authenticated=auth)
        elif name == "combat_roll_death_save":
            data = await asyncio.to_thread(service.combat_roll_death_save, token, parsed, authenticated=auth)
        elif name == "combat_request_special_attack":
            data = await asyncio.to_thread(service.combat_request_special_attack, token, parsed, authenticated=auth)
        elif name == "combat_adjudicate_special_attack":
            data = await asyncio.to_thread(service.combat_adjudicate_special_attack, token, parsed, authenticated=auth)
        elif name == "combat_roll_special_attack":
            data = await asyncio.to_thread(service.combat_roll_special_attack, token, parsed, authenticated=auth)
        elif name == "combat_start":
            data = await asyncio.to_thread(service.combat_start, token, parsed, authenticated=auth)
        elif name == "combat_add_character":
            data = await asyncio.to_thread(service.combat_add_character, token, parsed, authenticated=auth)
        elif name == "combat_add_monster":
            data = await asyncio.to_thread(service.combat_add_monster, token, parsed, authenticated=auth)
        elif name == "combat_create_monster":
            data = await asyncio.to_thread(service.combat_create_monster, token, parsed, authenticated=auth)
        elif name == "combat_create_quick_enemy":
            data = await asyncio.to_thread(service.combat_create_quick_enemy, token, parsed, authenticated=auth)
        elif name == "combat_list_monster_instances":
            data = await asyncio.to_thread(service.combat_list_monster_instances, token, authenticated=auth)
        elif name == "combat_request_initiative":
            data = await asyncio.to_thread(service.combat_request_initiative, token, parsed, authenticated=auth)
        elif name == "combat_roll_initiative":
            data = await asyncio.to_thread(service.combat_roll_initiative, token, parsed, authenticated=auth)
        elif name == "combat_finalize_initiative":
            data = await asyncio.to_thread(service.combat_finalize_initiative, token, parsed, authenticated=auth)
        elif name == "combat_advance_turn":
            data = await asyncio.to_thread(service.combat_advance_turn, token, parsed, authenticated=auth)
        elif name == "combat_use_action":
            data = await asyncio.to_thread(service.combat_use_action, token, parsed, authenticated=auth)
        elif name == "combat_withdraw_entry":
            data = await asyncio.to_thread(service.combat_withdraw_entry, token, parsed, authenticated=auth)
        elif name == "combat_remove_entry":
            data = await asyncio.to_thread(service.combat_remove_entry, token, parsed, authenticated=auth)
        elif name == "combat_end":
            data = await asyncio.to_thread(service.combat_end, token, parsed, authenticated=auth)
        else:  # pragma: no cover
            return structured_tool_error("tool_not_implemented", "Tool dispatch is not implemented", "工具 dispatch 尚未實作")
    except ValidationError:
        return structured_tool_error("invalid_arguments", "Tool arguments failed schema validation", "工具 arguments 未通過 schema 驗證")
    except PermissionError:
        return structured_tool_error("permission_denied", "Current AI controller is not permitted to perform this action", "目前 AI controller 無權執行此動作")
    except LookupError:
        return structured_tool_error("not_found", "Requested table object was not found in the current scope", "目前 scope 找不到指定的桌面物件")
    except CheckReferenceInvalidError as exc:
        return structured_tool_error(
            "unknown_check_ref",
            f"Unknown skill/ability reference: {exc}. Use a skill index like 'investigation' or an ability like 'dexterity'.",
            f"無法解析的技能／屬性參照：{exc}。技能用如 'investigation' 的名稱，屬性用如 'dexterity'。",
        )
    except ValueError:
        return structured_tool_error("invalid_arguments", "Tool arguments are not valid for the current table state", "工具 arguments 不符合目前桌面狀態")
    except RuntimeError:
        return structured_tool_error("table_conflict", "The table state changed or does not allow this action", "桌面狀態已變更或目前不允許此動作")

    return _structured_result(data)


__all__ = [
    "MCPToolDefinition",
    "call_tool",
    "structured_tool_error",
    "tool_catalog",
    "tool_reference_rows",
]
