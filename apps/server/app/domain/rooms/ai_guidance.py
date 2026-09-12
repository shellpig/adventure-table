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
                "一般敘事以約 100–250 字為目標；秘密資訊不要寫入 Main Stage。需要暗骰時使用 visibility=dm_only。"
                "所有可帶 idempotency_key 的寫入都要提供唯一值；替 Player 角色說話或行動時必須帶 subject_seat_id。"
                "正式檢定用 request_check 建立。"
            )
        return (
            "As DM, write player-facing responses back to the table with post_narration instead of replying only in the host chat. "
            "Aim for roughly 100–250 words for ordinary narration. Never put secret information on Main Stage; use visibility=dm_only for secret rolls. "
            "Provide a unique idempotency_key on every write that supports it, and provide subject_seat_id when speaking or acting for a Player Seat. "
            "Create formal checks with request_check."
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
    return (
        f"EN: {role_rule(role=role, locale='en')} {wait_rule('en')} Full guide: GET /mcp/guide?locale=en. "
        "If temporary_instruction is non-empty, follow it as an additional temporary instruction.\n"
        f"zh-TW：{role_rule(role=role, locale='zh-TW')} {wait_rule('zh-TW')} 完整指引：GET /mcp/guide?locale=zh-TW。"
        "temporary_instruction 若非空，將它視為額外的暫時指示。"
    )


__all__ = ["WAIT_RETRY_COUNT", "WAIT_TIMEOUT_SECONDS", "render_briefing", "role_rule", "wait_rule"]
