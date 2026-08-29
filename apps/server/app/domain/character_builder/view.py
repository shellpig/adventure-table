from __future__ import annotations

from app.content.registry import ContentRegistry
from app.domain.character_builder.compiler import compile_builder_draft
from app.domain.character_builder.schemas import BuilderDraft, BuilderView


def build_builder_view(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> BuilderView:
    compiled = compile_builder_draft(draft, registry)
    return BuilderView(
        draft=draft,
        resolved_summary=compiled.resolved_summary,
        choices=compiled.choices,
        validation=compiled.validation,
    )
