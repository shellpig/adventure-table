import type { Locale } from './locale'

const SEAT_REQUEST_CODE_MESSAGES: Record<string, Record<Locale, string>> = {
  seat_not_found: {
    'zh-TW': '找不到這個席位，或它不屬於目前的戰役。',
    en: 'This Seat could not be found in the current Campaign.',
  },
  lobby_unavailable: {
    'zh-TW': '目前的戰役／Lobby 狀態無法執行這個席位操作。',
    en: 'The current Campaign or Lobby state does not allow this Seat operation.',
  },
  seat_controller_invalid: {
    'zh-TW': '目前的席位 Controller 設定無法套用。',
    en: 'The requested Seat Controller assignment is not valid.',
  },
  seat_character_invalid: {
    'zh-TW': '這個角色目前不能指派到此玩家席位。',
    en: 'This Character cannot currently be assigned to the Player Seat.',
  },
  seat_history_referenced: {
    'zh-TW': '這個席位已被跑團歷史紀錄引用，不能永久刪除；可以改用封存。',
    en: 'This Seat is referenced by Session history and cannot be permanently deleted. Archive it instead.',
  },
  seat_management_authority_required: {
    'zh-TW': '只有房間 Owner 或 DM 可以管理這個席位。',
    en: 'Only the Room Owner or a DM may manage this Seat.',
  },
  room_owner_required: {
    'zh-TW': '只有房間 Owner 可以管理 DM 席位。',
    en: 'Only the Room Owner may manage the DM Seat.',
  },
  seat_controller_required: {
    'zh-TW': '你只能操作目前由自己控制的 Human 玩家席位。',
    en: 'You may operate only the Human Player Seat you currently control.',
  },
}

export function localizedSeatRequestMessage(
  code: string | undefined,
  status: number,
  originalMessage: string,
  locale: Locale,
): string {
  if (code && SEAT_REQUEST_CODE_MESSAGES[code]) return SEAT_REQUEST_CODE_MESSAGES[code][locale]
  if (locale === 'en') return originalMessage || `Seat request failed (${status})`
  return `席位請求失敗（HTTP ${status}），請稍後再試。`
}
