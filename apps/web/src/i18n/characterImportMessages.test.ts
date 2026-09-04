import { describe, expect, it } from 'vitest'

import {
  CHARACTER_IMPORT_REQUEST_CODE_MESSAGES,
  localizedCharacterImportRequestMessage,
} from './characterImportMessages'

const CODES = [
  'invalid_envelope_shape',
  'invalid_payload_shape',
  'unsupported_schema_status',
  'unsupported_ruleset',
  'ruleset_mismatch',
  'version_chain_gap',
  'version_chain_out_of_order',
  'current_state_version_missing',
  'version_lineage_invalid',
  'version_lineage_self_reference',
  'version_lineage_direction_invalid',
  'version_lineage_cycle',
  'invalid_version_kind',
  'invalid_build_shape',
  'invalid_builder_provenance',
  'state_shape_invalid',
  'build_references_invalid',
  'state_inconsistent_with_build',
  'draft_reconstruction_unavailable',
  'payload_too_large',
] as const

describe('M03-C import rejection localization', () => {
  it('has an English and zh-TW message for every machine code', () => {
    expect(Object.keys(CHARACTER_IMPORT_REQUEST_CODE_MESSAGES).sort()).toEqual([...CODES].sort())
    for (const code of CODES) {
      expect(CHARACTER_IMPORT_REQUEST_CODE_MESSAGES[code].en.trim()).not.toBe('')
      expect(CHARACTER_IMPORT_REQUEST_CODE_MESSAGES[code]['zh-TW'].trim()).not.toBe('')
    }
  })

  it('does not expose raw backend validation dumps for known import codes', () => {
    const raw = '3 validation errors for CharacterExport\npayload.versions.0...'
    expect(localizedCharacterImportRequestMessage('invalid_builder_provenance', 400, raw, 'en')).not.toContain(
      'validation errors',
    )
    expect(localizedCharacterImportRequestMessage('invalid_builder_provenance', 400, raw, 'zh-TW')).not.toContain(
      'HTTP 400',
    )
  })
})
