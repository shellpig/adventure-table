import { describe, expect, it } from 'vitest'

import {
  P2E_SESSION_REQUEST_CODES,
  P3B_SESSION_REQUEST_CODES,
  P3C_SESSION_REQUEST_CODES,
  P4E_SESSION_REQUEST_CODES,
  SESSION_REQUEST_CODES,
  SESSION_REQUEST_CODE_MESSAGES,
  localizedSessionRequestMessage,
} from './sessionMessages'

describe('Session request message SSOT', () => {
  for (const locale of ['en', 'zh-TW'] as const) {
    it(`covers every stable Session error code in ${locale}`, () => {
      const messages = SESSION_REQUEST_CODES.map(
        (code) => SESSION_REQUEST_CODE_MESSAGES[code][locale],
      )

      expect(new Set(messages).size).toBe(SESSION_REQUEST_CODES.length)
      for (const [index, code] of SESSION_REQUEST_CODES.entries()) {
        expect(messages[index]).not.toContain(code)
        expect(messages[index].trim()).not.toBe('')
      }
    })
  }

  it('keeps P2-E, P3-B, P3-C, and P4-E code ownership explicit', () => {
    expect(P2E_SESSION_REQUEST_CODES).toContain('session_not_active')
    expect(P3B_SESSION_REQUEST_CODES).toEqual([
      'table_actor_unauthorized',
      'exploration_subject_not_found',
      'stage_image_not_found',
      'invalid_stage_image',
      'stage_revision_conflict',
    ])
    expect(P3C_SESSION_REQUEST_CODES).toEqual([
      'validation_failed',
      'roll_request_not_found',
      'roll_request_already_resolved',
      'invalid_roll_input',
      'unknown_check_ref',
      'roll_character_not_found',
      'pending_action_not_found',
      'pending_action_invalid_transition',
      'pending_action_version_conflict',
      'pending_action_invalid_roll_binding',
      'table_state_subject_stale',
      'character_not_found',
      'character_archived',
      'stale_build_version',
      'state_write_conflict',
      'invalid_character_state',
    ])
    expect(P4E_SESSION_REQUEST_CODES).toEqual([
      'unknown_reference',
      'monster_instance_conflict',
      'combat_not_found',
      'attack_not_found',
      'combat_roll_not_found',
      'combat_target_not_found',
      'active_combat_exists',
      'combat_state_conflict',
      'initiative_request_not_found',
      'invalid_initiative_input',
      'invalid_attack_definition',
      'invalid_combat_input',
      'special_attack_not_found',
    ])
  })

  it('localizes Stage revision conflicts in both supported locales', () => {
    expect(localizedSessionRequestMessage('stage_revision_conflict', 409, 'raw', 'zh-TW')).toContain('舞台')
    expect(localizedSessionRequestMessage('stage_revision_conflict', 409, 'raw', 'en')).toContain('Stage')
  })

  it('localizes framework request validation for P3-C Session forms', () => {
    expect(localizedSessionRequestMessage('validation_failed', 422, 'raw', 'zh-TW')).toContain('輸入')
    expect(localizedSessionRequestMessage('validation_failed', 422, 'raw', 'en')).toContain('invalid')
  })

  it('localizes P3-C roll, PendingAction, and state failures in both locales', () => {
    expect(localizedSessionRequestMessage('invalid_roll_input', 422, 'raw', 'zh-TW')).toContain('擲骰')
    expect(localizedSessionRequestMessage('invalid_roll_input', 422, 'raw', 'en')).toContain('roll')
    expect(localizedSessionRequestMessage('pending_action_version_conflict', 409, 'raw', 'zh-TW')).toContain('PendingAction')
    expect(localizedSessionRequestMessage('pending_action_version_conflict', 409, 'raw', 'en')).toContain('PendingAction')
    expect(localizedSessionRequestMessage('state_write_conflict', 409, 'raw', 'zh-TW')).toContain('角色')
    expect(localizedSessionRequestMessage('state_write_conflict', 409, 'raw', 'en')).toContain('Character')
  })

  it('localizes P4-E combat state conflicts in both locales', () => {
    expect(localizedSessionRequestMessage('combat_state_conflict', 409, 'raw server text', 'zh-TW')).toBe(
      '戰鬥狀態已變更，這個動作現在不能執行，請重新整理後再試。',
    )
    expect(localizedSessionRequestMessage('combat_state_conflict', 409, 'raw server text', 'en')).toBe(
      'Combat state changed and this action is no longer allowed. Refresh and try again.',
    )
  })

  it('falls back without exposing an unknown raw code', () => {
    expect(localizedSessionRequestMessage('session_future_error', 500, 'server detail', 'en')).toBe(
      'server detail',
    )
    expect(localizedSessionRequestMessage('session_future_error', 500, 'server detail', 'zh-TW')).toBe(
      '跑團請求失敗（HTTP 500），請稍後再試。',
    )
  })
})
