"""Generate the P5-G E2E caster export from the real Builder and export endpoints.

The P5-G browser journeys need a Player Character who can cast an AoE spell.
The committed M03-B fixtures have no such character (the legacy fighter/wizard
predates spellcasting profiles), so this script builds a Wizard 5 (Evocation)
through the Builder HTTP flow, prepares Fireball through the same
``PATCH /api/characters/{id}/state`` the Character Sheet uses, and writes the
``GET /api/characters/{id}/export`` output with the M03-B placeholders.

Usage:
    python tests/generate_p5g_e2e_caster.py
"""

from __future__ import annotations

from pathlib import Path

import generate_m03b_fixtures as G
import m01k_support as S


OUTPUT = Path(__file__).resolve().parent / "data" / "p5g" / "fixture_wizard5_fireball.json"
FIREBALL = "srd5.1:spell:fireball"

# Wizard needs INT first; DEX/CON keep a level-5 caster alive in a journey.
WIZARD_ARRAY = {
    "strength": 8,
    "dexterity": 14,
    "constitution": 13,
    "intelligence": 15,
    "wisdom": 12,
    "charisma": 10,
}


def build_caster() -> dict:
    client, engine = S.seed_http()
    try:
        levels = [
            G._level(
                level,
                "srd5.1:class:wizard",
                hp=6 if level == 1 else 4,
                subclass_ref="srd5.1:subclass:evocation" if level == 2 else None,
            )
            for level in range(1, 6)
        ]
        view = S.http_create_draft(
            client,
            G._draft_payload(
                name="P5-G Caster",
                race="srd5.1:race:human",
                background="srd5.1:background:acolyte",
                abilities=WIZARD_ARRAY,
                levels=levels,
            ),
        )
        view = S.http_fill_generic(client, view)
        review = client.get(f"/api/character-builder/drafts/{view['draft']['id']}/review")
        assert review.status_code == 200, review.text
        (profile,) = review.json()["resolved_summary"]["spellcasting_profiles"]
        options = profile["available_spells"]
        cantrips = [o["spell_key"] for o in options if o["level"] == 0][: profile["cantrip_count"]]
        others = [o["spell_key"] for o in options if o["level"] >= 1 and o["spell_key"] != FIREBALL]
        spellbook = [FIREBALL, *others[: profile["spellbook_count"] - 1]]
        view = S.http_patch(
            client,
            view,
            {
                "spell_choices": {
                    profile["profile_id"]: {
                        "cantrip_keys": cantrips,
                        "known_spell_keys": [],
                        "spellbook_spell_keys": spellbook,
                    }
                }
            },
        )
        view = S.http_fill_equipment(client, view)
        character_id = S.http_confirm(client, view)["character_id"]

        document = G._export(client, character_id)
        (access,) = [
            entry
            for entry in document["payload"]["versions"][-1]["build_payload"]["spell_access_entries"]
            if entry["spell_key"] == FIREBALL
        ]
        prepared = client.patch(
            f"/api/characters/{character_id}/state",
            json={
                "prepared_spells": [
                    {
                        "spell_key": FIREBALL,
                        "source_profile_id": profile["profile_id"],
                        "source_access_entry_id": access["entry_id"],
                    }
                ]
            },
        )
        assert prepared.status_code == 200, prepared.text
        return G._canonicalize(G._export(client, character_id))
    finally:
        engine.dispose()


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(G._serialize(build_caster()), encoding="utf-8")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
