import { describe, expect, it } from 'vitest'

import {
  createLocalizedRequestError,
  installDynamicLocalizedBuilderPayload,
  localizedBuilderIssueMessage,
  localizedDisabledReason,
  localizedRequestErrorMessage,
} from './systemMessages'

describe('M02-G/H system-owned messages', () => {
  it('keeps machine validation identity stable while presentation is localized explicitly', () => {
    const issue = installDynamicLocalizedBuilderPayload({
      code: 'missing_race',
      severity: 'blocking_error',
      path: 'draft_payload.race_selection',
      message: 'Race selection is required before Confirm.',
      message_params: {},
      related_refs: [],
    })

    expect(issue.code).toBe('missing_race')
    expect(issue.path).toBe('draft_payload.race_selection')
    expect(
      localizedBuilderIssueMessage(issue.code, 'Race selection is required before Confirm.', 'zh-TW'),
    ).toBe('確認角色前必須選擇種族。')
    expect(
      localizedBuilderIssueMessage(issue.code, 'Race selection is required before Confirm.', 'en'),
    ).toBe('Race selection is required before Confirm.')
  })

  it('covers common blocking issue codes that previously leaked canonical English', () => {
    const cases = [
      ['multiclass_prerequisite_not_met', 'Wizard: Requires INT 13+ to multiclass.'],
      ['subclass_selected_too_early', 'Subclass selected too early.'],
      ['missing_subclass_at_timing', 'Subclass selection is required.'],
      ['duplicate_choice_option', 'Duplicate choice option.'],
      ['stale_build_version', 'Build version is stale.'],
      ['invalid_manual_hp_roll', 'Manual HP roll is invalid.'],
    ] as const

    for (const [code, original] of cases) {
      const localized = localizedBuilderIssueMessage(code, original, 'zh-TW')
      expect(localized).not.toContain(original)
      expect(localized).not.toMatch(/Wizard|Subclass|Duplicate|Build version|Manual HP/)
    }
  })

  it('covers the remaining Level Up guard and build-failure codes in both locales', () => {
    const cases = [
      ['invalid_version_target_level', 'level_up must target Character Level 6; got 7.'],
      ['level_up_origin_changed', 'Level Up cannot rewrite race/background/alignment; use Build Edit or Correction.'],
      ['level_up_historical_progression_changed', 'Level Up cannot rewrite class choices from the base Build.'],
      ['level_up_historical_hp_changed', 'Level Up cannot rewrite historical HP progression from the base Build.'],
      ['level_up_starting_equipment_changed', 'Level Up must preserve immutable starting-equipment provenance.'],
      ['level_up_numeric_override_changed', 'Numeric Overrides are not a Level Up choice; use Build Edit or Correction.'],
      ['build_candidate_missing', 'The server could not compile a final CharacterBuild from this draft.'],
      ['initial_state_missing', 'The server could not build initial Current State.'],
      ['final_character_validation_failed', 'Character level 1 must use the starting class maximum hit die.'],
    ] as const

    for (const [code, original] of cases) {
      const localized = localizedBuilderIssueMessage(code, original, 'zh-TW')
      expect(localized).not.toContain(original)
      expect(localized).not.toMatch(/[A-Za-z]/)
      expect(localized).not.toBe('目前的角色資料有一項需要修正的規則問題。')
      expect(localizedBuilderIssueMessage(code, original, 'en')).toMatch(/[A-Za-z]/)
    }
  })

  it('formats structured multiclass prerequisites without parsing canonical English prose', () => {
    const params = {
      class_ref: 'srd5.1:class:wizard',
      requirements: [{ ability: 'intelligence', minimum_score: 13 }],
      requirement_groups: [
        {
          choose: 1,
          options: [
            { ability: 'strength', minimum_score: 13 },
            { ability: 'dexterity', minimum_score: 13 },
          ],
        },
      ],
    }

    expect(
      localizedDisabledReason(
        'Wizard: Requires INT 13+ to multiclass.',
        'zh-TW',
        'multiclass_prerequisite_not_met',
        params,
      ),
    ).toBe('兼職需要符合：智力 13+；力量 13+ 或 敏捷 13+。')
    expect(
      localizedDisabledReason(
        'Wizard: Requires INT 13+ to multiclass.',
        'en',
        'multiclass_prerequisite_not_met',
        params,
      ),
    ).toBe('Requires Intelligence 13+; Strength 13+ or Dexterity 13+ to multiclass.')
  })

  it('formats structured feat and ASI prerequisites in both locales', () => {
    const featParams = {
      feat_ref: 'phb2014:feat:example',
      requirements: [
        { ability: 'strength', minimum_score: 13 },
        { ability: 'wisdom', minimum_score: 13 },
      ],
    }
    expect(localizedDisabledReason('canonical', 'zh-TW', 'feat_prerequisite_not_met', featParams)).toBe(
      '此專長需要符合：力量 13+；感知 13+。',
    )
    expect(localizedDisabledReason('canonical', 'en', 'feat_prerequisite_not_met', featParams)).toBe(
      'Requires Strength 13+; Wisdom 13+.',
    )
    expect(localizedDisabledReason('DEX cannot exceed 20.', 'zh-TW', 'ability_score_cap_reached', {
      ability: 'dexterity', maximum: 20,
    })).toBe('敏捷 不能超過 20。')
  })

  it('keeps structured machine fields after installing dynamic getters', () => {
    const payload = installDynamicLocalizedBuilderPayload({
      choice_id: 'level:2:class-selection',
      label: 'Level 2 class',
      disabled_reason: 'Complete ability scores before multiclassing.',
      disabled_reason_code: 'multiclass_ability_scores_incomplete',
      disabled_reason_params: { class_ref: 'srd5.1:class:wizard' },
    })

    expect(payload.disabled_reason_code).toBe('multiclass_ability_scores_incomplete')
    expect(payload.disabled_reason_params).toEqual({ class_ref: 'srd5.1:class:wizard' })
    expect(payload.disabled_reason).toBe('兼職前請先完成能力值。')
  })

  it('never leaks untranslated disabled reason prose into zh-TW fallback', () => {
    const original = 'Prerequisite not met.'
    const localized = localizedDisabledReason(original, 'zh-TW')
    expect(localized).toBe('此選項目前無法選擇；請先完成相關條件。')
    expect(localized).not.toContain(original)
    expect(localizedDisabledReason(original, 'en')).toBe(original)
  })

  it('localizes spell sniper no attack cantrip disabled reason in both locales', () => {
    const payload = installDynamicLocalizedBuilderPayload({
      choice_id: 'asi:wizard:4:feat:phb2014:feat:spell-sniper:spell-source',
      option_id: 'srd5.1:class:bard',
      disabled_reason: 'This class has no cantrips that require an attack roll in 5e 2014 rules.',
      disabled_reason_code: 'feat_spell_source_no_attack_cantrip',
      disabled_reason_params: { class_ref: 'srd5.1:class:bard' },
    })

    expect(payload.disabled_reason_code).toBe('feat_spell_source_no_attack_cantrip')
    expect(localizedDisabledReason(payload.disabled_reason, 'zh-TW', payload.disabled_reason_code)).toBe(
      '此職業在 5e 2014 規則中沒有需要攻擊擲骰的戲法。',
    )
    expect(localizedDisabledReason(payload.disabled_reason, 'en', payload.disabled_reason_code)).toBe(
      'This class has no cantrips that require an attack roll in 5e 2014 rules.',
    )
  })

  it('localizes request failures without requiring a browser document', () => {
    const zhError = createLocalizedRequestError('not_found', 404, 'Draft not found', 'zh-TW')
    const enError = createLocalizedRequestError('not_found', 404, 'Draft not found', 'en')

    expect(zhError.message).toContain('找不到')
    expect(enError.message).toContain('could not be found')
    expect(localizedRequestErrorMessage(undefined, 500, 'Database unavailable', 'zh-TW')).toBe(
      '要求失敗（HTTP 500），請稍後再試。',
    )
  })

  it('uses a Chinese-only safe fallback for unknown validation codes', () => {
    expect(localizedBuilderIssueMessage('future_code', 'Future warning', 'zh-TW')).toBe(
      '目前的角色資料有一項需要修正的規則問題。',
    )
    expect(localizedBuilderIssueMessage('future_code', 'Future warning', 'en')).toBe('Future warning')
  })
})
