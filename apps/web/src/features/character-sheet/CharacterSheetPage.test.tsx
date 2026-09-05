import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { CharacterSheetDTO, ContentEntry } from '../../api/character'
import { LocaleProvider } from '../../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type LocaleStorage } from '../../i18n/locale'
import { CharacterSheetView } from './CharacterSheetPage'

function englishStorage(): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? 'en' : null),
    setItem: () => undefined,
  }
}

function renderSheet(
  props: Omit<Parameters<typeof CharacterSheetView>[0], 'sheet'> = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <LocaleProvider storage={englishStorage()} documentTarget={null}>
        <CharacterSheetView sheet={sheet} {...props} />
      </LocaleProvider>
    </QueryClientProvider>,
  )
}

const sheet: CharacterSheetDTO = {
  character_id: '00000000-0000-4000-8000-0000000000e0', current_version_id: '00000000-0000-4000-8000-0000000000e1', name: 'P0 Human Fighter 5 / Wizard 5', ruleset: 'dnd5e-2014', version_no: 1, total_level: 10,
  classes: [
    { class_ref: 'srd5.1:class:fighter', name: 'Fighter', level: 5 },
    { class_ref: 'srd5.1:class:wizard', name: 'Wizard', level: 5 },
  ],
  proficiency_bonus: 4,
  abilities: {
    strength: { score: 16, modifier: 3 }, dexterity: { score: 14, modifier: 2 }, constitution: { score: 14, modifier: 2 }, intelligence: { score: 16, modifier: 3 }, wisdom: { score: 10, modifier: 0 }, charisma: { score: 8, modifier: -1 },
  },
  saving_throws: { strength: 7, dexterity: 2, constitution: 6, intelligence: 3, wisdom: 0, charisma: -1 },
  skills: { athletics: 7, arcana: 7, perception: 4 },
  skill_proficiencies: ['athletics', 'arcana'],
  passive_perception: 14, passive_investigation: 13, initiative_modifier: 2, armor_class: 18, walking_speed: 30, swim_speed: 30, max_hp: 74, current_hp: 74, temporary_hp: 0,
  hit_dice: [{ die: 'd10', total: 5, available: 5 }, { die: 'd6', total: 5, available: 5 }],
  features: [{ key: 'srd5.1:feature:second-wind', name: 'Second Wind' }, { key: 'srd5.1:feature:arcane-recovery', name: 'Arcane Recovery' }],
  conditions: [],
  spells: [
    { entry_id: 'wizard:magic-missile', spell_key: 'srd5.1:spell:magic-missile', name: 'Magic Missile', level: 1, source_type: 'class', source_key: 'srd5.1:class:wizard', access_type: 'spellbook', prepared: true },
    { entry_id: 'wizard:detect-magic', spell_key: 'srd5.1:spell:detect-magic', name: 'Detect Magic', level: 1, source_type: 'class', source_key: 'srd5.1:class:wizard', access_type: 'spellbook', prepared: false },
    { entry_id: 'wizard:always', spell_key: 'srd5.1:spell:shield', name: 'Shield', level: 1, source_type: 'feature', source_key: 'srd5.1:feature:arcane-recovery', access_type: 'always_prepared', prepared: true },
  ],
  spellcasting: [{ source_key: 'srd5.1:class:wizard', source_name: 'Wizard', ability: 'intelligence', save_dc: 15, attack_modifier: 7 }],
  spell_slots: { '1': { used: 1, remaining: 3 }, '2': { used: 0, remaining: 3 }, '3': { used: 1, remaining: 1 } },
  resources: { 'pact_magic:srd5.1:class:warlock:slot:2': { used: 0, remaining: 2 } },
  inventory: [
    { entry_id: 'inventory:shield', item_ref: 'srd5.1:equipment:shield', name: 'Shield', quantity: 1, equipped: true, carried: true, rules: { equipment_category: { index: 'armor', name: 'Armor' }, armor_class: { base: 2 } } },
    { entry_id: 'inventory:longsword', item_ref: 'srd5.1:equipment:longsword', name: 'Longsword', quantity: 1, equipped: false, carried: true, rules: { equipment_category: { index: 'weapon', name: 'Weapon' }, damage: { damage_dice: '1d8', damage_type: { index: 'slashing', name: 'Slashing' } } } },
    { entry_id: 'inventory:healing-potion', item_ref: 'srd5.1:item:potion-of-healing-common', name: 'Potion of Healing', quantity: 2, equipped: false, carried: true, rules: {} },
  ],
  roleplay_profile: { appearance: null, biography: null, personality_traits: [], ideals: [], bonds: [], flaws: [] },
}

