from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from app.content.identity import reference_to_stable_key
from app.content.registry import ContentRegistry
from app.content.schemas import ContentEntry
from app.domain.character.schemas import StartingEquipmentEntry
from app.domain.character_builder.creation import BuilderEquipmentSummary
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderOptionKind,
)


@dataclass(frozen=True)
class EquipmentCompilation:
    choices: tuple[BuilderChoice, ...]
    starting_equipment: tuple[StartingEquipmentEntry, ...]
    summary: tuple[BuilderEquipmentSummary, ...]
    issues: tuple[BuilderIssue, ...]


@dataclass(frozen=True)
class _Atom:
    source_ref: str
    path: str
    item_ref: str
    quantity: int


def _issue(code: str, path: str, message: str, *refs: str) -> BuilderIssue:
    return BuilderIssue(
        code=code,
        severity=BuilderIssueSeverity.BLOCKING_ERROR,
        path=path,
        message=message,
        related_refs=tuple(refs),
    )


def _choice_id(source_ref: str, path: str) -> str:
    source_index = source_ref.split(":", 2)[-1]
    digest = sha256(f"{source_ref}|{path}".encode("utf-8")).hexdigest()[:12]
    return f"equipment:{source_index}:{digest}"


def _entry_id(atom: _Atom) -> str:
    digest = sha256(
        f"{atom.source_ref}|{atom.path}|{atom.item_ref}|{atom.quantity}".encode("utf-8")
    ).hexdigest()[:20]
    return f"start:{digest}"


def _stable_equipment_ref(raw: Any) -> str | None:
    if not isinstance(raw, dict):
        return None
    try:
        return reference_to_stable_key(raw, kinds={"equipment"})
    except ValueError:
        return None


def _selection_ids(draft: BuilderDraft, choice_id: str) -> tuple[str, ...]:
    raw = draft.draft_payload.starting_equipment_choices.get(choice_id)
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,) if raw else ()
    if isinstance(raw, list) and all(isinstance(value, str) for value in raw):
        return tuple(raw)
    if isinstance(raw, dict):
        nested = raw.get("selected_option_ids")
        if isinstance(nested, list) and all(isinstance(value, str) for value in nested):
            return tuple(nested)
    return ()


def _category_options(
    raw_from: dict[str, Any],
    registry: ContentRegistry,
) -> tuple[list[dict[str, Any]], BuilderIssue | None]:
    category = raw_from.get("equipment_category")
    if not isinstance(category, dict):
        return [], _issue(
            "equipment_rules_data_error",
            "starting_equipment",
            "Equipment category choice is missing its category reference.",
        )
    try:
        category_ref = reference_to_stable_key(category, kinds={"equipment-category"})
    except ValueError:
        category_ref = None
    if category_ref is None:
        return [], _issue(
            "equipment_rules_data_error",
            "starting_equipment",
            "Equipment category choice has an invalid category reference.",
        )
    entry = registry.get_optional(category_ref)
    if entry is None:
        return [], _issue(
            "equipment_rules_data_error",
            "starting_equipment",
            f"Unknown equipment category: {category_ref}",
            category_ref,
        )
    raw_items = entry.data.get("equipment")
    if not isinstance(raw_items, list):
        return [], _issue(
            "equipment_rules_data_error",
            "starting_equipment",
            f"Equipment category has no item list: {category_ref}",
            category_ref,
        )
    options: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        options.append({"option_type": "counted_reference", "count": 1, "of": item})
    return options, None


def _raw_options(
    raw_choice: dict[str, Any],
    registry: ContentRegistry,
) -> tuple[list[dict[str, Any]], BuilderIssue | None]:
    raw_from = raw_choice.get("from")
    if not isinstance(raw_from, dict):
        return [], _issue(
            "equipment_rules_data_error",
            "starting_equipment",
            "Starting equipment choice is missing its option source.",
        )
    source_type = raw_from.get("option_set_type")
    if source_type == "options_array":
        raw_options = raw_from.get("options")
        if not isinstance(raw_options, list):
            return [], _issue(
                "equipment_rules_data_error",
                "starting_equipment",
                "Starting equipment options_array is missing options.",
            )
        return [value for value in raw_options if isinstance(value, dict)], None
    if source_type == "equipment_category":
        return _category_options(raw_from, registry)
    return [], _issue(
        "equipment_rules_data_error",
        "starting_equipment",
        f"Unsupported starting equipment option source: {source_type!r}",
    )


