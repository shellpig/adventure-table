import type { Locale } from './locale'

export const P2A_ROOM_REQUEST_CODES = [
  'room_not_found',
  'room_access_required',
  'room_access_denied',
  'room_access_throttled',
  'room_access_revoked',
  'room_scope_mismatch',
] as const

export type P2ARoomRequestCode = (typeof P2A_ROOM_REQUEST_CODES)[number]

export const ROOM_REQUEST_CODE_MESSAGES: Record<P2ARoomRequestCode, Record<Locale, string>> = {
  room_not_found: {
    'zh-TW': '找不到此 Room。',
    en: 'Room not found.',
  },
  room_access_required: {
    'zh-TW': '需要 Room 存取權限，請重新進入 Room。',
    en: 'Room access is required. Enter the Room again.',
  },
  room_access_denied: {
    'zh-TW': 'Room 密碼或進階 Key 不正確。',
    en: 'The Room password or elevated key is incorrect.',
  },
  room_access_throttled: {
    'zh-TW': 'Room 存取失敗次數過多，請稍後再試。',
    en: 'Too many failed Room access attempts. Try again later.',
  },
  room_access_revoked: {
    'zh-TW': '此 Room 存取權限已撤銷，請重新進入 Room。',
    en: 'This Room access has been revoked. Enter the Room again.',
  },
  room_scope_mismatch: {
    'zh-TW': '此存取權杖屬於另一個 Room，請重新進入目前的 Room。',
    en: 'This access token belongs to a different Room. Enter this Room again.',
  },
}

export function localizedRoomRequestMessage(
  code: string | undefined,
  status: number,
  originalMessage: string,
  locale: Locale,
): string {
  if (code && code in ROOM_REQUEST_CODE_MESSAGES) {
    return ROOM_REQUEST_CODE_MESSAGES[code as P2ARoomRequestCode][locale]
  }
  if (locale === 'en') return originalMessage || `Room request failed (${status})`
  return `Room 請求失敗（HTTP ${status}），請稍後再試。`
}
