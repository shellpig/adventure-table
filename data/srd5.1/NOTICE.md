# SRD 5.1 attribution

Contains material from the System Reference Document 5.1 ("SRD 5.1") by Wizards of the Coast LLC. SRD 5.1 is used under CC BY 4.0.

- SRD source: https://www.dndbeyond.com/srd
- CC BY 4.0: https://creativecommons.org/licenses/by/4.0/legalcode
- Structured extraction source: https://github.com/5e-bits/5e-database @ ce47a18dfeb3e41a1b2a2dfe00a25761c3c3a4f1
- Extraction project license: MIT. Copyright 2018-2020 Adrian Padua, Christopher Ward.
- Extraction license text: https://github.com/5e-bits/5e-database/blob/ce47a18dfeb3e41a1b2a2dfe00a25761c3c3a4f1/LICENSE.md

The Adventure Table normalization adds stable keys and source metadata. Monster and Beast stat blocks are intentionally not vendored in P0.

## Traditional Chinese translation / adaptation (M02)

This project distributes a Traditional Chinese (`zh-TW`) translation of part of SRD 5.1. Translations are adaptations of CC BY 4.0 material, and the SRD 5.1 material in this repository has therefore been **modified**.

- Translated by the Adventure Table project, 2026.
- Scope: the user-visible presentation text listed as required in `data/localization/localizable-fields.json`, plus the canonical `data.desc.*` text of SRD spells, class / subclass features and conditions.
- Files: `data/srd5.1/locales/zh-TW/`. Canonical English content under `data/srd5.1/` is unmodified; translations are stored as a separate overlay keyed by stable key and field path.
- Coverage at M02 closeout: 1,635 stable keys / 3,391 presentation fields.

**This is not a complete translation of SRD 5.1.** Content that is not currently user-visible in this application — including large parts of the item and background long-form text, and all Monster / Beast material (which is not vendored here at all) — remains untranslated. Terminology follows `data/localization/dnd5e-2014-glossary.json`.

Wizards of the Coast has not endorsed or approved this translation.
