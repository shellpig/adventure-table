from app.content.schemas import ContentEntry
from app.domain.character_builder.multiclass import (
    multiclass_failure_detail,
    multiclass_option_failure_detail,
)
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderOptionKind,
)
from app.domain.character_builder.structural import feat_failure_detail


def _class(index: str, prerequisite: tuple[str, int] | None = None) -> ContentEntry:
    data: dict[str, object] = {"hit_die": 8}
    if prerequisite is not None:
        ability, minimum = prerequisite
        data["multi_classing"] = {
            "prerequisites": [
                {
                    "ability_score": {
                        "key": f"srd5.1:ability:{ability}",
                        "name": ability.upper(),
                    },
                    "minimum_score": minimum,
                }
            ]
        }
    return ContentEntry(
        key=f"srd5.1:class:{index}",
        index=index,
        name=index.title(),
        source="srd5.1",
        ruleset="dnd5e-2014",
        data=data,
    )


def test_builder_message_models_serialize_language_neutral_fields() -> None:
    option = BuilderChoiceOption(
        option_id="srd5.1:class:wizard",
        label="Wizard",
        kind=BuilderOptionKind.REFERENCE,
        reference_id="srd5.1:class:wizard",
        disabled_reason="Wizard: Requires INT 13+ to multiclass.",
        disabled_reason_code="multiclass_prerequisite_not_met",
        disabled_reason_params={
            "class_ref": "srd5.1:class:wizard",
            "requirements": [{"ability": "intelligence", "minimum_score": 13}],
        },
    )
    choice = BuilderChoice(
        choice_id="level:2:class-selection",
        label="Level 2 class",
        required=True,
        choose_count=1,
        options=(option,),
    )
    issue = BuilderIssue(
        code="invalid_fixed_hp_gain",
        severity=BuilderIssueSeverity.BLOCKING_ERROR,
        path="draft_payload.level_choices.1.hp_base_gain",
        message="Wizard fixed HP gain must be 4.",
        message_params={"class_ref": "srd5.1:class:wizard", "expected_hp_gain": 4},
    )

    payload = choice.model_dump(mode="json")
    assert payload["options"][0]["disabled_reason_code"] == "multiclass_prerequisite_not_met"
    assert payload["options"][0]["disabled_reason_params"]["class_ref"] == "srd5.1:class:wizard"
    assert issue.model_dump(mode="json")["message_params"] == {
        "class_ref": "srd5.1:class:wizard",
        "expected_hp_gain": 4,
    }


def test_multiclass_detail_uses_structured_ability_values() -> None:
    fighter = _class("fighter", ("str", 13))
    wizard = _class("wizard", ("int", 13))

    detail = multiclass_failure_detail(wizard, {
        "strength": 15,
        "dexterity": 10,
        "constitution": 12,
        "intelligence": 12,
        "wisdom": 10,
        "charisma": 8,
    })
    assert detail is not None
    assert detail.code == "multiclass_prerequisite_not_met"
    assert detail.params["class_ref"] == "srd5.1:class:wizard"
    assert detail.params["requirements"] == [
        {"ability": "intelligence", "minimum_score": 13}
    ]

    option_detail = multiclass_option_failure_detail(
        wizard,
        (fighter,),
        {
            "strength": 12,
            "dexterity": 10,
            "constitution": 12,
            "intelligence": 14,
            "wisdom": 10,
            "charisma": 8,
        },
    )
    assert option_detail is not None
    assert option_detail.params["blocking_class_ref"] == "srd5.1:class:fighter"
    assert option_detail.params["requirements"] == [
        {"ability": "strength", "minimum_score": 13}
    ]


def test_feat_detail_uses_stable_key_and_structured_requirements() -> None:
    feat = ContentEntry(
        key="phb2014:feat:sample-feat",
        index="sample-feat",
        name="Sample Feat",
        source="phb2014",
        ruleset="dnd5e-2014",
        data={
            "prerequisites": [
                {
                    "ability_score": {
                        "key": "srd5.1:ability:dex",
                        "name": "DEX",
                    },
                    "minimum_score": 13,
                }
            ]
        },
    )

    detail = feat_failure_detail(feat, {
        "strength": 10,
        "dexterity": 12,
        "constitution": 10,
        "intelligence": 10,
        "wisdom": 10,
        "charisma": 10,
    })
    assert detail is not None
    assert detail.code == "feat_prerequisite_not_met"
    assert detail.params == {
        "feat_ref": "phb2014:feat:sample-feat",
        "requirements": [{"ability": "dexterity", "minimum_score": 13}],
    }