const conditions: ContentEntry[] = [{ key: 'srd5.1:condition:poisoned', index: 'poisoned', name: 'Poisoned', source: 'srd5.1', ruleset: 'dnd5e-2014', license: 'CC-BY-4.0', data: {} }]
const inventoryContent: ContentEntry[] = [{ key: 'srd5.1:equipment:shield', index: 'shield', name: 'Shield', source: 'srd5.1', ruleset: 'dnd5e-2014', license: 'CC-BY-4.0', data: { equipment_category: { index: 'armor', name: 'Armor' } } }]

describe('P0-E Character Sheet', () => {
  it('renders the shared header and Page 1 contract without roleplay requirements', () => {
    const html = renderSheet({ conditionContent: conditions })
    expect(html).toContain('P0 Human Fighter 5 / Wizard 5')
    expect(html).toContain('Lv. 10')
    expect(html).toContain('AC')
    expect(html).toContain('Passive Perception')
    expect(html).toContain('Movement')
    expect(html).toContain('Walk')
    expect(html).toContain('Swim')
    expect(html).toContain('30 ft')
    expect(html).toContain('d10')
    expect(html).toContain('5/5')
    expect(html).toContain('d6')
    expect(html).toContain('Second Wind')
    expect(html).toContain('Roleplay / Biography')
    expect(html).toContain('No roleplay information has been entered yet')
    expect(html).toContain('role="combobox"')
  })

  it('keeps spell access and prepared state visibly distinct without leaking raw source types', () => {
    const html = renderSheet({ initialTab: 'spells' })
    expect(html).toContain('Spellbook')
    expect(html).toContain('Prepared')
    expect(html).toContain('Unprepared')
    expect(html).toContain('Always Prepared')
    expect(html).toContain('Save DC')
    expect(html).toContain('+7')
    expect(html).toContain('Spell Slots')
    expect(html).toContain('Intelligence')
    expect(html).toContain('Level 2')
    expect(html).not.toContain('Wizard · class')
  })

  it('renders structured equipment category and damage labels with searchable add UI', () => {
    const html = renderSheet({ inventoryContent, initialTab: 'inventory' })
    expect(html).toContain('Live Inventory')
    expect(html).toContain('Potion of Healing')
    expect(html).toContain('Equipped')
    expect(html).toContain('Qty')
    expect(html).toContain('Add item')
    expect(html).toContain('Armor')
    expect(html).toContain('1d8 Slashing')
    expect(html).toContain('role="combobox"')
  })
})

describe('M03-B sheet header actions', () => {
  it('renders header actions inside the sheet hero, not as a floating overlay', () => {
    const markup = renderSheet({
      headerActions: <button type="button" aria-label="Export character JSON">Export JSON</button>,
    })
    const hero = markup.slice(
      markup.indexOf('class="character-hero"'),
      markup.indexOf('class="sheet-tabs"'),
    )
    expect(hero).toContain('character-hero__actions')
    expect(hero).toContain('aria-label="Export character JSON"')
  })

  it('omits the actions container when the page supplies none', () => {
    expect(renderSheet()).not.toContain('character-hero__actions')
  })
})
