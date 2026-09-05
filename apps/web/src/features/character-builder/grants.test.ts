import { describe, expect, it } from 'vitest'

import { type BuilderGrantSummary } from '../../api/characterBuilder'
import {
  grantDisplayName,
  grantPresentationFields,
  grantPresentationReferences,
  isVisibleGrant,
  pairGrantsByKind,
  sortGrantsByKind,
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

describe('pairGrantsByKind', () => {
  const grant = (kind: string, label: string): BuilderGrantSummary => ({
    label,
    kind,
    source_ref: `srd5.1:race:${label}`,
  })

  it('puts two grants of the same kind on one row', () => {
    const rows = pairGrantsByKind([grant('language', 'a'), grant('language', 'b')])
    expect(rows).toEqual([[grant('language', 'a'), grant('language', 'b')]])
  })

  it('starts a new row when the kind changes', () => {
    const rows = pairGrantsByKind([grant('language', 'a'), grant('trait', 'b')])
    expect(rows.map((row) => row.length)).toEqual([1, 1])
  })

  it('leaves an odd kind alone on its row', () => {
    const rows = pairGrantsByKind([
      grant('language', 'a'),
      grant('language', 'b'),
      grant('language', 'c'),
      grant('trait', 'd'),
    ])
    expect(rows.map((row) => row.map((item) => item.label))).toEqual([
      ['a', 'b'],
      ['c'],
      ['d'],
    ])
  })
})

describe('isVisibleGrant and sortGrantsByKind filtering', () => {
  it('filters out lineage kind from resolved grants', () => {
    const lineageGrant: BuilderGrantSummary = {
      label: 'Dhampir',
      kind: 'lineage',
      source_ref: 'vrgr:lineage:dhampir',
      reference_id: 'vrgr:lineage:dhampir',
    }
    const featureGrant: BuilderGrantSummary = {
      label: 'Spider Climb',
      kind: 'feature',
      source_ref: 'vrgr:lineage:dhampir',
      reference_id: 'vrgr:feature:spider-climb',
    }
    expect(isVisibleGrant(lineageGrant)).toBe(false)
    expect(isVisibleGrant(featureGrant)).toBe(true)
    const sorted = sortGrantsByKind([lineageGrant, featureGrant])
    expect(sorted).toEqual([featureGrant])
  })
})
