from __future__ import annotations

from app.domain.rooms.ai_tool_contract import (
    WAIT_EVENT_EMPTY_RETRY_COUNT,
    WAIT_EVENT_MAX_TIMEOUT_SECONDS,
)

WAIT_RETRY_COUNT = WAIT_EVENT_EMPTY_RETRY_COUNT
WAIT_TIMEOUT_SECONDS = int(WAIT_EVENT_MAX_TIMEOUT_SECONDS)


def role_rule(*, role: str, locale: str) -> str:
    if role == "dm":
        if locale == "zh-TW":
            return (
                "DM 回應玩家時一律用 post_narration 寫回桌上，不要只在承載 AI 的對話視窗回覆。"
                "一般敘事以約 100–250 字為目標；秘密資訊不要寫入 Main Stage 或公開 narration。需要暗骰時使用 visibility=dm_only。"
                "角色 HP、狀態等變更一律使用對應工具寫回桌上。所有可帶 idempotency_key 的寫入都要提供唯一值；"
                "替 Player 角色說話或行動時必須帶 subject_seat_id。正式檢定用 request_check 建立；成功後桌上會自動顯示擲骰提示，不要只為同一次要求另發 post_narration。skill_ref 用技能名如 investigation、ability_ref 用屬性如 dexterity。"
            )
        return (
            "As DM, write player-facing responses back to the table with post_narration instead of replying only in the host chat. "
            "Aim for roughly 100–250 words for ordinary narration. Never put secrets on Main Stage or in public narration; use visibility=dm_only for secret rolls. "
            "Write HP/condition/state changes back through the appropriate tools. Provide a unique idempotency_key on every write that supports it, "
            "and provide subject_seat_id when speaking or acting for a Player Seat. Create formal checks with request_check; success automatically posts the roll prompt to table chat, so do not call post_narration merely to ask for the same roll (skill_ref takes a skill name like investigation, ability_ref an ability like dexterity)."
        )
    if role == "player":
        if locale == "zh-TW":
            return (
                "Player 用 post_dialogue 說話、post_action 描述行動意圖；需要正式檢定時先描述意圖，等 DM 建立 Check，再用 roll_pending 或 submit_physical_roll。"
                "quick_roll 只是便利骰，不會取代正式 Check。需要更新 HP、狀態等 Current State 時用 update_character_state；私下告知 DM 用 whisper_dm。"
                "所有可帶 idempotency_key 的寫入都要提供唯一值。"
            )
        return (
            "As Player, use post_dialogue for speech and post_action for intended actions. For a formal check, describe the attempt, wait for the DM to create the Check, "
            "then use roll_pending or submit_physical_roll. quick_roll is convenience dice only and does not replace a formal Check. "
            "Use update_character_state for legal Current State changes such as HP or conditions, and whisper_dm for private messages to the DM. "
            "Provide a unique idempotency_key on every write that supports it."
        )
    raise ValueError("unsupported role")


def wait_rule(locale: str) -> str:
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


# The active-session briefing is a mandatory step-by-step loop rather than a
# description, so an AI runs the core table loop correctly without first reading
# GET /mcp/guide. It is guidance only: the server never enforces it (for example
# narration works even when the Stage is unset — Optional stays optional).
BRIEFING_MAX_CHARS = 3_000

# Connectors expose tool discovery separately from tool execution; a model can
# mistake "I can see / rescanned the tools" for "I called the tool". This rule
# makes an actual invocation the only evidence of connectivity.
_INVOCATION_RULE_EN = (
    "MCP invocation rule: only an actual tool call this turn (a real AT_mcp.<tool> "
    "invocation that returned a success or error) counts as calling MCP. Tool "
    "discovery, reading schemas, rescanning the connector or listing tools do NOT "
    "count. Never report MCP connection success or failure unless such an "
    "invocation occurred this turn; with none, say it is untested, do not guess "
    "connection failed."
)
_INVOCATION_RULE_ZH = (
    "MCP 呼叫判定：只有本回合實際執行 AT_mcp.<tool> 並取得成功或錯誤結果才算呼叫 MCP；"
    "查看工具清單、讀 schema、重新掃描 connector 都不算。沒有實際 invocation 前，不得宣稱連線成功或失敗，"
    "只能說『尚未測試』，不可推測為 connection failed。"
)


# Pre-session context carries no Campaign summary, so the DM is told up front
# where the attached Adventure's table of contents appears once play starts.
_PRE_SESSION_ADVENTURE_EN = (
    "After start, get_campaign_context lists attached Adventures with their outline "
    "(entry ids/titles); read entries with get_adventure_entry and set the opening scene "
    "with world_set_current_context. Narrate, set the Stage and write back in the players' language. "
)
_PRE_SESSION_ADVENTURE_ZH = (
    "開始後 get_campaign_context 會列出附加 Adventure 與其目錄（條目 id／標題）；"
    "用 get_adventure_entry 讀條目，並以 world_set_current_context 設定開場 scene。敘事、Stage 與寫回一律用玩家使用的語言。"
)


