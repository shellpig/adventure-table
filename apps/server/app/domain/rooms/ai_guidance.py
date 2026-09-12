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
                "替 Player 角色說話或行動時必須帶 subject_seat_id。正式檢定用 request_check 建立。"
            )
        return (
            "As DM, write player-facing responses back to the table with post_narration instead of replying only in the host chat. "
            "Aim for roughly 100–250 words for ordinary narration. Never put secrets on Main Stage or in public narration; use visibility=dm_only for secret rolls. "
            "Write HP/condition/state changes back through the appropriate tools. Provide a unique idempotency_key on every write that supports it, "
            "and provide subject_seat_id when speaking or acting for a Player Seat. Create formal checks with request_check."
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
BRIEFING_MAX_CHARS = 2_400

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


def _dm_loop(locale: str) -> str:
    if locale == "zh-TW":
        return (
            "DM 必跑流程（無需先讀 guide；每步都做，不得停在 host chat 等提示）："
            "1) 讀 stage；stage_unset 為真（stage.text 空）時先呼叫 set_stage_text 建立目前場景。"
            "2) 用 post_narration 對玩家敘事（約 100–250 字；秘密不進 Stage／公開 narration，暗骰 visibility=dm_only）。"
            f"3) 立即呼叫 wait_for_event（timeout 最多 {WAIT_TIMEOUT_SECONDS} 秒）——不要停、不要回 host chat 等人再提示。"
            "4) 收到 Player 的 dialogue／action 立即處理；需要檢定用 request_check。"
            "5) 場景實質變化時再用 set_stage_text 更新。"
            "6) 處理完事件後再次 wait_for_event，持續循環。"
            f"7) 只有連續 {WAIT_RETRY_COUNT} 次無事件（約 10 分鐘）、Session 結束或 host 明確喊停才停止。"
            "所有寫入帶 idempotency_key，代理 Player 說話／行動帶 subject_seat_id。"
        )
    return (
        "MANDATORY DM LOOP (run it without reading the guide; do every step, never stop in host chat waiting for a prompt): "
        "1) Read stage; when stage_unset is true (stage.text empty) call set_stage_text first to establish the current scene. "
        "2) Narrate to players with post_narration (~100-250 words; keep secrets off the Stage/public narration, use visibility=dm_only for hidden rolls). "
        f"3) Immediately call wait_for_event (timeout up to {WAIT_TIMEOUT_SECONDS}s) — do NOT stop or wait for a human prompt. "
        "4) On a Player dialogue/action resolve it; for a check use request_check. "
        "5) When the scene materially changes, update set_stage_text. "
        "6) After handling an event call wait_for_event again and repeat. "
        f"7) Stop only after {WAIT_RETRY_COUNT} consecutive empty waits (~10 min), Session end, or the host tells you to stop. "
        "Put idempotency_key on every write, and subject_seat_id when speaking/acting for a Player."
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


def render_briefing(*, role: str, mode: str) -> str:
    if role not in {"dm", "player"}:
        raise ValueError("unsupported role")
    if mode not in {"pre_session", "active_session"}:
        raise ValueError("unsupported mode")
    if mode == "pre_session":
        briefing = (
            "EN: This token already makes you the controller of this DM Seat — there is NO join step. "
            "Read this context, then call start_session. The tool list is the same before and after start; gameplay tools simply start accepting calls. "
            "Right after start the Stage is empty, so your first action is set_stage_text, then post_narration. "
            "Full guide: GET /mcp/guide?locale=en.\n"
            "zh-TW：這個 token 已經讓你成為此 DM Seat 的 controller，沒有另外的入席步驟。先讀 context，再呼叫 start_session；"
            "工具清單開始前後相同，開始後 gameplay 工具即可呼叫。開場後 Stage 是空的，第一步先 set_stage_text，再 post_narration。"
            "完整指引：GET /mcp/guide?locale=zh-TW。"
        )
    else:
        loop = _dm_loop if role == "dm" else _player_loop
        briefing = (
            f"EN: {loop('en')} {_INVOCATION_RULE_EN} Full guide: GET /mcp/guide?locale=en. "
            "If temporary_instruction is non-empty, follow it as an additional temporary instruction.\n"
            f"zh-TW：{loop('zh-TW')} {_INVOCATION_RULE_ZH} 完整指引：GET /mcp/guide?locale=zh-TW。"
            "temporary_instruction 非空時視為額外暫時指示。"
        )
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
