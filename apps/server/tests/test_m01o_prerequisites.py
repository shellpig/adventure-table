from app.domain.character_builder.m01o_prerequisites import (
    M01OPrerequisiteContext,
    m01o_requirement_failure,
)


def test_ancestry_prerequisite_distinguishes_missing_context_from_mismatch() -> None:
    requirement = {"type": "ancestry", "refs": ["srd5.1:race:elf"]}

    assert m01o_requirement_failure(requirement, M01OPrerequisiteContext()) == {
        "type": "ancestry_context_missing",
        "allowed_refs": ["srd5.1:race:elf"],
    }
    assert m01o_requirement_failure(
        requirement,
        M01OPrerequisiteContext(ancestry_ref="srd5.1:race:human"),
    ) == {
        "type": "ancestry",
        "allowed_refs": ["srd5.1:race:elf"],
        "actual_ref": "srd5.1:race:human",
    }
    assert m01o_requirement_failure(
        requirement,
        M01OPrerequisiteContext(ancestry_ref="srd5.1:race:elf"),
    ) is None


def test_size_prerequisite_distinguishes_missing_context_from_mismatch() -> None:
    requirement = {"type": "size", "sizes": ["Small"]}

    assert m01o_requirement_failure(requirement, M01OPrerequisiteContext()) == {
        "type": "size_context_missing",
        "allowed_sizes": ["small"],
    }
    assert m01o_requirement_failure(
        requirement,
        M01OPrerequisiteContext(size="Medium"),
    ) == {"type": "size", "allowed_sizes": ["small"], "actual_size": "medium"}
    assert m01o_requirement_failure(requirement, M01OPrerequisiteContext(size="small")) is None


def test_subclass_spellcasting_feature_satisfies_spellcasting_requirement() -> None:
    assert m01o_requirement_failure(
        {"type": "spellcasting"},
        M01OPrerequisiteContext(
            feature_refs=frozenset({"srd5.1:feature:eldritch-knight-spellcasting"})
        ),
    ) is None


def test_pact_magic_feature_satisfies_spellcasting_requirement() -> None:
    assert m01o_requirement_failure(
        {"type": "spellcasting"},
        M01OPrerequisiteContext(feature_refs=frozenset({"srd5.1:feature:pact-magic"})),
    ) is None


def test_feature_prerequisite_uses_effective_server_features() -> None:
    assert m01o_requirement_failure(
        {"type": "feature", "refs": ["srd5.1:feature:spellcasting"]},
        M01OPrerequisiteContext(feature_refs=frozenset({"srd5.1:feature:spellcasting"})),
    ) is None


def test_proficiency_prerequisite_accepts_armor_implication() -> None:
    assert m01o_requirement_failure(
        {"type": "proficiency", "refs": ["srd5.1:proficiency:heavy-armor"]},
        M01OPrerequisiteContext(
            proficiency_refs=frozenset({"srd5.1:proficiency:all-armor"})
        ),
    ) is None


def test_any_of_accepts_first_satisfied_expanded_prerequisite() -> None:
    requirement = {
        "type": "any_of",
        "options": [
            {"type": "ancestry", "refs": ["srd5.1:race:elf"]},
            {"type": "size", "sizes": ["small"]},
        ],
    }

    assert m01o_requirement_failure(
        requirement,
        M01OPrerequisiteContext(size="Small"),
    ) is None
