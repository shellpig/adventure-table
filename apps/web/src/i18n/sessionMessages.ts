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

export const P3B_SESSION_REQUEST_CODES = [
  'table_actor_unauthorized',
  'exploration_subject_not_found',
  'stage_image_not_found',
  'invalid_stage_image',
  'stage_revision_conflict',
] as const

export const P3C_SESSION_REQUEST_CODES = [
  'validation_failed',
  'roll_request_not_found',
  'roll_request_already_resolved',
  'invalid_roll_input',
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
] as const

export const SESSION_REQUEST_CODES = [
  ...P2E_SESSION_REQUEST_CODES,
  ...P3B_SESSION_REQUEST_CODES,
  ...P3C_SESSION_REQUEST_CODES,
] as const

export type SessionRequestCode = (typeof SESSION_REQUEST_CODES)[number]

export const SESSION_REQUEST_CODE_MESSAGES: Record<SessionRequestCode, Record<Locale, string>> = {
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
  table_actor_unauthorized: {
    'zh-TW': '你目前沒有權限執行這個桌內操作，請重新整理 Session 狀態。',
    en: 'You are no longer authorized for this table action. Refresh the Session state.',
  },
  exploration_subject_not_found: {
    'zh-TW': '選擇的 Player Seat 目前不是這場 Session 的有效角色。',
    en: 'The selected Player Seat is not an active Character in this Session.',
  },
  stage_image_not_found: {
    'zh-TW': '目前舞台使用的圖片已不存在，請重新整理舞台。',
    en: 'The current Stage image is no longer available. Refresh the Stage.',
  },
  invalid_stage_image: {
    'zh-TW': '舞台圖片格式或內容無效，請使用有效的 PNG、JPEG 或 WebP 圖片。',
    en: 'The Stage image is invalid. Use a valid PNG, JPEG, or WebP image.',
  },
  stage_revision_conflict: {
    'zh-TW': '舞台已被另一個頁面更新，請重新整理後再編輯。',
    en: 'The Stage changed in another editor. Refresh before editing again.',
  },
  validation_failed: {
    'zh-TW': '輸入格式或欄位內容無效，請檢查後再試。',
    en: 'The request contains invalid fields or values. Check the input and try again.',
  },
  roll_request_not_found: {
    'zh-TW': '找不到這個正式 RollRequest，請重新整理骰子面板。',
    en: 'This formal RollRequest no longer exists. Refresh the Dice panel.',
  },
  roll_request_already_resolved: {
    'zh-TW': '這個正式 RollRequest 已經完成，不能再次提交結果。',
    en: 'This formal RollRequest is already resolved and cannot be submitted again.',
  },
  invalid_roll_input: {
    'zh-TW': '擲骰輸入無效；請確認實體骰原始值與優勢／劣勢所需骰數。',
    en: 'The roll input is invalid. Check raw physical dice and advantage/disadvantage requirements.',
  },
  roll_character_not_found: {
    'zh-TW': '這個檢定綁定的角色已無法使用，請由 DM 重新建立檢定。',
    en: 'The Character bound to this Check is unavailable. Ask the DM to create a new Check.',
  },
  pending_action_not_found: {
    'zh-TW': '找不到這個 PendingAction，請重新整理目前行動狀態。',
    en: 'This PendingAction no longer exists. Refresh the current action state.',
  },
  pending_action_invalid_transition: {
    'zh-TW': '這個 PendingAction 不能切換到要求的狀態。',
    en: 'This PendingAction cannot move to the requested status.',
  },
  pending_action_version_conflict: {
    'zh-TW': '這個 PendingAction 已被其他操作更新，請重新整理後再試。',
    en: 'This PendingAction changed in another operation. Refresh before trying again.',
  },
  pending_action_invalid_roll_binding: {
    'zh-TW': '這個 PendingAction 無法綁定指定的正式檢定，請重新選擇 RollRequest。',
    en: 'This PendingAction cannot bind to that formal RollRequest. Choose a current request.',
  },
  table_state_subject_stale: {
    'zh-TW': '角色座位或本場角色在提交前已改變，請重新整理角色狀態。',
    en: 'The Seat or active Character changed before the state update committed. Refresh Character state.',
  },
  character_not_found: {
    'zh-TW': '找不到這個本場角色，無法更新目前狀態。',
    en: 'The active Character could not be found for this state update.',
  },
  character_archived: {
    'zh-TW': '這個角色已封存，不能再修改目前狀態。',
    en: 'This Character is archived and its Current State cannot be changed.',
  },
  stale_build_version: {
    'zh-TW': '角色 Build 已更新；請重新整理角色資料後再修改目前狀態。',
    en: 'The Character Build changed. Refresh the Character before updating Current State.',
  },
  state_write_conflict: {
    'zh-TW': '角色目前狀態剛被其他操作更新，請重新整理後再試。',
    en: 'Character Current State changed concurrently. Refresh before trying again.',
  },
  invalid_character_state: {
    'zh-TW': '這次修改會產生不合法的角色目前狀態，請檢查輸入。',
    en: 'This change would create invalid Character Current State. Check the input.',
  },
}

export function localizedSessionRequestMessage(
  code: string | undefined,
  status: number,
  originalMessage: string,
  locale: Locale,
): string {
  if (code && code in SESSION_REQUEST_CODE_MESSAGES) {
    return SESSION_REQUEST_CODE_MESSAGES[code as SessionRequestCode][locale]
  }
  if (locale === 'en') return originalMessage || `Session request failed (${status})`
  return `Session 請求失敗（HTTP ${status}），請稍後再試。`
}
