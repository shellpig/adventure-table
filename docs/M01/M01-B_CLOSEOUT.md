# M01-B Closeout Checklist

Automated implementation scope:

- [x] PHB 2014 content pack enabled explicitly beside SRD 5.1.
- [x] 13 core PHB backgrounds + 5 official variants normalized.
- [x] Wood Elf, Drow, Mountain Dwarf, Stout Halfling, Forest Gnome normalized as cross-source subraces.
- [x] Variant Human represented as a complete `race` identity.
- [x] Origin ability / skill / language / feat choices compile into immutable Build data.
- [x] Racial feature spell access uses race-origin source identity and character-level gates.
- [x] Background starting equipment stays on the P1 equipment path.
- [x] Background roleplay editor is optional and preserves manual text.
- [x] Full regression CI green — `P1 Full Regression` #475 (`33297019620`), 173 backend tests, 12 Vitest tests, 15 Playwright tests, migrations and restart persistence all passed.

## Mandatory Human Gate

The M01 testing guide requires six real browser creation flows and explicitly says this gate cannot be replaced by Playwright. Do not mark M01-B closed until the human tester completes:

1. Pure SRD regression.
2. PHB missing subrace (Wood Elf or Drow).
3. Variant Human (+1/+1 distinct abilities, skill, feat).
4. PHB Background with tool/language choice.
5. Martial character.
6. Caster with origin/racial spell interaction.

Each flow must reach Confirm, Character Sheet, and browser reload. Blocker and Major UX findings must be fixed and the affected flow rerun before closeout.
