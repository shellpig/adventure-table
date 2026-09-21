from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.domain.campaign_runtime.context_schemas import (
    ActiveCombatRef,
    AdventureSceneRef,
    AttachedAdventureRef,
    CampaignContextDmView,
    CampaignContextPlayerView,
    CampaignInvalidSceneRefError,
    CampaignPartyMemberView,
    CurrentSceneView,
    RuntimeSceneRef,
    SceneContextDmView,
    SceneContextPlayerView,
    SceneRef,
    WorldEntryRef,
)
from app.domain.campaign_runtime.payloads import RuntimeItemPayload, parse_runtime_payload
from app.domain.campaign_runtime.schemas import (
    CampaignAdventureEntryOverlayView,
    CampaignRuntimeContext,
    RuntimeWorldEntryDmView,
    RuntimeWorldEntryPlayerView,
)
from app.domain.campaign_runtime.service import (
    CampaignRuntimeAuthorityError,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeService,
    CampaignRuntimeValidationError,
    _get_adventure_entry_overlay_in_transaction,
    project_runtime_aggregate,
)
from app.domain.rooms.table_events import TableActorContext
from app.persistence.adventures.repository import AdventureRepository
from app.persistence.campaign_runtime.repository import StoredRuntimeWorldEntryAggregate
from app.persistence.characters import characters
from app.persistence.combat.lifecycle import CombatRepository
from app.persistence.rooms.campaigns import StoredCampaign


def _is_item_in_scene(aggregate: StoredRuntimeWorldEntryAggregate, scene_id: UUID) -> bool:
    if aggregate.entry.kind != "item":
        return False
    payload = parse_runtime_payload("item", aggregate.entry.state_json)
    assert isinstance(payload, RuntimeItemPayload)
    holder = payload.holder_ref
    return holder is not None and holder.kind == "scene" and holder.target_id == scene_id


def _no_scene_view(actor: TableActorContext) -> SceneContextDmView | SceneContextPlayerView:
    if actor.is_current_dm:
        return SceneContextDmView()
    return SceneContextPlayerView()