# An Adventure is a baseline, not a script (規格企劃 〇.7): when it offers no
# path — e.g. a reveal condition with no matching encounter — the DM improvises
# and persists what matters instead of stalling the table.
def _dm_loop(locale: str) -> str:
    if locale == "zh-TW":
        return (
            "DM 必跑流程（每步都做，不得停在 host chat）："
            "1) campaign_context.attached_adventure_count>0 時：用 get_campaign_context 讀 attached_adventures[].outline（Adventure 目錄），"
            "以 get_adventure_entry 讀需要的條目；current_scene.kind 為 none 時用 world_set_current_context 設定目前 scene。"
            "Adventure 是底稿不是劇本：它沒給路徑時（例如有條件卻沒有對應遭遇）要像真人 DM 即興（新 NPC 用 world_create_entry、敵人用 Quick Combat）。"
            "2) stage_unset 為真時先 set_stage_text。"
            "3) 用 post_narration 敘事（約 100–250 字；秘密不進 Stage／公開 narration，暗骰 visibility=dm_only）。"
            f"4) 立即呼叫 wait_for_event（timeout 最多 {WAIT_TIMEOUT_SECONDS} 秒）。"
            "5) 處理 Player 的 dialogue／action；檢定用 request_check，它會自動顯示擲骰提示，不必另發 post_narration。"
            "6) 場景變化時更新 set_stage_text；世界狀態改變（門開、NPC 死亡、重要的即興內容）用 world_set_override（Adventure 條目現況）"
            "或 world_create_entry（新 fact／npc／item）寫回，下一場才會延續。"
            "7) 每處理完一個事件再 wait_for_event。"
            f"8) 只有連續 {WAIT_RETRY_COUNT} 次無事件（約 10 分鐘）、Session 結束或 host 喊停才停止。"
            "敘事、Stage 與寫回一律用玩家使用的語言。寫入帶 idempotency_key，代理 Player 帶 subject_seat_id。"
        )
    return (
        "MANDATORY DM LOOP (do every step; never stop in host chat): "
        "1) If campaign_context.attached_adventure_count>0, read attached_adventures[].outline via get_campaign_context "
        "and open entries with get_adventure_entry; if current_scene.kind is none, set it with world_set_current_context. "
        "The Adventure is a baseline, not a script: where it gives no path (e.g. a condition with no encounter), improvise like a human DM "
        "(new NPC via world_create_entry, enemies via Quick Combat). "
        "2) When stage_unset is true call set_stage_text first. "
        "3) Narrate with post_narration (~100-250 words; secrets never on Stage/public narration; hidden rolls visibility=dm_only). "
        f"4) Immediately call wait_for_event (timeout up to {WAIT_TIMEOUT_SECONDS}s). "
        "5) Resolve each Player dialogue/action; for a check use request_check, which automatically posts the roll prompt (no extra post_narration). "
        "6) Update set_stage_text when the scene changes; when the world changes (door opened, NPC died, key improvisation) write it back with "
        "world_set_override (Adventure entry state) or world_create_entry (new fact/npc/item) so it persists. "
        "7) Call wait_for_event again after each event. "
        f"8) Stop only after {WAIT_RETRY_COUNT} consecutive empty waits (~10 min), Session end, or host stop. "
        "Narrate, set the Stage and write back in the players' language. idempotency_key on every write; subject_seat_id when acting for a Player."
    )


