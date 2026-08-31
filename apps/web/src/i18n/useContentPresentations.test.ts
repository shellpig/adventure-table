import { describe, expect, it } from 'vitest'

import {
  groupPresentationRequests,
  localizedContentLabel,
} from './useContentPresentations'

describe('localizedContentLabel', () => {
  it('preserves counted-reference bonuses', () => {
    expect(localizedContentLabel('力量', 'STR +2')).toBe('力量 +2')
  })

  it('keeps source disambiguation without reintroducing English source prose', () => {
    expect(
      localizedContentLabel(
        '火焰箭',
        'Fire Bolt · System Reference Document 5.1',
      ),
    ).toBe('火焰箭 · SRD 5.1')
  })

  it('does not duplicate an existing mechanics suffix', () => {
    expect(localizedContentLabel('力量 +1', 'STR +1')).toBe('力量 +1')
  })

  it('preserves trailing multiplication counts', () => {
    expect(localizedContentLabel('治療藥水', 'Potion of Healing ×2')).toBe('治療藥水 ×2')
  })

  it('preserves the counted-reference prefix emitted by structural choices', () => {
    expect(
      localizedContentLabel(
        '標槍',
        '2 × Javelin · System Reference Document 5.1',
      ),
    ).toBe('2 × 標槍 · SRD 5.1')
  })
})

describe('groupPresentationRequests', () => {
  it('asks for name only when no reference needs an extra field', () => {
    expect(
      groupPresentationRequests(
        ['srd5.1:language:common', 'srd5.1:proficiency:skill-history'],
        {},
      ),
    ).toEqual([
      {
        fields: ['name'],
        references: ['srd5.1:language:common', 'srd5.1:proficiency:skill-history'],
      },
    ])
  })

  it('keeps an extra field off references that do not declare it', () => {
    // The batch endpoint rejects the whole request when any reference lacks a
    // requested field, so a single combined request would lose every name.
    const groups = groupPresentationRequests(
      ['srd5.1:language:common', 'phb2014:background:noble'],
      { 'phb2014:background:noble': ['data.feature.name'] },
    )

    expect(groups).toHaveLength(2)
    expect(groups).toContainEqual({
      fields: ['name'],
      references: ['srd5.1:language:common'],
    })
    expect(groups).toContainEqual({
      fields: ['data.feature.name', 'name'],
      references: ['phb2014:background:noble'],
    })
  })

  it('groups references that share a field set into one request', () => {
    const groups = groupPresentationRequests(
      ['phb2014:background:noble', 'srd5.1:background:acolyte'],
      {
        'phb2014:background:noble': ['data.feature.name'],
        'srd5.1:background:acolyte': ['data.feature.name'],
      },
    )

    expect(groups).toEqual([
      {
        fields: ['data.feature.name', 'name'],
        references: ['phb2014:background:noble', 'srd5.1:background:acolyte'],
      },
    ])
  })

  it('drops blank references and de-duplicates', () => {
    expect(
      groupPresentationRequests(['srd5.1:skill:athletics', '', 'srd5.1:skill:athletics'], {}),
    ).toEqual([{ fields: ['name'], references: ['srd5.1:skill:athletics'] }])
  })
})
