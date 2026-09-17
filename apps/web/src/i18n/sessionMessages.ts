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
] as const

export const P4E_SESSION_REQUEST_CODES = [
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
] as const

export const SESSION_REQUEST_CODES = [
  ...P2E_SESSION_REQUEST_CODES,
  ...P3B_SESSION_REQUEST_CODES,
  ...P3C_SESSION_REQUEST_CODES,
  ...P4E_SESSION_REQUEST_CODES,
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
  unknown_check_ref: {
    'zh-TW': '這個檢定的技能／屬性參照無法解析，請由 DM 用正確的技能或屬性名稱重新建立。',
    en: 'This Check has an unresolvable skill/ability reference. Ask the DM to recreate it with a valid skill or ability name.',
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
  unknown_reference: {
    'zh-TW': '找不到指定的內容參照或規則資料，請確認資料來源。',
    en: 'The requested content reference or rules data could not be found. Check the content source.',
  },
  monster_instance_conflict: {
    'zh-TW': '怪物實體狀態發生衝突，請重新整理戰鬥後再試。',
    en: 'Monster instance state conflict occurred. Refresh the Combat and try again.',
  },
  combat_not_found: {
    'zh-TW': '找不到進行中的戰鬥，請確認戰鬥是否已開始或已結束。',
    en: 'Active Combat could not be found. Confirm whether Combat has started or already ended.',
  },
  attack_not_found: {
    'zh-TW': '找不到這項攻擊請求或攻擊定義，請重新整理戰鬥面板。',
    en: 'This attack request or definition no longer exists. Refresh the Combat panel.',
  },
  combat_roll_not_found: {
    'zh-TW': '找不到這筆待處理的戰鬥擲骰，請重新整理擲骰面板。',
    en: 'This pending combat roll could not be found. Refresh the roll panel.',
  },
  combat_target_not_found: {
    'zh-TW': '戰鬥目標已不在這場戰鬥中，請重新選擇目標。',
    en: 'The combat target is no longer in this Combat. Select another target.',
  },
  active_combat_exists: {
    'zh-TW': '這個 Campaign 已有進行中的戰鬥。',
    en: 'This Campaign already has an active Combat.',
  },
  combat_state_conflict: {
    'zh-TW': '戰鬥狀態已變更，這個動作現在不能執行，請重新整理後再試。',
    en: 'Combat state changed and this action is no longer allowed. Refresh and try again.',
  },
  initiative_request_not_found: {
    'zh-TW': '找不到這項先攻擲骰請求，可能已被結算或取消。',
    en: 'This initiative roll request could not be found. It may have been resolved or canceled.',
  },
  invalid_initiative_input: {
    'zh-TW': '先攻數值無效，請輸入合法的先攻擲骰結果。',
    en: 'Invalid initiative value. Provide a valid initiative roll result.',
  },
  invalid_attack_definition: {
    'zh-TW': '攻擊定義內容無效，請確認射程、傷害或加值設定。',
    en: 'The attack definition is invalid. Check range, damage, or modifier settings.',
  },
  invalid_combat_input: {
    'zh-TW': '戰鬥輸入不合法，請檢查目標、骰值或參數。',
    en: 'Invalid combat input. Check the target, roll, or parameters.',
  },
  special_attack_not_found: {
    'zh-TW': '找不到這項特殊攻擊請求，請重新整理後再試。',
    en: 'This special attack request no longer exists. Refresh and try again.',
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