def _player_loop(locale: str) -> str:
    if locale == "zh-TW":
        return (
            "Player 必跑流程（無需先讀 guide；每步都做，不得停在 host chat 等提示）："
            "1) 用 post_dialogue 說話、用 post_action 描述行動意圖。"
            "2) 需要正式檢定時先用 post_action 描述嘗試，等 DM 建立 Check，再用 roll_pending 或 submit_physical_roll 完成（quick_roll 只是便利骰，不取代正式 Check）。"
            "3) HP／狀態變更用 update_character_state；要私下告知 DM 用 whisper_dm。"
            f"4) 行動後立即呼叫 wait_for_event（timeout 最多 {WAIT_TIMEOUT_SECONDS} 秒）——不要停、不要回 host chat 等人再提示。"
            "5) 收到新事件即處理，再次 wait_for_event，持續循環。"
            f"6) 只有連續 {WAIT_RETRY_COUNT} 次無事件（約 10 分鐘）、Session 結束或 host 明確喊停才停止。"
            "所有寫入帶 idempotency_key。"
        )
    return (
        "MANDATORY PLAYER LOOP (run it without reading the guide; do every step, never stop in host chat waiting for a prompt): "
        "1) Speak in character with post_dialogue and describe intended actions with post_action. "
        "2) For a formal check, describe the attempt with post_action, wait for the DM to create the Check, then complete it with roll_pending or submit_physical_roll (quick_roll is convenience dice only, never a formal check). "
        "3) Change your HP/conditions with update_character_state; message the DM privately with whisper_dm. "
        f"4) After acting, immediately call wait_for_event (timeout up to {WAIT_TIMEOUT_SECONDS}s) — do NOT stop or wait for a human prompt. "
        "5) On a new event handle it, then call wait_for_event again and repeat. "
        f"6) Stop only after {WAIT_RETRY_COUNT} consecutive empty waits (~10 min), Session end, or the host tells you to stop. "
        "Put idempotency_key on every write."
    )


def _dm_combat_loop(locale: str) -> str:
    if locale == "zh-TW":
        return (
            "DM 戰鬥必跑流程（無需先讀 guide；每步都做，不得停在 host chat 等提示）："
            "1) 讀取 get_session_context.combat（或 get_combat_context）：檢視 round、current_turn_entry_id（當前回合）、"
            "my_entry_ids、pending_roll_requests、reaction_windows（反應窗口）、pending_adjudications（待處理裁定）並依 next_required_action 行動。"
            "2) 遇待處理裁定依 next_required_action 選工具：Attack 距離用 combat_adjudicate_attack（in_range）、"
            "reach 用 combat_adjudicate_special_attack、AoE 用 combat_resolve_aoe_spell、借機攻擊／自由規則用 combat_resolve_adjudication。"
            "3) 輪到 Monster 回合以 combat_* 工具（攻擊、施法、主要動作）解決行動後呼叫 combat_advance_turn 推進回合；"
            "next_required_action=advance_turn（Player action 用完、無待處理）時也由你推進。"
            "環境傷害用 quick_roll 擲骰再 combat_apply_damage，不要自訂數字。"
            "4) 用 post_narration 簡短敘述戰況（機械結果由系統記錄；嚴禁改 HP 偽造攻擊；只說傷勢，不說敵人精確 HP）。"
            f"5) 每次解決後立即呼叫 wait_for_event（timeout 最多 {WAIT_TIMEOUT_SECONDS} 秒）——不要停在 host chat。"
            "6) 處理完事件後再次呼叫 wait_for_event 持續循環。"
            f"7) 僅連續 {WAIT_RETRY_COUNT} 次無事件（約 10 分鐘）、戰鬥或 Session 結束才停止。"
            "寫入帶 idempotency_key，代 Player 行動帶 subject_seat_id。"
        )
    return (
        "MANDATORY DM COMBAT LOOP (no need to read the guide; do every step, never stop in host chat): "
        "1) Read get_session_context.combat (or get_combat_context): check round, current_turn_entry_id (current turn), "
        "my_entry_ids, pending_roll_requests, reaction_windows (reaction window), pending_adjudications, and follow next_required_action. "
        "2) On pending adjudication use the tool next_required_action names: range -> combat_adjudicate_attack (in_range), "
        "reach -> combat_adjudicate_special_attack, AoE -> combat_resolve_aoe_spell, OA/freeform -> combat_resolve_adjudication. "
        "3) On a Monster turn resolve actions with combat_* tools (attack/cast/use) then combat_advance_turn; "
        "also call combat_advance_turn when next_required_action=advance_turn (Player action spent, nothing pending). "
        "Environmental damage: quick_roll, then combat_apply_damage; never invent the number. "
        "4) Narrate briefly with post_narration (mechanical results are logged; never patch enemy HP to fake attacks; "
        "narrate injury level, never exact enemy HP). "
        f"5) After handling any action call wait_for_event (timeout up to {WAIT_TIMEOUT_SECONDS}s) — never stop in host chat. "
        "6) After resolving an event call wait_for_event again and repeat. "
        f"7) Stop only after {WAIT_RETRY_COUNT} consecutive empty waits (~10 min), combat end, Session end, or host stop. "
        "Writes take idempotency_key; acting for Player takes subject_seat_id."
    )


