from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Literal


class ReactionKind(StrEnum):
    OPPORTUNITY_ATTACK = "opportunity_attack"
    SHIELD = "shield"
    COUNTERSPELL = "counterspell"
    READY = "ready"
    OTHER = "other"


@dataclass(frozen=True)
class ReactionWindow:
    window_id: str
    entry_id: str
    kind: ReactionKind
    reason: str
    source_entry_id: str | None = None
    status: Literal["open", "resolved", "expired"] = "open"


@dataclass(frozen=True)
class ReadyState:
    owner_entry_id: str
    trigger: str
    response: str
    created_turn_key: str
    expires_at_owner_turn_key: str
    spell_ref: str | None = None
    spell_slot_level: int | None = None
    concentration_started: bool = False

    def __post_init__(self) -> None:
        if not self.trigger.strip() or not self.response.strip():
            raise ValueError("Ready requires non-blank trigger and response")
        if self.spell_ref is None and self.spell_slot_level is not None:
            raise ValueError("spell_slot_level requires spell_ref")


@dataclass(frozen=True)
class ReactionResolution:
    reaction_available: bool
    window: ReactionWindow
    events: tuple[dict[str, object], ...]


def open_reaction_window(
    *,
    window_id: str,
    entry_id: str,
    kind: ReactionKind,
    reason: str,
    source_entry_id: str | None = None,
) -> ReactionWindow:
    if not window_id.strip() or not entry_id.strip() or not reason.strip():
        raise ValueError("reaction window id, entry id and reason are required")
    return ReactionWindow(window_id, entry_id, kind, reason, source_entry_id)


def resolve_reaction(
    *,
    window: ReactionWindow,
    actor_entry_id: str,
    reaction_available: bool,
    accept: bool,
) -> ReactionResolution:
    if window.status != "open":
        raise ValueError("reaction window is not open")
    if actor_entry_id != window.entry_id:
        raise PermissionError("reaction window belongs to another combat entry")
    if accept and not reaction_available:
        raise ValueError("reaction is not available")
    resolved = replace(window, status="resolved")
    if not accept:
        return ReactionResolution(
            reaction_available,
            resolved,
            ({"type": "reaction_resolved", "window_id": window.window_id, "accepted": False},),
        )
    return ReactionResolution(
        False,
        resolved,
        (
            {
                "type": "reaction_resolved",
                "window_id": window.window_id,
                "accepted": True,
                "kind": window.kind.value,
            },
        ),
    )


def expire_reaction_window(window: ReactionWindow) -> ReactionResolution:
    if window.status != "open":
        return ReactionResolution(True, window, ())
    expired = replace(window, status="expired")
    return ReactionResolution(
        True,
        expired,
        ({"type": "reaction_expired", "window_id": window.window_id},),
    )


def refresh_reaction_at_turn_start(*, owner_entry_id: str, current_turn_entry_id: str) -> bool:
    return owner_entry_id == current_turn_entry_id


def create_ready_state(
    *,
    owner_entry_id: str,
    trigger: str,
    response: str,
    created_turn_key: str,
    expires_at_owner_turn_key: str,
    spell_ref: str | None = None,
    spell_slot_level: int | None = None,
    concentration_started: bool = False,
) -> ReadyState:
    return ReadyState(
        owner_entry_id=owner_entry_id,
        trigger=trigger,
        response=response,
        created_turn_key=created_turn_key,
        expires_at_owner_turn_key=expires_at_owner_turn_key,
        spell_ref=spell_ref,
        spell_slot_level=spell_slot_level,
        concentration_started=concentration_started,
    )


def ready_trigger_matches(*, ready: ReadyState, trigger_key: str) -> bool:
    # The server passes a normalized trigger key only after deciding the declared
    # trigger has occurred; clients never self-trigger Ready.
    return bool(trigger_key.strip()) and trigger_key == ready.trigger


def expire_ready_at_turn_start(
    *, ready: ReadyState | None, owner_turn_key: str
) -> tuple[ReadyState | None, tuple[dict[str, object], ...]]:
    if ready is None or owner_turn_key != ready.expires_at_owner_turn_key:
        return ready, ()
    return None, (
        {
            "type": "reaction_expired",
            "kind": "ready",
            "owner_entry_id": ready.owner_entry_id,
            "refund": False,
        },
    )
