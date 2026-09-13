from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


SPELLCASTING_FEATURE_ALIASES = frozenset(
    {
        "spellcasting",
        "pact_magic",
        "pact-magic",
        "srd5.1:feature:spellcasting",
        "srd5.1:feature:pact-magic",
    }
)
ARMOR_PROFICIENCY_IMPLICATIONS = {
    "srd5.1:proficiency:all-armor": frozenset(
        {
            "srd5.1:proficiency:light-armor",
            "srd5.1:proficiency:medium-armor",
            "srd5.1:proficiency:heavy-armor",
        }
    ),
}


@dataclass(frozen=True, slots=True)
class M01OPrerequisiteContext:
    """Server-built context for M01-O expanded feat prerequisite atoms.

    The client may render prerequisite hints, but the authoritative acquisition
    path must rebuild this context from the persisted draft/character state.
    Missing ancestry/lineage/size is intentionally represented as None so the
    evaluator can distinguish unavailable context from an explicit mismatch.
    """

    ability_scores: Mapping[str, int] | None = None
    ancestry_ref: str | None = None
    lineage_ref: str | None = None
    size: str | None = None
    feature_refs: frozenset[str] = frozenset()
    proficiency_refs: frozenset[str] = frozenset()
    has_spellcasting: bool = False

    @property
    def effective_feature_refs(self) -> frozenset[str]:
        features = set(self.feature_refs)
        if self.has_spellcasting:
            features.add("spellcasting")
        return frozenset(features)


def _strings(value: object) -> list[str]:
    # Lists, not tuples: these values are embedded verbatim in
    # ``BuilderIssue.message_params`` / ``disabled_reason_params`` (JsonValue).
    if isinstance(value, str):
        return [value]
    if not isinstance(value, Iterable) or isinstance(value, (bytes, bytearray, Mapping)):
        return []
    return [item for item in value if isinstance(item, str)]


def _refs(requirement: Mapping[str, object], *keys: str) -> list[str]:
    for key in keys:
        values = _strings(requirement.get(key))
        if values:
            return values
    return []


def _normalized_size(size: str | None) -> str | None:
    return size.lower().replace("_", "-") if size is not None else None


def _is_spellcasting_feature(feature_ref: str) -> bool:
    normalized = feature_ref.lower().replace("_", "-")
    if normalized in SPELLCASTING_FEATURE_ALIASES:
        return True
    if normalized.endswith(":feature:spellcasting"):
        return True
    if normalized.endswith(":feature:pact-magic"):
        return True
    if normalized.endswith("-spellcasting"):
        return True
    return False


def _has_spellcasting_capability(context: M01OPrerequisiteContext) -> bool:
    return context.has_spellcasting or any(
        _is_spellcasting_feature(feature_ref)
        for feature_ref in context.effective_feature_refs
    )


def _has_proficiency(context: M01OPrerequisiteContext, required_ref: str) -> bool:
    if required_ref in context.proficiency_refs:
        return True
    return any(
        required_ref in ARMOR_PROFICIENCY_IMPLICATIONS.get(held_ref, ())
        for held_ref in context.proficiency_refs
    )


def m01o_requirement_failure(
    requirement: Mapping[str, object],
    context: M01OPrerequisiteContext,
) -> dict[str, object] | None:
    req_type = requirement.get("type")

    if req_type == "ancestry":
        allowed = _refs(requirement, "refs", "ancestry_refs", "ancestry_ref")
        if not allowed:
            return {"type": "unsupported"}
        if context.ancestry_ref is None:
            return {"type": "ancestry_context_missing", "allowed_refs": allowed}
        if context.ancestry_ref not in allowed:
            return {
                "type": "ancestry",
                "allowed_refs": allowed,
                "actual_ref": context.ancestry_ref,
            }
        return None

    if req_type == "lineage":
        allowed = _refs(requirement, "refs", "lineage_refs", "lineage_ref")
        if not allowed:
            return {"type": "unsupported"}
        if context.lineage_ref is None:
            return {"type": "lineage_context_missing", "allowed_refs": allowed}
        if context.lineage_ref not in allowed:
            return {
                "type": "lineage",
                "allowed_refs": allowed,
                "actual_ref": context.lineage_ref,
            }
        return None

    if req_type == "size":
        allowed = [
            normalized
            for size in _refs(requirement, "sizes", "size")
            if (normalized := _normalized_size(size)) is not None
        ]
        if not allowed:
            return {"type": "unsupported"}
        actual = _normalized_size(context.size)
        if actual is None:
            return {"type": "size_context_missing", "allowed_sizes": allowed}
        if actual not in allowed:
            return {"type": "size", "allowed_sizes": allowed, "actual_size": actual}
        return None

    if req_type == "feature":
        required = _refs(requirement, "refs", "feature_refs", "feature_ref")
        if not required:
            return {"type": "unsupported"}
        if not context.effective_feature_refs.intersection(required):
            return {"type": "feature", "required_refs": required}
        return None

    if req_type == "proficiency":
        required = _refs(requirement, "refs", "proficiency_refs", "proficiency_ref")
        if not required:
            return {"type": "unsupported"}
        if not any(_has_proficiency(context, ref) for ref in required):
            return {"type": "proficiency", "required_refs": required}
        return None

    if req_type == "spellcasting":
        if _has_spellcasting_capability(context):
            return None
        return {"type": "spellcasting"}

    if req_type == "any_of":
        options = requirement.get("options")
        if not isinstance(options, list) or not options:
            return {"type": "unsupported"}
        failures: list[dict[str, object]] = []
        for option in options:
            if not isinstance(option, Mapping):
                return {"type": "unsupported"}
            failure = m01o_requirement_failure(option, context)
            if failure is None:
                return None
            failures.append(failure)
        return {"type": "any_of", "options": failures}

    return {"type": "unsupported"}


def is_m01o_prerequisite_type(req_type: object) -> bool:
    return req_type in {
        "ancestry",
        "lineage",
        "size",
        "feature",
        "proficiency",
        "spellcasting",
        "any_of",
    }