def _option_label(raw_option: dict[str, Any], registry: ContentRegistry) -> str:
    kind = raw_option.get("option_type")
    if kind in {"counted_reference", "reference"}:
        reference = raw_option.get("of") if kind == "counted_reference" else raw_option.get("item")
        if not isinstance(reference, dict):
            return "Unknown equipment"
        item_ref = _stable_equipment_ref(reference)
        item = registry.get_optional(item_ref or "")
        name = (
            f"{item.name} · {item.source_label or item.source}"
            if item is not None
            else str(reference.get("name") or reference.get("index") or "Equipment")
        )
        count = raw_option.get("count", 1)
        return f"{count} × {name}" if isinstance(count, int) and count > 1 else name
    if kind == "choice":
        nested = raw_option.get("choice")
        if isinstance(nested, dict):
            desc = nested.get("desc")
            if isinstance(desc, str) and desc.strip():
                return desc
        return "Choose equipment"
    if kind == "multiple":
        items = raw_option.get("items")
        if isinstance(items, list):
            labels = [_option_label(item, registry) for item in items if isinstance(item, dict)]
            if labels:
                return " + ".join(labels)
        return "Equipment bundle"
    return str(raw_option.get("string") or "Equipment option")


def _builder_option(
    choice_id: str,
    raw_option: dict[str, Any],
    option_index: int,
    registry: ContentRegistry,
) -> BuilderChoiceOption:
    kind = raw_option.get("option_type")
    option_id = f"{choice_id}:option:{option_index}"
    if kind in {"counted_reference", "reference"}:
        reference = raw_option.get("of") if kind == "counted_reference" else raw_option.get("item")
        item_ref = _stable_equipment_ref(reference)
        return BuilderChoiceOption(
            option_id=option_id,
            label=_option_label(raw_option, registry),
            kind=BuilderOptionKind.COUNTED_REFERENCE,
            reference_id=item_ref,
            count=int(raw_option.get("count", 1)) if kind == "counted_reference" else 1,
        )
    if kind == "choice":
        return BuilderChoiceOption(
            option_id=option_id,
            label=_option_label(raw_option, registry),
            kind=BuilderOptionKind.NESTED_CHOICE,
            nested_choice_id=f"{choice_id}:nested:{option_index}",
        )
    if kind == "multiple":
        return BuilderChoiceOption(
            option_id=option_id,
            label=_option_label(raw_option, registry),
            kind=BuilderOptionKind.BRANCH,
            branch_key=f"{choice_id}:bundle:{option_index}",
        )
    return BuilderChoiceOption(
        option_id=option_id,
        label=_option_label(raw_option, registry),
        kind=BuilderOptionKind.BRANCH,
        disabled_reason=f"Unsupported equipment option type: {kind!r}",
    )


def _resolve_fixed_item(
    source_ref: str,
    path: str,
    raw_option: dict[str, Any],
    registry: ContentRegistry,
) -> tuple[_Atom | None, BuilderIssue | None]:
    kind = raw_option.get("option_type")
    reference = raw_option.get("of") if kind == "counted_reference" else raw_option.get("item")
    item_ref = _stable_equipment_ref(reference)
    count = raw_option.get("count", 1) if kind == "counted_reference" else 1
    if item_ref is None or registry.get_optional(item_ref) is None:
        return None, _issue(
            "equipment_rules_data_error",
            path,
            f"Starting equipment references an unknown item: {item_ref or reference!r}",
            *(tuple([item_ref]) if item_ref else ()),
        )
    if not isinstance(count, int) or count < 1:
        return None, _issue(
            "equipment_rules_data_error",
            path,
            "Starting equipment quantity must be a positive integer.",
            item_ref,
        )
    return _Atom(source_ref=source_ref, path=path, item_ref=item_ref, quantity=count), None


