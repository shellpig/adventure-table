import { useEffect, useMemo, useState } from 'react'

import {
  addRosterCharacter,
  CampaignApiError,
  clearCampaignSelection,
  createCampaign,
  deleteCampaign,
  getCampaign,
  listCampaigns,
  listRoomCharacters,
  listRoster,
  removeRosterCharacter,
  selectCampaign,
  setCampaignStatus,
  setRosterStatus,
  type Campaign,
  type CampaignStatus,
  type RoomCharacterSummary,
  type RosterEntry,
  type RosterStatus,
} from '../../api/campaigns'
import { getRoom, type RoomAuthority, type RoomSummary } from '../../api/rooms'
import { useLocale } from '../../i18n/LocaleProvider'
import { campaignCopy } from './campaignCopy'
import { recentRoomForId } from './roomStorage'
import './rooms.css'

const UUID_PATTERN = '[0-9a-fA-F-]{36}'

export type RoomCampaignRoute = {
  roomId: string
  campaignId: string | null
}

export function roomCampaignRouteFromPath(pathname: string): RoomCampaignRoute | null {
  const match = pathname.match(
    new RegExp(`^/rooms/(${UUID_PATTERN})/campaigns(?:/(${UUID_PATTERN}))?/?$`),
  )
  return match ? { roomId: match[1], campaignId: match[2] ?? null } : null
}

export function campaignPermissions(authority: RoomAuthority | null | undefined) {
  return {
    isOwner: authority === 'owner',
    canManageRoster: authority === 'owner' || authority === 'dm',
  }
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof CampaignApiError ? error.message : fallback
}

