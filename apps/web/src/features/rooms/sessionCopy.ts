import type { Locale } from '../../i18n/locale'
import { localizedSessionRequestMessage } from '../../i18n/sessionMessages'
import { SessionApiError } from '../../api/sessions'

const copy = {
  'zh-TW': {
    locale: 'zh-TW' as const,
    title: '進行中的 Session',
    intro: '本場參與角色在加入時固定；座位控制者可變更，但不會替換已加入的角色。',
    missingAccess: '找不到這個 Room 的本機存取資訊，請重新進入 Room。',
    loadingFailed: 'Session 資料載入失敗。',
    backLobby: '返回大廳',
    start: '開始 Session',
    starting: '正在開始…',
    resume: '繼續 Session',
    activeHint: '這個 Campaign 已有進行中的 Session。',
    participants: '參與者',
    noParticipants: '尚無參與者。',
    dm: 'DM',
    player: '玩家',
    spectator: '旁觀者',
    noCharacter: '無本場角色',
    lateJoin: '中途加入',
    lateJoinSeat: '選擇 Player Seat',
    noLateJoinSeats: '目前沒有可加入的 Player Seat。',
    join: '加入 Session',
    end: '結束 Session',
    endConfirm: '確定正常結束這場 Session？角色目前狀態會原樣保留。',
    abandon: '放棄 Session',
    abandonConfirm: '確定將這場 Session 標記為 abandoned？這不會指派新的 DM。',
    active: '進行中',
    ended: '已結束',
    abandoned: '已放棄',
    currentDmHint: '只有本場固定的 current DM Controller 可以中途加入與正常結束 Session。',
    ownerAbandonHint: 'Room Owner 若不是本場 DM，只能 Abandon，不能接管或正常 End。',
    requestFailed: 'Session 操作失敗。',
  },
  en: {
    locale: 'en' as const,
    title: 'Active Session',
    intro: 'A participant’s active character is fixed when they join. Seat control may change, but it does not replace that character.',
    missingAccess: 'Local access for this Room is missing. Enter the Room again.',
    loadingFailed: 'Session data could not be loaded.',
    backLobby: 'Back to Lobby',
    start: 'Start Session',
    starting: 'Starting…',
    resume: 'Resume Session',
    activeHint: 'This Campaign already has an active Session.',
    participants: 'Participants',
    noParticipants: 'No participants yet.',
    dm: 'DM',
    player: 'Player',
    spectator: 'Spectator',
    noCharacter: 'No active character',
    lateJoin: 'Late Join',
    lateJoinSeat: 'Choose Player Seat',
    noLateJoinSeats: 'No Player Seat is currently eligible to join.',
    join: 'Join Session',
    end: 'End Session',
    endConfirm: 'End this Session normally? Current Character State will be preserved exactly.',
    abandon: 'Abandon Session',
    abandonConfirm: 'Mark this Session abandoned? This does not assign a replacement DM.',
    active: 'Active',
    ended: 'Ended',
    abandoned: 'Abandoned',
    currentDmHint: 'Only this Session’s fixed current DM Controller may Late Join or End it normally.',
    ownerAbandonHint: 'A Room Owner who is not the current DM may Abandon, but cannot take over or End normally.',
    requestFailed: 'Session operation failed.',
  },
} as const

export type SessionCopy = (typeof copy)[Locale]

export function sessionCopy(locale: Locale): SessionCopy {
  return copy[locale]
}

export function sessionErrorMessage(error: unknown, presentation: SessionCopy): string {
  if (!(error instanceof SessionApiError)) return presentation.requestFailed
  return localizedSessionRequestMessage(
    error.code,
    error.status,
    error.message,
    presentation.locale,
  )
}
