import type { Locale } from './locale'

export const P2E_SESSION_REQUEST_CODES = [
  'session_not_found',
  'session_already_active',
  'character_already_in_active_session',
  'dm_controller_mismatch',
  'session_not_active',
  'session_active_character_locked',
  'seat_character_invalid',
  'lobby_unavailable',
] as const

export type P2ESessionRequestCode = (typeof P2E_SESSION_REQUEST_CODES)[number]

export const SESSION_REQUEST_CODE_MESSAGES: Record<P2ESessionRequestCode, Record<Locale, string>> = {
  session_not_found: {
    'zh-TW': '找不到這場 Session。',
    en: 'Session not found.',
  },
  session_already_active: {
    'zh-TW': '這個 Campaign 已經有進行中的 Session。',
    en: 'This Campaign already has an active Session.',
  },
  character_already_in_active_session: {
    'zh-TW': '至少一名所選角色已在另一個進行中的 Session。',
    en: 'At least one selected Character is already in another active Session.',
  },
  dm_controller_mismatch: {
    'zh-TW': '只有本場固定的 current DM Controller 可以執行此操作。',
    en: 'Only this Session’s fixed current DM Controller may perform this operation.',
  },
  session_not_active: {
    'zh-TW': '這場 Session 已不再是進行中狀態。',
    en: 'This Session is no longer active.',
  },
  session_active_character_locked: {
    'zh-TW': 'Session 開始後，參與者的 Active Character 不能更換。',
    en: 'A participant’s Active Character cannot be changed after the Session starts.',
  },
  seat_character_invalid: {
    'zh-TW': '這個 Player Seat 目前無法加入 Session。',
    en: 'This Player Seat cannot join the Session right now.',
  },
  lobby_unavailable: {
    'zh-TW': '目前的 Campaign／Lobby 狀態無法執行此 Session 操作。',
    en: 'The current Campaign or Lobby state does not allow this Session operation.',
  },
}

export function localizedSessionRequestMessage(
  code: string | undefined,
  status: number,
  originalMessage: string,
  locale: Locale,
): string {
  if (code && code in SESSION_REQUEST_CODE_MESSAGES) {
    return SESSION_REQUEST_CODE_MESSAGES[code as P2ESessionRequestCode][locale]
  }
  if (locale === 'en') return originalMessage || `Session request failed (${status})`
  return `Session 請求失敗（HTTP ${status}），請稍後再試。`
}