class CampaignContextService:
    """Actor-scoped, role-projected Campaign context retrieval (P6-C read side).

    Composes the P6-B active read intents; authority and projection stay in
    ``CampaignRuntimeService`` / ``project_runtime_aggregate``.
    """

    def __init__(self, runtime_service: CampaignRuntimeService) -> None:
        self.runtime_service = runtime_service
        self.engine = runtime_service.engine
        self.event_service = runtime_service.event_service
        self.campaign_repo = runtime_service.campaign_repo
        self.runtime_repo = runtime_service.runtime_repo
        self.link_repo = runtime_service.link_repo
        self.session_repo = runtime_service.session_repo
        self.adventure_repo = AdventureRepository(runtime_service.engine)
        self.combat_repo = CombatRepository(runtime_service.engine, self.event_service.repository)

    def get_campaign_context(
        self,
        actor: TableActorContext,
    ) -> CampaignContextDmView | CampaignContextPlayerView:
        with self.engine.connect() as connection:
            self.runtime_service._require_active_actor(connection, actor)
            campaign = self._campaign_or_404(connection, actor)
            stored_context = self.runtime_repo.get_context_in_transaction(
                connection, actor.campaign_id
            )
            current_situation = stored_context.current_situation if stored_context else None
            current_scene = self._resolve_current_scene_ref(connection, actor, stored_context)
            party = self._resolve_party(connection, actor)
            active_combat = self._resolve_active_combat(actor)
            world_entries = self._resolve_world_entries(actor)

            if actor.is_current_dm:
                return CampaignContextDmView(
                    campaign_id=campaign.id,
                    name=campaign.name,
                        current_scene=current_scene,
                    current_situation=current_situation,
                    party=party,
                    active_combat=active_combat,
                    attached_adventures=self._resolve_attached_adventures(actor),
                    world_entries=world_entries,
                )
            return CampaignContextPlayerView(
                campaign_id=campaign.id,
                name=campaign.name,
                current_scene=current_scene,
                current_situation=current_situation,
                party=party,
                active_combat=active_combat,
                world_entries=world_entries,
            )

    def get_scene_context(
        self,
        actor: TableActorContext,
        scene_ref: SceneRef | None = None,
    ) -> SceneContextDmView | SceneContextPlayerView:
        with self.engine.connect() as connection:
            self.runtime_service._require_active_actor(connection, actor)
            self._campaign_or_404(connection, actor)

            if isinstance(scene_ref, AdventureSceneRef):
                # Players may never reference Adventure entries; reject before any
                # lookup so existence cannot be probed.
                if not actor.is_current_dm:
                    raise CampaignInvalidSceneRefError(
                        "Adventure scene references are only available to the current DM"
                    )
                return self._resolve_adventure_scene(
                    connection, actor, scene_ref.adventure_entry_id
                )
            if isinstance(scene_ref, RuntimeSceneRef):
                return self._resolve_runtime_scene(
                    connection, actor, scene_ref.runtime_entry_id, is_current_scene=False
                )

            stored_context = self.runtime_repo.get_context_in_transaction(
                connection, actor.campaign_id
            )
            if stored_context is None:
                return _no_scene_view(actor)
            if stored_context.current_adventure_scene_entry_id is not None:
                if not actor.is_current_dm:
                    return _no_scene_view(actor)
                return self._resolve_adventure_scene(
                    connection, actor, stored_context.current_adventure_scene_entry_id
                )
            if stored_context.current_runtime_scene_entry_id is not None:
                return self._resolve_runtime_scene(
                    connection,
                    actor,
                    stored_context.current_runtime_scene_entry_id,
                    is_current_scene=True,
                )
            return _no_scene_view(actor)

    def get_world_entry(
        self,
        actor: TableActorContext,
        world_entry_id: UUID,
    ) -> RuntimeWorldEntryDmView | RuntimeWorldEntryPlayerView:
        return self.runtime_service.get_active(actor, world_entry_id)

    def get_adventure_entry(
        self,
        actor: TableActorContext,
        adventure_entry_id: UUID,
    ) -> CampaignAdventureEntryOverlayView:
        if not actor.is_current_dm:
            raise CampaignRuntimeAuthorityError("Only the current DM may read adventure entries")
        return self.runtime_service.get_adventure_entry_overlay_active(actor, adventure_entry_id)

    def _campaign_or_404(self, connection: Connection, actor: TableActorContext) -> StoredCampaign:
        campaign = self.campaign_repo.get_in_transaction(connection, actor.campaign_id)
        if campaign is None or campaign.room_id != actor.room_id:
            raise CampaignRuntimeNotFoundError(
                f"Campaign {actor.campaign_id} not found in room {actor.room_id}"
            )
        return campaign

    def _controlled_character_ids(
        self, connection: Connection, actor: TableActorContext
    ) -> tuple[UUID, ...]:
        return self.event_service.repository.active_character_ids_for_seats_in_transaction(
            connection, actor.session_id, actor.controlled_seat_ids
        )

    def _project_for_actor(
        self,
        connection: Connection,
        actor: TableActorContext,
        aggregates: list[StoredRuntimeWorldEntryAggregate],
    ) -> tuple[RuntimeWorldEntryDmView, ...] | tuple[RuntimeWorldEntryPlayerView, ...]:
        if actor.is_current_dm:
            dm_views: list[RuntimeWorldEntryDmView] = []
            for aggregate in aggregates:
                view = project_runtime_aggregate(aggregate, controlled_character_ids=(), is_dm=True)
                assert isinstance(view, RuntimeWorldEntryDmView)
                dm_views.append(view)
            return tuple(dm_views)
        controlled = self._controlled_character_ids(connection, actor)
        player_views: list[RuntimeWorldEntryPlayerView] = []
        for aggregate in aggregates:
            view = project_runtime_aggregate(
                aggregate, controlled_character_ids=controlled, is_dm=False
            )
            if view is not None:
                assert isinstance(view, RuntimeWorldEntryPlayerView)
                player_views.append(view)
        return tuple(player_views)

    def _resolve_current_scene_ref(
        self,
        connection: Connection,
        actor: TableActorContext,
        stored_context: CampaignRuntimeContext | None,
    ) -> CurrentSceneView:
        if stored_context is None:
            return CurrentSceneView(kind="none")

        if stored_context.current_adventure_scene_entry_id is not None:
            adventure_entry_id = stored_context.current_adventure_scene_entry_id
            if not actor.is_current_dm:
                return CurrentSceneView(kind="none")
            # Detach is blocked while the Current Scene points at this entry, so the
            # overlay lookup cannot miss; let any failure propagate.
            overlay = _get_adventure_entry_overlay_in_transaction(
                connection,
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                adventure_entry_id=adventure_entry_id,
                link_repo=self.link_repo,
                runtime_repo=self.runtime_repo,
            )
            return CurrentSceneView(
                kind="adventure", label=overlay.title, entry_id=adventure_entry_id
            )

        if stored_context.current_runtime_scene_entry_id is not None:
            runtime_entry_id = stored_context.current_runtime_scene_entry_id
            aggregate = self.runtime_repo.get_entry_in_transaction(
                connection, actor.campaign_id, runtime_entry_id, include_archived=False
            )
            if aggregate is not None:
                views = self._project_for_actor(connection, actor, [aggregate])
                if views:
                    scene = views[0]
                    return CurrentSceneView(
                        kind="runtime", label=scene.title or scene.body, entry_id=runtime_entry_id
                    )

        return CurrentSceneView(kind="none")

    def _resolve_party(
        self,
        connection: Connection,
        actor: TableActorContext,
    ) -> tuple[CampaignPartyMemberView, ...]:
        participants = self.session_repo.list_participants(actor.session_id)
        character_ids = [p.active_character_id for p in participants if p.active_character_id]
        names: dict[UUID, str] = {}
        if character_ids:
            rows = connection.execute(
                select(characters.c.id, characters.c.name).where(characters.c.id.in_(character_ids))
            ).mappings()
            names = {row["id"]: row["name"] for row in rows}
        return tuple(
            CampaignPartyMemberView(
                seat_id=p.seat_id,
                role=p.role_snapshot,
                active_character_id=p.active_character_id,
                character_label=(
                    names.get(p.active_character_id) if p.active_character_id else None
                ),
            )
            for p in participants
        )

    def _resolve_active_combat(self, actor: TableActorContext) -> ActiveCombatRef | None:
        combat = self.combat_repo.get_active(actor.campaign_id)
        if combat is None:
            return None
        return ActiveCombatRef(
            combat_id=combat.id,
            round=combat.round_number,
            current_turn_entry_id=combat.current_turn_entry_id,
        )

    def _resolve_attached_adventures(
        self, actor: TableActorContext
    ) -> tuple[AttachedAdventureRef, ...]:
        # Links are FK RESTRICT to same-Room definitions, so every link resolves.
        definitions = {d.id: d for d in self.adventure_repo.list_definitions(actor.room_id)}
        return tuple(
            AttachedAdventureRef(
                adventure_id=link.adventure_id, name=definitions[link.adventure_id].name
            )
            for link in self.link_repo.list_for_campaign(actor.campaign_id)
        )

    def _resolve_world_entries(self, actor: TableActorContext) -> tuple[WorldEntryRef, ...]:
        return tuple(
            WorldEntryRef(id=e.id, kind=e.kind, title=e.title, visibility=e.visibility)
            for e in self.runtime_service.list_active(actor, include_archived=False)
        )

    def _related_aggregates(
        self,
        connection: Connection,
        actor: TableActorContext,
        *,
        scene_id: UUID,
        source_adventure_entry_id: UUID | None,
        exclude_id: UUID | None = None,
    ) -> list[StoredRuntimeWorldEntryAggregate]:
        return [
            a
            for a in self.runtime_repo.list_entries_in_transaction(
                connection, actor.campaign_id, include_archived=False
            )
            if a.entry.id != exclude_id
            and (
                (
                    source_adventure_entry_id is not None
                    and a.entry.source_adventure_entry_id == source_adventure_entry_id
                )
                or _is_item_in_scene(a, scene_id)
            )
        ]

    def _resolve_adventure_scene(
        self,
        connection: Connection,
        actor: TableActorContext,
        adventure_entry_id: UUID,
    ) -> SceneContextDmView | SceneContextPlayerView:
        try:
            overlay = _get_adventure_entry_overlay_in_transaction(
                connection,
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                adventure_entry_id=adventure_entry_id,
                link_repo=self.link_repo,
                runtime_repo=self.runtime_repo,
            )
        except (CampaignRuntimeNotFoundError, CampaignRuntimeValidationError) as exc:
            raise CampaignInvalidSceneRefError(str(exc)) from exc
        if overlay.kind != "scene":
            raise CampaignInvalidSceneRefError(
                f"Adventure entry {adventure_entry_id} is not a scene (kind={overlay.kind})"
            )

        related = self._related_aggregates(
            connection,
            actor,
            scene_id=adventure_entry_id,
            source_adventure_entry_id=adventure_entry_id,
        )
        views = self._project_for_actor(connection, actor, related)
        if actor.is_current_dm:
            return SceneContextDmView(
                scene_id=adventure_entry_id,
                scene_kind="adventure",
                title=overlay.title,
                baseline=overlay,
                override=overlay.override,
                current_truth="override" if overlay.override is not None else "baseline",
                related_entries=views,
            )
        # Player: the Adventure scene itself is never exposed; only Runtime entries
        # already projected for this actor.
        return SceneContextPlayerView(related_entries=views)

    def _resolve_runtime_scene(
        self,
        connection: Connection,
        actor: TableActorContext,
        runtime_entry_id: UUID,
        *,
        is_current_scene: bool,
    ) -> SceneContextDmView | SceneContextPlayerView:
        aggregate = self.runtime_repo.get_entry_in_transaction(
            connection, actor.campaign_id, runtime_entry_id, include_archived=False
        )
        if aggregate is None:
            raise CampaignInvalidSceneRefError(
                f"Runtime entry {runtime_entry_id} not found in campaign {actor.campaign_id}"
            )
        if aggregate.entry.kind != "scene":
            raise CampaignInvalidSceneRefError(
                f"Runtime entry {runtime_entry_id} is not a scene (kind={aggregate.entry.kind})"
            )

        scene_views = self._project_for_actor(connection, actor, [aggregate])
        if not scene_views:
            # Invisible to this Player: a Current Scene degrades to "no scene", an
            # explicit ref is indistinguishable from a missing one.
            if is_current_scene:
                return _no_scene_view(actor)
            raise CampaignInvalidSceneRefError(
                f"Runtime entry {runtime_entry_id} not found in campaign {actor.campaign_id}"
            )
        scene = scene_views[0]
        related = self._project_for_actor(
            connection,
            actor,
            self._related_aggregates(
                connection,
                actor,
                scene_id=runtime_entry_id,
                source_adventure_entry_id=aggregate.entry.source_adventure_entry_id,
                exclude_id=runtime_entry_id,
            ),
        )
        if actor.is_current_dm:
            assert isinstance(scene, RuntimeWorldEntryDmView)
            return SceneContextDmView(
                scene_id=runtime_entry_id,
                scene_kind="runtime",
                title=scene.title or scene.body,
                runtime_scene=scene,
                current_truth="runtime",
                related_entries=related,
            )
        assert isinstance(scene, RuntimeWorldEntryPlayerView)
        return SceneContextPlayerView(
            scene_id=runtime_entry_id,
            scene_kind="runtime",
            title=scene.title or scene.body,
            runtime_scene=scene,
            related_entries=related,
        )


__all__ = ["CampaignContextService"]
