import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { type BuilderView } from '../../api/characterBuilder'
import { SpellcastingStep } from './SpellcastingStep'


function spellView(): BuilderView {
  return {
    draft: {
      id: '11111111-1111-4111-8111-111111111111',
      mode: 'create',
      revision: 4,
      draft_payload: {
        spell_choices: {
          'class:wizard': {
            cantrip_keys: ['srd5.1:spell:fire-bolt'],
            spellbook_spell_keys: ['srd5.1:spell:magic-missile'],
            prepared_spell_keys: ['srd5.1:spell:magic-missile'],
          },
          'class:warlock': {
            cantrip_keys: ['srd5.1:spell:eldritch-blast'],
            known_spell_keys: ['srd5.1:spell:hex'],
          },
        },
      },
      created_at: '2026-08-30T00:00:00Z',
      updated_at: '2026-08-30T00:00:00Z',
    },
    resolved_summary: {
      name: 'Arcane Rail',
      target_level: 4,
      selected_reference_count: 0,
      choice_selection_count: 0,
      grants: [],
      ability_scores: [],
      progression: [],
      spellcasting_profiles: [
        {
          profile_id: 'class:wizard',
          source_type: 'class',
          source_key: 'srd5.1:class:wizard',
          source_name: 'Wizard',
          class_ref: 'srd5.1:class:wizard',
          ability: 'intelligence',
          access_model: 'spellbook',
          class_level: 1,
          max_spell_level: 1,
          cantrip_count: 3,
          known_spell_count: 0,
          spellbook_count: 6,
          prepared_limit: 4,
          resource_pool_type: 'normal_multiclass_slots',
          available_spells: [
            { spell_key: 'srd5.1:spell:fire-bolt', name: 'Fire Bolt · System Reference Document 5.1', level: 0 },
            { spell_key: 'srd5.1:spell:magic-missile', name: 'Magic Missile · System Reference Document 5.1', level: 1 },
            { spell_key: 'srd5.1:spell:shield', name: 'Shield', level: 1 },
          ],
          selected_cantrip_keys: ['srd5.1:spell:fire-bolt'],
          selected_known_spell_keys: [],
          selected_spellbook_spell_keys: ['srd5.1:spell:magic-missile'],
          selected_prepared_spell_keys: ['srd5.1:spell:magic-missile'],
        },
        {
          profile_id: 'class:warlock',
          source_type: 'class',
          source_key: 'srd5.1:class:warlock',
          source_name: 'Warlock',
          class_ref: 'srd5.1:class:warlock',
          ability: 'charisma',
          access_model: 'known',
          class_level: 3,
          max_spell_level: 2,
          cantrip_count: 2,
          known_spell_count: 4,
          spellbook_count: 0,
          prepared_limit: null,
          resource_pool_type: 'pact_magic',
          available_spells: [
            { spell_key: 'srd5.1:spell:eldritch-blast', name: 'Eldritch Blast', level: 0 },
            { spell_key: 'srd5.1:spell:hex', name: 'Hex', level: 1 },
          ],
          selected_cantrip_keys: ['srd5.1:spell:eldritch-blast'],
          selected_known_spell_keys: ['srd5.1:spell:hex'],
          selected_spellbook_spell_keys: [],
          selected_prepared_spell_keys: [],
        },
      ],
      spell_resource_pools: [
        {
          pool_id: 'spell_slots:combined',
          pool_type: 'normal_multiclass_slots',
          slots: [{ level: 1, count: 2 }],
        },
        {
          pool_id: 'pact_magic:srd5.1:class:warlock',
          pool_type: 'pact_magic',
          source_profile_id: 'class:warlock',
          slots: [{ level: 2, count: 2 }],
        },
      ],
    },
    choices: [],
    validation: { issues: [], can_confirm: false, non_standard_count: 0 },
  }
}

describe('P1-E SpellcastingStep', () => {
  it('renders source-aware Wizard and Warlock access with separate resource pools', () => {
    const html = renderToStaticMarkup(
      <SpellcastingStep view={spellView()} disabled={false} onSave={() => undefined} />,
    )

    expect(html).toContain('Spellcasting &amp; resources')
    expect(html).toContain('Combined spell slots')
    expect(html).toContain('Pact Magic')
    expect(html).toContain('Wizard 1')
    expect(html).toContain('Spellbook')
    expect(html).toContain('Initial prepared spells')
    expect(html).toContain('Magic Missile')
    expect(html).toContain('Warlock 3')
    expect(html).toContain('Known spells')
    expect(html).toContain('Hex')
    expect(html).toContain('×2')
    expect(html).not.toContain('System Reference Document 5.1')
  })
})
