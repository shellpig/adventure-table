from __future__ import annotations

from fastapi.testclient import TestClient

from app.content import load_default_content_registry
from app.content.localization import ContentLocalizationCatalog, LocalizableFieldPolicy
from app.content.registry import CONTENT_PACKS_ROOT
from app.main import app


POLICY_PATH = CONTENT_PACKS_ROOT / "localization" / "localizable-fields.json"


def _client_with_overlay() -> TestClient:
    registry = load_default_content_registry()
    policy = LocalizableFieldPolicy.from_path(POLICY_PATH)
    overlays = {
        ("srd5.1", "zh-TW"): {
            "srd5.1:class:fighter": {"name": "戰士"},
            "srd5.1:race:elf": {"name": "精靈"},
            "srd5.1:spell:fireball": {"name": "火球術"},
        }
    }
    app.state.content_registry = registry
    app.state.content_localization = ContentLocalizationCatalog(registry, policy, overlays)
    return TestClient(app)


def _name(presentation: dict[str, object]) -> str:
    fields = presentation["fields"]
    assert isinstance(fields, list)
    name = next(field for field in fields if field["field_path"] == "name")
    return str(name["value"])


def test_batch_presentation_resolves_zh_tw_names_by_stable_key_and_deduplicates() -> None:
    client = _client_with_overlay()
    references = [
        "srd5.1:class:fighter",
        "srd5.1:race:elf",
        "srd5.1:spell:fireball",
        "srd5.1:class:fighter",
    ]

    response = client.post(
        "/api/rules/presentation/batch?locale=zh-TW",
        json={"references": references},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["locale"] == "zh-TW"
    assert [item["key"] for item in payload["presentations"]] == references[:3]
    assert [_name(item) for item in payload["presentations"]] == ["戰士", "精靈", "火球術"]
    assert all(
        field["source"] == "overlay" and not field["fallback_used"]
        for item in payload["presentations"]
        for field in item["fields"]
    )


def test_batch_presentation_switches_locale_without_changing_identity() -> None:
    client = _client_with_overlay()
    references = ["srd5.1:class:fighter", "srd5.1:spell:fireball"]

    zh = client.post(
        "/api/rules/presentation/batch?locale=zh-TW",
        json={"references": references},
    ).json()
    en = client.post(
        "/api/rules/presentation/batch?locale=en",
        json={"references": references},
    ).json()

    assert [item["key"] for item in zh["presentations"]] == references
    assert [item["key"] for item in en["presentations"]] == references
    assert [_name(item) for item in zh["presentations"]] == ["戰士", "火球術"]
    assert [_name(item) for item in en["presentations"]] == ["Fighter", "Fireball"]
