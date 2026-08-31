import { describe, expect, it } from 'vitest'

import { type BuilderGrantSummary } from '../../api/characterBuilder'
import {
  grantDisplayName,
  grantPresentationFields,
  grantPresentationReferences,
} from './grants'

const referenceGrant: BuilderGrantSummary = {
  label: 'Skill: History',
  kind: 'proficiency',
  source_ref: 'phb2014:background:noble',
  reference_id: 'srd5.1:proficiency:skill-history',
}

const inlineGrant: BuilderGrantSummary = {
  label: 'Position of Privilege',
  kind: 'background_feature',
  source_ref: 'phb2014:background:noble',
  reference_id: null,
  presentation_field: 'data.feature.name',
}

const nameFor = (reference: string | null | undefined, fallback = '') =>
  reference === 'srd5.1:proficiency:skill-history' ? '技能：歷史' : fallback

const fieldFor = (
  reference: string | null | undefined,
  fieldPath: string | null | undefined,
  fallback = '',
) =>
  reference === 'phb2014:background:noble' && fieldPath === 'data.feature.name'
    ? '特權階級'
    : fallback

describe('grant presentation identity', () => {
  it('asks for the source entry when the grant is an inline field', () => {
    expect(grantPresentationReferences([referenceGrant, inlineGrant])).toEqual([
      'srd5.1:proficiency:skill-history',
      'phb2014:background:noble',
    ])
  })

  it('maps each source entry to the extra field paths it needs', () => {
    expect(grantPresentationFields([referenceGrant, inlineGrant])).toEqual({
      'phb2014:background:noble': ['data.feature.name'],
    })
    expect(grantPresentationFields([referenceGrant])).toEqual({})
  })

  it('localizes an inline background feature instead of falling back to English', () => {
    expect(grantDisplayName(inlineGrant, inlineGrant.label, nameFor, fieldFor)).toBe(
      '特權階級',
    )
  })

  it('still resolves standalone entries through their own StableKey', () => {
    expect(
      grantDisplayName(referenceGrant, referenceGrant.label, nameFor, fieldFor),
    ).toBe('技能：歷史')
  })

  it('falls back to the canonical label when nothing resolves', () => {
    const unknown: BuilderGrantSummary = {
      label: 'Unlocalized',
      kind: 'feature',
      source_ref: 'phb2014:background:noble',
      reference_id: null,
    }
    expect(grantDisplayName(unknown, unknown.label, nameFor, fieldFor)).toBe(
      'Unlocalized',
    )
  })
})