export function RoomCampaignPage({ roomId, campaignId }: RoomCampaignRoute) {
  const { locale } = useLocale()
  const copy = campaignCopy(locale)
  const recent = recentRoomForId(roomId)
  const token = recent?.accessToken ?? ''
  const { isOwner, canManageRoster } = campaignPermissions(recent?.authority)
  const [room, setRoom] = useState<RoomSummary | null>(null)
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [campaign, setCampaign] = useState<Campaign | null>(null)
  const [roster, setRoster] = useState<RosterEntry[]>([])
  const [characters, setCharacters] = useState<RoomCharacterSummary[]>([])
  const [name, setName] = useState('')
  const [ruleset, setRuleset] = useState('dnd5e-2014')
  const [selectedCharacterId, setSelectedCharacterId] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const rosterCharacterIds = useMemo(
    () => new Set(roster.map((entry) => entry.character_id)),
    [roster],
  )
  const availableCharacters = characters.filter(
    (character) => !rosterCharacterIds.has(character.id),
  )

  const reloadList = async () => {
    const [nextRoom, nextCampaigns] = await Promise.all([
      getRoom(roomId, token),
      listCampaigns(roomId, token),
    ])
    setRoom(nextRoom)
    setCampaigns(nextCampaigns)
  }

  const reloadDetail = async () => {
    if (!campaignId) return
    const [nextRoom, nextCampaign, nextRoster, nextCharacters] = await Promise.all([
      getRoom(roomId, token),
      getCampaign(roomId, campaignId, token),
      listRoster(roomId, campaignId, token),
      listRoomCharacters(roomId, token),
    ])
    setRoom(nextRoom)
    setCampaign(nextCampaign)
    setRoster(nextRoster)
    setCharacters(nextCharacters)
    const nextAvailable = nextCharacters.filter(
      (item) => !nextRoster.some((entry) => entry.character_id === item.id),
    )
    setSelectedCharacterId((current) =>
      nextAvailable.some((item) => item.id === current) ? current : (nextAvailable[0]?.id ?? ''),
    )
  }

  const runMutation = (
    operation: () => Promise<unknown>,
    refresh: () => Promise<void> = campaignId ? reloadDetail : reloadList,
  ) => {
    setPending(true)
    setError(null)
    void operation()
      .then(() => refresh())
      .catch((cause) => setError(errorMessage(cause, copy.requestFailed)))
      .finally(() => setPending(false))
  }

  useEffect(() => {
    if (!recent) return
    let active = true
    const load = campaignId ? reloadDetail : reloadList
    void load().catch((cause) => {
      if (active) setError(errorMessage(cause, copy.requestFailed))
    })
    return () => {
      active = false
    }
    // The Room token is the authoritative browser credential for this page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignId, roomId, token])

  if (!recent) {
    return (
      <main className="landing-page room-workspace-page">
        <section className="landing-card room-workspace-card">
          <h1>{copy.campaignsTitle}</h1>
          <p>{copy.missingAccess}</p>
          <a className="button secondary" href="/">{copy.backRoom}</a>
        </section>
      </main>
    )
  }

  const statusLabel = (status: CampaignStatus) => copy[status]
  const rosterStatusLabel = (status: RosterStatus) =>
    status === 'active' ? copy.rosterActive : copy[status]

  if (!campaignId) {
    return (
      <main className="landing-page room-workspace-page">
        <section className="landing-card room-workspace-card">
          <h1>{copy.campaignsTitle}</h1>
          <p>{copy.campaignsIntro}</p>
          <a className="button secondary" href={`/rooms/${roomId}`}>{copy.backRoom}</a>
          {error ? <div className="error-banner">{error}</div> : null}
          {isOwner ? (
            <form
              className="room-form"
              onSubmit={(event) => {
                event.preventDefault()
                setPending(true)
                setError(null)
                void createCampaign(roomId, token, { name, ruleset })
                  .then(() => {
                    setName('')
                    return reloadList()
                  })
                  .catch((cause) => setError(errorMessage(cause, copy.requestFailed)))
                  .finally(() => setPending(false))
              }}
            >
              <h2>{copy.createTitle}</h2>
              <label>{copy.nameLabel}<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
              <label>{copy.rulesetLabel}<input value={ruleset} onChange={(event) => setRuleset(event.target.value)} required /></label>
              <button className="button primary" disabled={pending} type="submit">{copy.createAction}</button>
            </form>
          ) : <p>{copy.ownerLifecycleHint}</p>}
          {isOwner && room?.active_campaign_id ? (
            <button
              className="button secondary"
              disabled={pending}
              type="button"
              onClick={() => runMutation(() => clearCampaignSelection(roomId, token), reloadList)}
            >
              {copy.clearSelection}
            </button>
          ) : null}
          <div className="workshop-list">
            {campaigns.length === 0 ? <p>{copy.noCampaigns}</p> : campaigns.map((item) => (
              <article className="workshop-card" key={item.id}>
                <h2>{item.name}</h2>
                <p>{copy.status}: {statusLabel(item.status)}</p>
                {room?.active_campaign_id === item.id ? <strong>{copy.selected}</strong> : null}
                <div className="workshop-card__split-actions">
                  <a className="button primary" href={`/rooms/${roomId}/campaigns/${item.id}`}>{copy.open}</a>
                  {isOwner && item.status !== 'archived' && room?.active_campaign_id !== item.id ? (
                    <button
                      className="button secondary"
                      disabled={pending}
                      type="button"
                      onClick={() => runMutation(() => selectCampaign(roomId, item.id, token), reloadList)}
                    >
                      {copy.select}
                    </button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </section>
      </main>
    )
  }

  if (!campaign) {
    return (
      <main className="landing-page">
        <section className="landing-card">
          <h1>{copy.loading}</h1>
          {error ? <div className="error-banner">{error}</div> : null}
        </section>
      </main>
    )
  }

  return (
    <main className="landing-page room-workspace-page">
      <section className="landing-card room-workspace-card">
        <h1>{campaign.name}</h1>
        <p>{copy.status}: {statusLabel(campaign.status)}</p>
        <div className="workshop-card__split-actions">
          <a className="button secondary" href={`/rooms/${roomId}/campaigns`}>{copy.backCampaigns}</a>
          {isOwner && room?.active_campaign_id !== campaign.id && campaign.status !== 'archived' ? (
            <button
              className="button secondary"
              disabled={pending}
              type="button"
              onClick={() => runMutation(() => selectCampaign(roomId, campaign.id, token))}
            >
              {copy.select}
            </button>
          ) : null}
          {isOwner && room?.active_campaign_id === campaign.id ? (
            <button
              className="button secondary"
              disabled={pending}
              type="button"
              onClick={() => runMutation(() => clearCampaignSelection(roomId, token))}
            >
              {copy.clearSelection}
            </button>
          ) : null}
        </div>
        {isOwner ? (
          <div className="workshop-card__split-actions">
            {(['draft', 'active', 'completed', 'archived'] as CampaignStatus[]).map((status) => (
              <button
                key={status}
                className="button secondary"
                disabled={pending || campaign.status === status}
                type="button"
                onClick={() => runMutation(() => setCampaignStatus(roomId, campaign.id, token, status))}
              >
                {statusLabel(status)}
              </button>
            ))}
            {campaign.status === 'draft' ? (
              <button
                className="button danger"
                disabled={pending}
                type="button"
                onClick={() => {
                  setPending(true)
                  setError(null)
                  void deleteCampaign(roomId, campaign.id, token)
                    .then(() => window.location.assign(`/rooms/${roomId}/campaigns`))
                    .catch((cause) => setError(errorMessage(cause, copy.requestFailed)))
                    .finally(() => setPending(false))
                }}
              >
                {copy.deleteDraft}
              </button>
            ) : null}
          </div>
        ) : <p>{copy.ownerLifecycleHint}</p>}
        {error ? <div className="error-banner">{error}</div> : null}
        <hr />
        <h2>{copy.rosterTitle}</h2>
        <p>{copy.rosterIntro}</p>
        {canManageRoster && availableCharacters.length > 0 ? (
          <div className="workshop-card__split-actions">
            <label>
              {copy.addCharacter}
              <select value={selectedCharacterId} onChange={(event) => setSelectedCharacterId(event.target.value)}>
                {availableCharacters.map((character) => (
                  <option value={character.id} key={character.id}>
                    {character.name} · {copy.levelLabel} {character.level} · {character.class_summary}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="button primary"
              type="button"
              disabled={pending || !selectedCharacterId}
              onClick={() => runMutation(() => addRosterCharacter(roomId, campaign.id, selectedCharacterId, token))}
            >
              {copy.addAction}
            </button>
          </div>
        ) : canManageRoster && availableCharacters.length === 0 ? <p>{copy.noCharacters}</p> : null}
        <div className="workshop-list">
          {roster.length === 0 ? <p>{copy.noRoster}</p> : roster.map((entry) => {
            const character = characters.find((item) => item.id === entry.character_id)
            return (
              <article className="workshop-card" key={entry.character_id}>
                <h3>{character?.name ?? entry.character_id}</h3>
                <p>{copy.status}: {rosterStatusLabel(entry.status)}</p>
                {canManageRoster ? (
                  <div className="workshop-card__split-actions">
                    <select
                      value={entry.status}
                      disabled={pending}
                      onChange={(event) => runMutation(() => setRosterStatus(
                        roomId,
                        campaign.id,
                        entry.character_id,
                        token,
                        event.target.value as RosterStatus,
                      ))}
                    >
                      {(['active', 'inactive', 'retired', 'dead'] as RosterStatus[]).map((status) => (
                        <option key={status} value={status}>{rosterStatusLabel(status)}</option>
                      ))}
                    </select>
                    <button
                      className="button secondary"
                      disabled={pending}
                      type="button"
                      onClick={() => {
                        if (!window.confirm(copy.removeConfirm)) return
                        runMutation(() => removeRosterCharacter(
                          roomId,
                          campaign.id,
                          entry.character_id,
                          token,
                        ))
                      }}
                    >
                      {copy.remove}
                    </button>
                  </div>
                ) : null}
              </article>
            )
          })}
        </div>
      </section>
    </main>
  )
}