def _player_combat_loop(locale: str) -> str:
    if locale == "zh-TW":
        return (
            "Player 戰鬥必跑流程（無需先讀 guide；每步都做，不得停在 host chat 等提示）："
            "1) 讀取 get_session_context.combat（或 get_combat_context）：檢視 round、current_turn_entry_id（當前回合）、"
            "my_entry_ids、pending_roll_requests、reaction_windows（反應窗口）、pending_adjudications 與 next_required_action。"
            "2) 僅在自己當前回合（current_turn_entry_id 屬於 my_entry_ids）或開啟的反應窗口（combat_respond_to_reaction）行動；"
            "待擲骰時，攻擊/豁免/先攻用 roll_pending，專注豁免用 combat_roll_concentration；"
            "無法確認距離/掩蔽/OA 時呼叫 combat_request_adjudication 或 combat_request_opportunity_attack 提請裁定並等 DM；否則等待。"
            f"3) 行動後立即呼叫 wait_for_event（timeout 最多 {WAIT_TIMEOUT_SECONDS} 秒）——不要停在 host chat。"
            "4) 收到新事件即處理，再次 wait_for_event 持續循環。"
            f"5) 僅連續 {WAIT_RETRY_COUNT} 次無事件（約 10 分鐘）、戰鬥或 host 喊停才停止。寫入帶 idempotency_key。"
        )
    return (
        "MANDATORY PLAYER COMBAT LOOP (run it without reading the guide; do every step, never stop in host chat): "
        "1) Read get_session_context.combat (or get_combat_context): check round, current_turn_entry_id (current turn), "
        "my_entry_ids, pending_roll_requests, reaction_windows (reaction window), pending_adjudications, and next_required_action. "
        "2) Act ONLY on your own current turn (current_turn_entry_id in my_entry_ids) or in an open reaction window (combat_respond_to_reaction). "
        "Pending rolls: roll_pending for attack/save/initiative, combat_roll_concentration for Concentration save. "
        "If unsure of range/cover/OA, call combat_request_adjudication or combat_request_opportunity_attack to request adjudication and wait for DM; otherwise wait. "
        f"3) After acting call wait_for_event (timeout up to {WAIT_TIMEOUT_SECONDS}s) — never stop in host chat. "
        "4) On new event handle it, call wait_for_event again and repeat. "
        f"5) Stop only after {WAIT_RETRY_COUNT} consecutive empty waits (~10 min), combat end, or host stop. "
        "Writes take idempotency_key."
    )


def _format_active_briefing(en_loop: str, zh_loop: str) -> str:
    return (
        f"EN: {en_loop} {_INVOCATION_RULE_EN} Full guide: GET /mcp/guide?locale=en. "
        "If temporary_instruction is non-empty, follow it as an additional temporary instruction.\n"
        f"zh-TW：{zh_loop} {_INVOCATION_RULE_ZH} 完整指引：GET /mcp/guide?locale=zh-TW。"
        "temporary_instruction 非空時視為額外暫時指示。"
    )


def render_briefing(*, role: str, mode: str) -> str:
    if role not in {"dm", "player"}:
        raise ValueError("unsupported role")
    if mode not in {"pre_session", "active_session", "active_combat"}:
        raise ValueError("unsupported mode")
    if mode == "pre_session":
        briefing = (
            "EN: This token already makes you the controller of this DM Seat — there is NO join step. "
            "Read this context, then call start_session. The tool list is the same before and after start; gameplay tools simply start accepting calls. "
            f"{_PRE_SESSION_ADVENTURE_EN if role == 'dm' else ''}"
            "Right after start the Stage is empty, so your first action is set_stage_text, then post_narration. "
            "Full guide: GET /mcp/guide?locale=en.\n"
            "zh-TW：這個 token 已經讓你成為此 DM Seat 的 controller，沒有另外的入席步驟。先讀 context，再呼叫 start_session；"
            "工具清單開始前後相同，開始後 gameplay 工具即可呼叫。"
            f"{_PRE_SESSION_ADVENTURE_ZH if role == 'dm' else ''}"
            "開場後 Stage 是空的，第一步先 set_stage_text，再 post_narration。"
            "完整指引：GET /mcp/guide?locale=zh-TW。"
        )
    elif mode == "active_combat":
        loop = _dm_combat_loop if role == "dm" else _player_combat_loop
        briefing = _format_active_briefing(loop("en"), loop("zh-TW"))
    else:
        loop = _dm_loop if role == "dm" else _player_loop
        briefing = _format_active_briefing(loop("en"), loop("zh-TW"))
    if len(briefing) > BRIEFING_MAX_CHARS:
        raise RuntimeError(
            f"AI briefing exceeded {BRIEFING_MAX_CHARS}-character contract"
        )
    return briefing


__all__ = [
    "BRIEFING_MAX_CHARS",
    "WAIT_RETRY_COUNT",
    "WAIT_TIMEOUT_SECONDS",
    "render_briefing",
    "role_rule",
    "wait_rule",
]