def _resolve_choice(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    source_ref: str,
    raw_choice: dict[str, Any],
    path: str,
) -> tuple[list[BuilderChoice], list[_Atom], list[BuilderIssue]]:
    choice_id = _choice_id(source_ref, path)
    choose = raw_choice.get("choose", 1)
    if not isinstance(choose, int) or choose < 1:
        return [], [], [
            _issue(
                "equipment_rules_data_error",
                f"draft_payload.starting_equipment_choices.{choice_id}",
                "Starting equipment choose count must be a positive integer.",
                source_ref,
            )
        ]

    raw_options, data_issue = _raw_options(raw_choice, registry)
    options = tuple(
        _builder_option(choice_id, raw_option, index, registry)
        for index, raw_option in enumerate(raw_options)
    )
    selected = _selection_ids(draft, choice_id)
    label = raw_choice.get("desc")
    if not isinstance(label, str) or not label.strip():
        label = f"{registry.get(source_ref).name} — Starting Equipment"

    builder_choice = BuilderChoice(
        choice_id=choice_id,
        label=label,
        source_ref=source_ref,
        required=True,
        choose_count=choose,
        option_source="equipment",
        options=options,
        selected_option_ids=selected,
    )
    choices = [builder_choice]
    atoms: list[_Atom] = []
    issues: list[BuilderIssue] = []
    if data_issue is not None:
        issues.append(data_issue)
        return choices, atoms, issues

    selection_path = f"draft_payload.starting_equipment_choices.{choice_id}"
    if len(selected) != choose:
        issues.append(
            _issue(
                "invalid_equipment_choice_count",
                selection_path,
                f"{label} requires exactly {choose} selection(s).",
                source_ref,
            )
        )
        return choices, atoms, issues

    option_by_id = {
        f"{choice_id}:option:{index}": (index, raw_option)
        for index, raw_option in enumerate(raw_options)
    }
    illegal = [option_id for option_id in selected if option_id not in option_by_id]
    if illegal:
        issues.append(
            _issue(
                "invalid_equipment_option",
                selection_path,
                f"{label} contains an option that is not currently eligible.",
                *illegal,
            )
        )
        return choices, atoms, issues

    if len(selected) != len(set(selected)):
        issues.append(
            _issue(
                "duplicate_equipment_option",
                selection_path,
                f"{label} cannot select the same option more than once.",
            )
        )
        return choices, atoms, issues

    for option_id in selected:
        option_index, raw_option = option_by_id[option_id]
        kind = raw_option.get("option_type")
        option_path = f"{path}.option.{option_index}"
        if kind in {"counted_reference", "reference"}:
            atom, issue = _resolve_fixed_item(source_ref, option_path, raw_option, registry)
            if atom is not None:
                atoms.append(atom)
            if issue is not None:
                issues.append(issue)
            continue

        if kind == "choice":
            nested = raw_option.get("choice")
            if not isinstance(nested, dict):
                issues.append(
                    _issue(
                        "equipment_rules_data_error",
                        selection_path,
                        "Nested starting equipment choice is malformed.",
                        source_ref,
                    )
                )
                continue
            child_choices, child_atoms, child_issues = _resolve_choice(
                draft,
                registry,
                source_ref=source_ref,
                raw_choice=nested,
                path=f"{option_path}.choice",
            )
            choices.extend(child_choices)
            atoms.extend(child_atoms)
            issues.extend(child_issues)
            continue

        if kind == "multiple":
            raw_items = raw_option.get("items")
            if not isinstance(raw_items, list):
                issues.append(
                    _issue(
                        "equipment_rules_data_error",
                        selection_path,
                        "Starting equipment bundle is malformed.",
                        source_ref,
                    )
                )
                continue
            for child_index, child in enumerate(raw_items):
                if not isinstance(child, dict):
                    continue
                child_kind = child.get("option_type")
                child_path = f"{option_path}.item.{child_index}"
                if child_kind in {"counted_reference", "reference"}:
                    atom, issue = _resolve_fixed_item(source_ref, child_path, child, registry)
                    if atom is not None:
                        atoms.append(atom)
                    if issue is not None:
                        issues.append(issue)
                elif child_kind == "choice":
                    nested = child.get("choice")
                    if not isinstance(nested, dict):
                        issues.append(
                            _issue(
                                "equipment_rules_data_error",
                                selection_path,
                                "Nested bundle choice is malformed.",
                                source_ref,
                            )
                        )
                        continue
                    child_choices, child_atoms, child_issues = _resolve_choice(
                        draft,
                        registry,
                        source_ref=source_ref,
                        raw_choice=nested,
                        path=f"{child_path}.choice",
                    )
                    choices.extend(child_choices)
                    atoms.extend(child_atoms)
                    issues.extend(child_issues)
                else:
                    issues.append(
                        _issue(
                            "equipment_rules_data_error",
                            selection_path,
                            f"Unsupported equipment bundle option type: {child_kind!r}",
                            source_ref,
                        )
                    )
            continue

        issues.append(
            _issue(
                "equipment_rules_data_error",
                selection_path,
                f"Unsupported starting equipment option type: {kind!r}",
                source_ref,
            )
        )
    return choices, atoms, issues


