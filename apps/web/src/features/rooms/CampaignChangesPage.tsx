import { useEffect, useState } from 'react'

import {
  getRuntimeContext,
  listOverrides,
  listRuntimeEntries,
  type CampaignAdventureOverride,
  type CampaignRuntimeContext,
  type RuntimeWorldEntryDmView,
} from '../../api/campaignRuntime'
import { useLocale } from '../../i18n/LocaleProvider'
import {
  campaignRuntimeCopy,
  campaignRuntimeErrorMessage,
  type CampaignRuntimeCopy,
} from './campaignRuntimeCopy'
import { recentRoomForId } from './roomStorage'
import './rooms.css'

const UUID_PATTERN = '[0-9a-fA-F-]{36}'

export type CampaignChangesRoute = {
  roomId: string
  campaignId: string
}

export function campaignChangesRouteFromPath(pathname: string): CampaignChangesRoute | null {
  const match = pathname.match(
    new RegExp(`^/rooms/(${UUID_PATTERN})/campaigns/(${UUID_PATTERN})/changes/?$`),
  )
  return match ? { roomId: match[1], campaignId: match[2] } : null
}

export function isCampaignChangesEmpty(
  entries: { length: number },
  overrides: { length: number },
  context: {
    current_adventure_scene_entry_id?: string | null
    current_runtime_scene_entry_id?: string | null
    current_situation?: string | null
  } | null,
): boolean {
  if (entries.length > 0 || overrides.length > 0) return false
  if (!context) return true
  return (
    !context.current_adventure_scene_entry_id &&
    !context.current_runtime_scene_entry_id &&
    !context.current_situation
  )
}

export type CampaignChangesViewProps = {
  roomId: string
  campaignId: string
  loading: boolean
  error: string | null
  entries: RuntimeWorldEntryDmView[]
  overrides: CampaignAdventureOverride[]
  context: CampaignRuntimeContext | null
  copy: CampaignRuntimeCopy
}

export function CampaignChangesView({
  roomId,
  campaignId,
  loading,
  error,
  entries,
  overrides,
  context,
  copy,
}: CampaignChangesViewProps) {
  const isEmpty = isCampaignChangesEmpty(entries, overrides, context)
  const backHref = `/rooms/${roomId}/campaigns/${campaignId}`
  const currentScene =
    context?.current_runtime_scene_entry_id ??
    context?.current_adventure_scene_entry_id ??
    null

  return (
    <main className="landing-page room-workspace-page">
      <section className="landing-card room-workspace-card">
        <h1>{copy.changesTitle}</h1>
        <p>{copy.changesIntro}</p>
        <div className="workshop-card__split-actions">
          <a className="button secondary" href={backHref}>
            {copy.backCampaign}
          </a>
        </div>
        {loading ? <p>{copy.loading}</p> : null}
        {error ? <div className="error-banner">{error}</div> : null}
        {!loading && !error && isEmpty ? (
          <p>{copy.emptyState}</p>
        ) : null}
        {!loading && !error && !isEmpty ? (
          <div>
            <hr />
            <section>
              <h2>{copy.contextHeading}</h2>
              <p>
                <strong>{copy.currentSceneLabel}:</strong> {currentScene ?? copy.noCurrentScene}
              </p>
              {context?.current_situation ? (
                <p>
                  <strong>{copy.currentSituationLabel}:</strong> {context.current_situation}
                </p>
              ) : null}
            </section>
            <hr />
            <section>
              <h2>{copy.entriesHeading}</h2>
              <p>{copy.entryCountLabel}: {entries.length}</p>
            </section>
            <hr />
            <section>
              <h2>{copy.overridesHeading}</h2>
              <p>{copy.overrideCountLabel}: {overrides.length}</p>
            </section>
          </div>
        ) : null}
      </section>
    </main>
  )
}

export function CampaignChangesPage({ roomId, campaignId }: CampaignChangesRoute) {
  const { locale } = useLocale()
  const copy = campaignRuntimeCopy(locale)
  const recent = recentRoomForId(roomId)
  const token = recent?.accessToken ?? ''
  const [entries, setEntries] = useState<RuntimeWorldEntryDmView[]>([])
  const [overrides, setOverrides] = useState<CampaignAdventureOverride[]>([])
  const [context, setContext] = useState<CampaignRuntimeContext | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!recent) {
      setLoading(false)
      setError(copy.missingAccess)
      return
    }

    let active = true
    setLoading(true)
    setError(null)

    Promise.all([
      listRuntimeEntries(roomId, campaignId, token),
      listOverrides(roomId, campaignId, token),
      getRuntimeContext(roomId, campaignId, token),
    ])
      .then(([nextEntries, nextOverrides, nextContext]) => {
        if (!active) return
        setEntries(nextEntries)
        setOverrides(nextOverrides)
        setContext(nextContext)
      })
      .catch((cause: unknown) => {
        if (!active) return
        setError(campaignRuntimeErrorMessage(cause, copy))
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
    // Room token is the authoritative credential for this Room-first page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignId, locale, roomId, token])

  return (
    <CampaignChangesView
      roomId={roomId}
      campaignId={campaignId}
      loading={loading}
      error={error}
      entries={entries}
      overrides={overrides}
      context={context}
      copy={copy}
    />
  )
}
