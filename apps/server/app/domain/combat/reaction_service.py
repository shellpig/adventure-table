from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Literal, Mapping


class ReactionKind(StrEnum):
    OPPORTUNITY_ATTACK = "opportunity_attack"
    SHIELD = "shield"
    COUNTERSPELL = "counterspell"
    READY = "ready"
    LEGENDARY_ACTION = "legendary_action"
    OTHER = "other"


ReactionStatus = Literal["open", "resolved", "declined", "expired", "cancelled"]


@dataclass(frozen=True)
class ReactionWindow:
    """Durable P4-D reaction request payload.

    ``entry_id`` remains the primary owner for P4-B compatibility. The full
    eligible set supports group windows while still fitting the existing
    ``combat_entries.pending_reaction_state`` JSON column.
    """

    window_id: str
    entry_id: str
    kind: ReactionKind
    reason: str
    source_entry_id: str | None = None
    status: ReactionStatus = "open"
    eligible_entry_ids: tuple[str, ...] = ()
    target_entry_id: str | None = None
    safe_payload: Mapping[str, Any] | None = None
    secret_payload: Mapping[str, Any] | None = None
    session_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.window_id.strip() or not self.entry_id.strip() or not self.reason.strip():
            raise ValueError("reaction window id, entry id and reason are required")
        eligible = self.eligible_entry_ids or (self.entry_id,)
        if self.entry_id not in eligible:
            raise ValueError("primary reaction entry must be eligible")
        if len(eligible) != len(set(eligible)):
            raise ValueError("eligible reaction entries must be unique")

    @property
    def eligible(self) -> tuple[str, ...]:
        return self.eligible_entry_ids or (self.entry_id,)

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": 1,
            "open": self.status == "open",
            "window_id": self.window_id,
            "entry_id": self.entry_id,
            "kind": self.kind.value,
            "reason": self.reason,
            "source_entry_id": self.source_entry_id,
            "status": self.status,
            "eligible_entry_ids": list(self.eligible),
            "target_entry_id": self.target_entry_id,
            "safe_payload": dict(self.safe_payload or {}),
            "secret_payload": dict(self.secret_payload or {}),
            "session_ref": self.session_ref,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ReactionWindow":
        return cls(
            window_id=str(payload["window_id"]),
            entry_id=str(payload["entry_id"]),
            kind=ReactionKind(str(payload["kind"])),
            reason=str(payload["reason"]),
            source_entry_id=(str(payload["source_entry_id"]) if payload.get("source_entry_id") else None),
            status=str(payload.get("status", "open")),  # type: ignore[arg-type]
            eligible_entry_ids=tuple(str(item) for item in payload.get("eligible_entry_ids", ())),
            target_entry_id=(str(payload["target_entry_id"]) if payload.get("target_entry_id") else None),
            safe_payload=dict(payload.get("safe_payload") or {}),
            secret_payload=dict(payload.get("secret_payload") or {}),
            session_ref=(str(payload["session_ref"]) if payload.get("session_ref") else None),
        )


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

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": 1,
            "owner_entry_id": self.owner_entry_id,
            "trigger": self.trigger,
            "response": self.response,
            "created_turn_key": self.created_turn_key,
            "expires_at_owner_turn_key": self.expires_at_owner_turn_key,
            "spell_ref": self.spell_ref,
            "spell_slot_level": self.spell_slot_level,
            "concentration_started": self.concentration_started,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ReadyState":
        return cls(
            owner_entry_id=str(payload["owner_entry_id"]),
            trigger=str(payload["trigger"]),
            response=str(payload["response"]),
            created_turn_key=str(payload["created_turn_key"]),
            expires_at_owner_turn_key=str(payload["expires_at_owner_turn_key"]),
            spell_ref=(str(payload["spell_ref"]) if payload.get("spell_ref") else None),
            spell_slot_level=(int(payload["spell_slot_level"]) if payload.get("spell_slot_level") is not None else None),
            concentration_started=bool(payload.get("concentration_started", False)),
        )


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
    eligible_entry_ids: tuple[str, ...] = (),
    target_entry_id: str | None = None,
    safe_payload: Mapping[str, Any] | None = None,
    secret_payload: Mapping[str, Any] | None = None,
    session_ref: str | None = None,
) -> ReactionWindow:
    return ReactionWindow(
        window_id=window_id,
        entry_id=entry_id,
        kind=kind,
        reason=reason,
        source_entry_id=source_entry_id,
        eligible_entry_ids=eligible_entry_ids,
        target_entry_id=target_entry_id,
        safe_payload=safe_payload,
        secret_payload=secret_payload,
        session_ref=session_ref,
    )


def open_opportunity_attack_window(
    *,
    window_id: str,
    entry_id: str,
    source_entry_id: str,
    target_entry_id: str,
    dm_adjudicated: bool,
    session_ref: str | None = None,
) -> ReactionWindow:
    if not dm_adjudicated:
        raise PermissionError("Quick Combat opportunity attacks require DM adjudication")
    return open_reaction_window(
        window_id=window_id,
        entry_id=entry_id,
        kind=ReactionKind.OPPORTUNITY_ATTACK,
        reason="dm_adjudicated_opportunity_attack",
        source_entry_id=source_entry_id,
        target_entry_id=target_entry_id,
        session_ref=session_ref,
    )


def resolve_reaction(
    *,
    window: ReactionWindow,
    actor_entry_id: str,
    reaction_available: bool,
    accept: bool,
) -> ReactionResolution:
    if window.status != "open":
        raise ValueError("reaction window is not open")
    if actor_entry_id not in window.eligible:
        raise PermissionError("combat entry is not eligible for this reaction window")
    if accept and not reaction_available:
        raise ValueError("reaction is not available")
    resolved = replace(window, status="resolved" if accept else "declined")
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
                "actor_entry_id": actor_entry_id,
            },
        ),
    )


def cancel_reaction_window(window: ReactionWindow, *, reason: str) -> ReactionResolution:
    if window.status != "open":
        return ReactionResolution(True, window, ())
    cancelled = replace(window, status="cancelled")
    return ReactionResolution(
        True,
        cancelled,
        ({"type": "reaction_cancelled", "window_id": window.window_id, "reason": reason},),
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
    # Free-text Ready declarations are adjudicated by the server/DM. The domain
    # only consumes the normalized trigger key after that decision.
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


def spend_legendary_action(
    *,
    owner_entry_id: str,
    ended_turn_entry_id: str,
    available_points: int,
    cost: int,
) -> tuple[int, dict[str, object]]:
    """Represent the lightweight 2014 legendary-action timing/resource rule."""

    if owner_entry_id == ended_turn_entry_id:
        raise ValueError("legendary action can only be used at another creature's turn end")
    if cost <= 0:
        raise ValueError("legendary action cost must be positive")
    if available_points < cost:
        raise ValueError("insufficient legendary action resource")
    remaining = available_points - cost
    return remaining, {
        "type": "legendary_action_spent",
        "owner_entry_id": owner_entry_id,
        "ended_turn_entry_id": ended_turn_entry_id,
        "cost": cost,
        "remaining": remaining,
    }
