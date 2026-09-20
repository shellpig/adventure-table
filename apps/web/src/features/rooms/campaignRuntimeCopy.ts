import { CampaignRuntimeApiError } from '../../api/campaignRuntime'
import type { Locale } from '../../i18n/locale'

const COPY = {
  en: {
    changesTitle: 'Campaign Changes',
    changesIntro: 'Review mutable world entries, adventure overrides, and the current situation for this Campaign.',
    backCampaign: '← Back to Campaign',
    loading: 'Loading Campaign changes…',
    emptyState: 'No runtime entries, overrides, or current situation recorded yet.',
    missingAccess: 'This browser does not have access to this Room. Enter the Room again.',
    entriesHeading: 'Runtime Entries',
    overridesHeading: 'Adventure Overrides',
    contextHeading: 'Current Context',
    currentSituationLabel: 'Current Situation',
    currentSceneLabel: 'Current Scene',
    noCurrentScene: 'None',
    entryCountLabel: 'Active entries',
    overrideCountLabel: 'Active overrides',
    requestFailed: 'Campaign runtime request failed.',
    errCampaignRuntimeForbidden: 'You do not have permission to manage runtime world state for this Campaign.',
    errCampaignRuntimeNotFound: 'Requested runtime entry, override, or Campaign was not found.',
    errCampaignRuntimeArchived: 'This runtime entry or Campaign is archived and cannot be modified.',
    errCampaignRuntimeActiveSession: 'An active Session is currently in progress; manage world changes through the active Session.',
    errCampaignRuntimeSessionNotActive: 'The Session is not active or has ended.',
    errCampaignRuntimeIdempotencyConflict: 'An operation with this request key was already processed with different parameters.',
    errCampaignRuntimeRevisionConflict: 'Runtime world state was modified by another action. Please refresh and try again.',
    errCampaignRuntimeOverrideExists: 'An override already exists for this adventure entry.',
    errCampaignRuntimeInvalid: 'Invalid runtime world state data or parameters.',
  },
  'zh-TW': {
    changesTitle: 'Campaign 變更',
    changesIntro: '檢視此 Campaign 的動態世界項目、冒險覆寫與目前情境。',
    backCampaign: '← 回 Campaign',
    loading: '正在載入 Campaign 變更…',
    emptyState: '目前尚未記錄任何執行期項目、覆寫或目前情境。',
    missingAccess: '這個瀏覽器沒有此 Room 的存取權，請重新進入 Room。',
    entriesHeading: '執行期項目',
    overridesHeading: '冒險覆寫',
    contextHeading: '目前情境',
    currentSituationLabel: '目前情境摘要',
    currentSceneLabel: '目前場景',
    noCurrentScene: '無',
    entryCountLabel: '使用中項目',
    overrideCountLabel: '使用中覆寫',
    requestFailed: 'Campaign 世界狀態請求失敗。',
    errCampaignRuntimeForbidden: '您沒有在此 Campaign 管理世界狀態的權限。',
    errCampaignRuntimeNotFound: '找不到指定的執行期項目、覆寫或 Campaign。',
    errCampaignRuntimeArchived: '此執行期項目或 Campaign 已封存，無法修改。',
    errCampaignRuntimeActiveSession: '目前已有進行中的 Session，請透過進行中的 Session 進行世界狀態變更。',
    errCampaignRuntimeSessionNotActive: 'Session 目前非進行中或已結束。',
    errCampaignRuntimeIdempotencyConflict: '此請求索引鍵先前已以不同參數處理過。',
    errCampaignRuntimeRevisionConflict: '世界狀態已被其他動作修改，請重新整理後再試一次。',
    errCampaignRuntimeOverrideExists: '此冒險項目已存在覆寫。',
    errCampaignRuntimeInvalid: '執行期世界狀態資料或參數無效。',
  },
} as const satisfies Record<Locale, Record<string, string>>

export type CampaignRuntimeCopy = Record<keyof (typeof COPY)['en'], string>

export function campaignRuntimeCopy(locale: Locale): CampaignRuntimeCopy {
  return COPY[locale]
}

export function campaignRuntimeErrorMessage(error: unknown, copy: CampaignRuntimeCopy): string {
  const code =
    error instanceof CampaignRuntimeApiError
      ? error.code
      : typeof error === 'object' && error !== null && 'code' in error
        ? String((error as { code: unknown }).code)
        : null

  switch (code) {
    case 'campaign_runtime_forbidden':
      return copy.errCampaignRuntimeForbidden
    case 'campaign_runtime_not_found':
      return copy.errCampaignRuntimeNotFound
    case 'campaign_runtime_archived':
      return copy.errCampaignRuntimeArchived
    case 'campaign_runtime_active_session':
      return copy.errCampaignRuntimeActiveSession
    case 'campaign_runtime_session_not_active':
      return copy.errCampaignRuntimeSessionNotActive
    case 'campaign_runtime_idempotency_conflict':
      return copy.errCampaignRuntimeIdempotencyConflict
    case 'campaign_runtime_revision_conflict':
      return copy.errCampaignRuntimeRevisionConflict
    case 'campaign_runtime_override_exists':
      return copy.errCampaignRuntimeOverrideExists
    case 'campaign_runtime_invalid':
      return copy.errCampaignRuntimeInvalid
    default:
      return copy.requestFailed
  }
}
