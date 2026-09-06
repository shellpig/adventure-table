import type { Locale } from '../../i18n/locale'

export const ROOM_ERROR_CODES = [
  'room_not_found',
  'room_access_required',
  'room_access_denied',
  'room_access_throttled',
  'room_access_revoked',
  'room_scope_mismatch',
] as const

export type RoomErrorCode = (typeof ROOM_ERROR_CODES)[number]

const COPY = {
  en: {
    eyebrow: 'P2 · Room workspace',
    title: 'Start at the table',
    description: 'Create a Room for a new table, or enter an existing Room with its code and password.',
    createTitle: 'Create Room',
    roomName: 'Room name',
    password: 'Room password',
    displayName: 'Display name (optional)',
    createAction: 'Create Room',
    enterTitle: 'Enter Room',
    roomCode: 'Room code',
    elevatedKey: 'DM / Owner key (optional)',
    enterAction: 'Enter Room',
    recentTitle: 'Recent Rooms',
    continueAction: 'Open Room',
    createdTitle: 'Room created',
    createdDescription: 'Save these elevated keys now. Adventure Table will not store or show the raw keys again.',
    ownerKey: 'Owner key',
    dmKey: 'DM key',
    roomCodeLabel: 'Room code',
    requestError: 'Room request failed.',
    workspaceEyebrow: 'Room workspace',
    workspaceLoading: 'Opening Room…',
    workspaceMissing: 'This browser does not have an access token for this Room. Enter the Room again from the homepage.',
    workspaceError: 'Room access could not be verified. Enter the Room again if your access expired.',
    workspacePlaceholder: 'This Room is ready. Character workspace arrives in P2-B.',
    authority: 'Room authority',
    backHome: 'Back to Room entry',
  },
  'zh-TW': {
    eyebrow: 'P2 · Room 工作區',
    title: '先進入跑團房間',
    description: '建立新的 Room，或使用房號與密碼進入既有 Room。',
    createTitle: '建立 Room',
    roomName: 'Room 名稱',
    password: 'Room 密碼',
    displayName: '顯示名稱（選填）',
    createAction: '建立 Room',
    enterTitle: '進入 Room',
    roomCode: 'Room 房號',
    elevatedKey: 'DM / Owner Key（選填）',
    enterAction: '進入 Room',
    recentTitle: '最近使用的 Rooms',
    continueAction: '開啟 Room',
    createdTitle: 'Room 已建立',
    createdDescription: '請現在保存以下進階 Key。Adventure Table 不會保存或再次顯示這些原始 Key。',
    ownerKey: 'Owner Key',
    dmKey: 'DM Key',
    roomCodeLabel: 'Room 房號',
    requestError: 'Room 請求失敗。',
    workspaceEyebrow: 'Room 工作區',
    workspaceLoading: '正在開啟 Room…',
    workspaceMissing: '這個瀏覽器沒有此 Room 的存取權杖，請回首頁重新進入 Room。',
    workspaceError: '無法驗證 Room 存取權限；如果權限已失效，請重新進入 Room。',
    workspacePlaceholder: '這個 Room 已可使用；角色工作區會在 P2-B 加入。',
    authority: 'Room 權限',
    backHome: '回 Room 入口',
  },
} as const satisfies Record<Locale, Record<string, string>>

const ERROR_COPY = {
  en: {
    room_not_found: 'Room not found.',
    room_access_required: 'Room access is required. Enter the Room again.',
    room_access_denied: 'The Room password or elevated key is incorrect.',
    room_access_throttled: 'Too many failed Room access attempts. Try again later.',
    room_access_revoked: 'This Room access has been revoked. Enter the Room again.',
    room_scope_mismatch: 'This access token belongs to a different Room. Enter this Room again.',
  },
  'zh-TW': {
    room_not_found: '找不到此 Room。',
    room_access_required: '需要 Room 存取權限，請重新進入 Room。',
    room_access_denied: 'Room 密碼或進階 Key 不正確。',
    room_access_throttled: 'Room 存取失敗次數過多，請稍後再試。',
    room_access_revoked: '此 Room 存取權限已撤銷，請重新進入 Room。',
    room_scope_mismatch: '此存取權杖屬於另一個 Room，請重新進入目前的 Room。',
  },
} as const satisfies Record<Locale, Record<RoomErrorCode, string>>

export type RoomCopy = (typeof COPY)[Locale]

export function roomCopy(locale: Locale): RoomCopy {
  return COPY[locale]
}

export function roomErrorMessage(locale: Locale, code: string): string {
  if ((ROOM_ERROR_CODES as readonly string[]).includes(code)) {
    return ERROR_COPY[locale][code as RoomErrorCode]
  }
  return COPY[locale].requestError
}