def _automatic_atoms(source: ContentEntry, registry: ContentRegistry) -> tuple[list[_Atom], list[BuilderIssue]]:
    atoms: list[_Atom] = []
    issues: list[BuilderIssue] = []
    raw_entries = source.data.get("starting_equipment")
    if not isinstance(raw_entries, list):
        return atoms, issues
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            continue
        equipment = raw.get("equipment")
        option = {
            "option_type": "counted_reference",
            "count": raw.get("quantity", 1),
            "of": equipment,
        }
        atom, issue = _resolve_fixed_item(
            source.key,
            f"automatic.{index}",
            option,
            registry,
        )
        if atom is not None:
            atoms.append(atom)
        if issue is not None:
            issues.append(issue)
    return atoms, issues


def _source_entries(draft: BuilderDraft, registry: ContentRegistry) -> tuple[ContentEntry, ...]:
    payload = draft.draft_payload
    result: list[ContentEntry] = []
    if payload.level_choices:
        starting_class = registry.get_optional(payload.level_choices[0].class_ref)
        if starting_class is not None:
            result.append(starting_class)
    if payload.background_selection is not None:
        background = registry.get_optional(payload.background_selection.reference_id)
        if background is not None:
            result.append(background)
    return tuple(result)


def compile_starting_equipment(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> EquipmentCompilation:
    choices: list[BuilderChoice] = []
    atoms: list[_Atom] = []
    issues: list[BuilderIssue] = []
    live_choice_ids: set[str] = set()

    for source in _source_entries(draft, registry):
        automatic, automatic_issues = _automatic_atoms(source, registry)
        atoms.extend(automatic)
        issues.extend(automatic_issues)

        raw_choices = source.data.get("starting_equipment_options")
        if not isinstance(raw_choices, list):
            continue
        for index, raw_choice in enumerate(raw_choices):
            if not isinstance(raw_choice, dict):
                continue
            next_choices, next_atoms, next_issues = _resolve_choice(
                draft,
                registry,
                source_ref=source.key,
                raw_choice=raw_choice,
                path=f"choice.{index}",
            )
            choices.extend(next_choices)
            atoms.extend(next_atoms)
            issues.extend(next_issues)
            live_choice_ids.update(choice.choice_id for choice in next_choices)

    stale_choice_ids = tuple(
        key
        for key in draft.draft_payload.starting_equipment_choices
        if key not in live_choice_ids
    )
    for stale in stale_choice_ids:
        issues.append(
            _issue(
                "stale_equipment_choice",
                f"draft_payload.starting_equipment_choices.{stale}",
                "This starting-equipment selection no longer belongs to the current class/background choices.",
            )
        )

    entries: list[StartingEquipmentEntry] = []
    summary: list[BuilderEquipmentSummary] = []
    for atom in atoms:
        item = registry.get_optional(atom.item_ref)
        if item is None:
            continue
        entry_id = _entry_id(atom)
        entries.append(
            StartingEquipmentEntry(
                entry_id=entry_id,
                item_ref=atom.item_ref,
                quantity=atom.quantity,
            )
        )
        summary.append(
            BuilderEquipmentSummary(
                entry_id=entry_id,
                item_ref=atom.item_ref,
                name=item.name,
                quantity=atom.quantity,
                source_ref=atom.source_ref,
            )
        )

    entry_ids = [entry.entry_id for entry in entries]
    if len(entry_ids) != len(set(entry_ids)):
        issues.append(
            _issue(
                "equipment_entry_id_collision",
                "draft_payload.starting_equipment_choices",
                "Starting equipment produced duplicate deterministic entry ids.",
            )
        )

    return EquipmentCompilation(
        choices=tuple(choices),
        starting_equipment=tuple(entries),
        summary=tuple(summary),
        issues=tuple(issues),
    )
