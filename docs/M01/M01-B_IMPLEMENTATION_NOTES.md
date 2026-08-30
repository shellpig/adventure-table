# M01-B Implementation Invariants

- PHB subraces reference the full SRD parent race StableKey; base-race grants are not copied into the PHB entries.
- Variant Human is `phb2014:race:variant-human`, not a subrace and not a `race-variant`.
- `variant_of` is provenance only and must not cause mechanical inheritance.
- Racial spells are granted by racial feature identity and do not consume normal class spell slots.
- Roleplay suggestions are optional input helpers, never structural validation requirements.
