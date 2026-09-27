"""Opportunity Attack reach-crossing detection (P5-E, backend only).

Pure function: given a mover's anchor-by-anchor footprints and a set of
candidate reactors, find the steps where the mover leaves a reactor's melee
reach. A 5e 2014 opportunity attack fires when a creature *leaves* a
threatened square: the previous footprint is within reach and the next
footprint is not.

Eligibility mirrors the 2014 reaction rules: the reactor must be active,
hostile to the mover, have its reaction available, be alive, not be under an
incapacitating condition, and not already hold an open reaction window. The
mover must not have Disengaged this turn. Reach is the maximum
``ResolvedAttack.reach_feet`` over the reactor's melee attacks (unarmed 5 ft
when it has no melee attack); a ranged-only band never threatens.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.domain.combat.resolution import ResolvedAttack
from app.domain.spatial.pathing import grid_distance
from app.domain.spatial.primitives import Footprint, GridCell, occupied_cells

#: Melee reach assumed when a reactor has no melee ResolvedAttack (unarmed strike).
UNARMED_REACH_FEET = 5


@dataclass(frozen=True)
class OpportunityReactor:
    """One candidate reactor evaluated against a mover's path."""

    entry_id: UUID
    anchor: GridCell
    footprint: Footprint
    # All melee ResolvedAttacks from AttackDefinitionResolver.attacks_for;
    # reach is derived only from these, never from a guessed number.
    melee_attacks: tuple[ResolvedAttack, ...]
    turn_order: int | None
    hidden: bool
    hostile_to_mover: bool
    active: bool
    reaction_available: bool
    # Incapacitated-class condition (blocks_reactions in CONDITION_SEMANTICS).
    blocks_reactions: bool
    current_hp: int
    has_open_window: bool

    @property
    def reach_feet(self) -> int:
        reaches = [attack.reach_feet for attack in self.melee_attacks if attack.reach_feet is not None]
        return max(reaches) if reaches else UNARMED_REACH_FEET

    def eligible(self) -> bool:
        return (
            self.active
            and self.hostile_to_mover
            and self.reaction_available
            and self.current_hp > 0
            and not self.blocks_reactions
            and not self.has_open_window
        )


@dataclass(frozen=True)
class OpportunityCrossing:
    """One movement step where at least one reactor's reach is left."""

    # Index into the mover's anchor list of the step's *previous* anchor:
    # the mover pauses at anchors[step_index] (still inside reach).
    step_index: int
    # Reactor entry ids in deterministic order: canonical initiative order
    # (turn_order, nulls last), then stable input order as tie-break.
    reactor_entry_ids: tuple[UUID, ...]


def _within_reach(
    mover_anchor: GridCell,
    mover_footprint: Footprint,
    reactor: OpportunityReactor,
) -> bool:
    mover_cells = tuple(occupied_cells(mover_anchor.x, mover_anchor.y, mover_footprint))
    reactor_cells = tuple(occupied_cells(reactor.anchor.x, reactor.anchor.y, reactor.footprint))
    return grid_distance(mover_cells, reactor_cells).feet <= reactor.reach_feet


def detect_opportunity_crossings(
    *,
    anchors: tuple[GridCell, ...],
    mover_footprint: Footprint,
    reactors: tuple[OpportunityReactor, ...],
    mover_disengaged: bool,
) -> tuple[OpportunityCrossing, ...]:
    """Find every step where the mover leaves an eligible reactor's reach.

    ``anchors`` is the full validated path including the start anchor; step
    ``i`` moves from ``anchors[i]`` to ``anchors[i + 1]``. A reactor fires
    when the previous footprint is within its reach and the next footprint
    is not. A Disengaged mover never provokes. The caller splits hidden
    reactors (DM-only crossing note, no pause) from visible ones.
    """
    if mover_disengaged or len(anchors) < 2:
        return ()
    eligible = [reactor for reactor in reactors if reactor.eligible()]
    if not eligible:
        return ()
    # Deterministic order: canonical initiative order, then stable input order.
    order = {
        reactor.entry_id: index
        for index, reactor in enumerate(reactors)
    }
    eligible.sort(key=lambda r: (r.turn_order is None, r.turn_order or 0, order[r.entry_id]))
    crossings: list[OpportunityCrossing] = []
    for step_index in range(len(anchors) - 1):
        previous, nxt = anchors[step_index], anchors[step_index + 1]
        leaving = tuple(
            reactor.entry_id
            for reactor in eligible
            if _within_reach(previous, mover_footprint, reactor)
            and not _within_reach(nxt, mover_footprint, reactor)
        )
        if leaving:
            crossings.append(OpportunityCrossing(step_index=step_index, reactor_entry_ids=leaving))
    return tuple(crossings)


__all__ = [
    "UNARMED_REACH_FEET",
    "OpportunityCrossing",
    "OpportunityReactor",
    "detect_opportunity_crossings",
]
