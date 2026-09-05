import { describe, expect, it } from 'vitest'

import type { BuilderEquipmentSummary } from '../../api/characterBuilder'
import { mergeEquipmentByItem } from './EquipmentReviewStep'

function entry(
  entryId: string,
  itemRef: string,
  name: string,
  quantity: number,
): BuilderEquipmentSummary {
  return {
    entry_id: entryId,
    item_ref: itemRef,
    name,
    quantity,
    source_ref: 'tce:class:artificer',
  }
}

describe('starting equipment presentation', () => {
  it('merges repeated items into a single row with the summed quantity', () => {
    const merged = mergeEquipmentByItem([
      entry('a', 'srd5.1:equipment:crossbow-light', 'Light Crossbow', 1),
      entry('b', 'srd5.1:equipment:crossbow-bolt', 'Crossbow Bolt', 20),
      entry('c', 'srd5.1:equipment:crossbow-light', 'Light Crossbow', 1),
    ])

    expect(merged).toEqual([
      { item_ref: 'srd5.1:equipment:crossbow-light', name: 'Light Crossbow', quantity: 2 },
      { item_ref: 'srd5.1:equipment:crossbow-bolt', name: 'Crossbow Bolt', quantity: 20 },
    ])
  })

  it('keeps distinct items untouched and in first-seen order', () => {
    const merged = mergeEquipmentByItem([
      entry('a', 'srd5.1:equipment:club', 'Club', 1),
      entry('b', 'srd5.1:equipment:dagger', 'Dagger', 1),
    ])

    expect(merged.map((item) => [item.item_ref, item.quantity])).toEqual([
      ['srd5.1:equipment:club', 1],
      ['srd5.1:equipment:dagger', 1],
    ])
  })
})
