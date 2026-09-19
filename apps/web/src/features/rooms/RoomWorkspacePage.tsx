import { useEffect, useState } from 'react'

import { listCampaigns, type Campaign } from '../../api/campaigns'
import type { CharacterListItem } from '../../api/characterBuilder'
import { listRoomCharacters, listRoomDraftCount } from '../../api/roomCharacters'
import { deleteRoom, getRoom, heartbeatRoom, RoomApiError, type RoomSummary } from '../../api/rooms'
import type { Locale } from '../../i18n/locale'
import { useLocale } from '../../i18n/LocaleProvider'
import { localizedRoomRequestMessage } from '../../i18n/roomMessages'
import { roomCopy, type RoomCopy } from './copy'
import { startRoomHeartbeat } from './heartbeat'
import { forgetRecentRoom, recentRoomForId } from './roomStorage'
import './rooms.css'

export function roomIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/rooms\/([0-9a-fA-F-]{36})\/?$/)
  return match?.[1] ?? null
}

/**
 * The stored Recent Rooms entry can never open this Room again: the Room is gone
 * (404), or its access session no longer exists — Room hard delete cascades the
 * session away, so a deleted Room actually surfaces as 403 room_access_denied.
 */
export function isStaleRecentRoom(cause: unknown): boolean {
  if (!(cause instanceof RoomApiError)) return false
  return cause.code === 'room_not_found' || cause.code === 'room_access_denied'
}

export type DeleteRoomInventoryViewModel = {
  campaignCount: number
  characterCount: number
  draftCount: number
  campaigns: string[]
  characters: { name: string; class_summary: string; archived: boolean }[]
}

export function buildDeleteInventory(
  campaigns: Campaign[],
  activeCharacters: CharacterListItem[],
  archivedCharacters: CharacterListItem[],
  draftCount: number,
): DeleteRoomInventoryViewModel {
  return {
    campaignCount: campaigns.length,
    characterCount: activeCharacters.length + archivedCharacters.length,
    draftCount,
    campaigns: campaigns.map((campaign) => campaign.name),
    characters: [
      ...activeCharacters.map((c) => ({
        name: c.name,
        class_summary: c.class_summary,
        archived: false,
      })),
      ...archivedCharacters.map((c) => ({
        name: c.name,
        class_summary: c.class_summary,
        archived: true,
      })),
    ],
  }
}

export async function fetchDeleteRoomInventory(
  roomId: string,
  accessToken: string,
): Promise<DeleteRoomInventoryViewModel> {
  const [campaigns, active, archived, draftCount] = await Promise.all([
    listCampaigns(roomId, accessToken),
    listRoomCharacters(roomId, accessToken),
    listRoomCharacters(roomId, accessToken, { archived: true }),
    listRoomDraftCount(roomId, accessToken),
  ])
  return buildDeleteInventory(campaigns, active, archived, draftCount)
}

export function DeleteRoomInventoryView({
  inventory,
  loading,
  error,
  copy,
}: {
  inventory: DeleteRoomInventoryViewModel | null
  loading: boolean
  error: boolean
  copy: RoomCopy
}) {
  if (loading) {
    return <p className="room-workspace-meta">{copy.deleteRoomInventoryLoading}</p>
  }
  if (error) {
    return <div className="error-banner">{copy.deleteRoomInventoryError}</div>
  }
  if (!inventory) {
    return null
  }

  const summary = copy.deleteRoomInventorySummary
    .replace('{campaigns}', String(inventory.campaignCount))
    .replace('{characters}', String(inventory.characterCount))
    .replace('{drafts}', String(inventory.draftCount))

  return (
    <div className="room-delete-inventory">
      <p className="room-workspace-meta">{summary}</p>
      {inventory.campaigns.length > 0 ? (
        <div className="room-delete-inventory-group">
          <strong>{copy.deleteRoomInventoryCampaigns}</strong>
          <ul className="room-delete-inventory-list">
            {inventory.campaigns.map((name, index) => (
              <li key={`${name}-${index}`}>{name}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {inventory.characters.length > 0 ? (
        <div className="room-delete-inventory-group">
          <strong>{copy.deleteRoomInventoryCharacters}</strong>
          <ul className="room-delete-inventory-list">
            {inventory.characters.map((char, index) => {
              const summaryPart = char.class_summary ? ` (${char.class_summary})` : ''
              const archivedPart = char.archived ? copy.deleteRoomInventoryArchivedSuffix : ''
              return (
                <li key={`${char.name}-${index}`}>
                  {char.name}{summaryPart}{archivedPart}
                </li>
              )
            })}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

export type DeleteRoomSectionProps = {
  roomId: string
  roomName: string
  isOwner: boolean
  deleteOpen: boolean
  onOpenDelete: () => void
  onCancelDelete: () => void
  onConfirmDelete: () => void
  deleteConfirmation: string
  onConfirmationChange: (value: string) => void
  deletePending: boolean
  deleteError: RoomApiError | null
  inventory: DeleteRoomInventoryViewModel | null
  inventoryLoading: boolean
  inventoryError: boolean
  copy: RoomCopy
  locale: Locale
}

export function DeleteRoomSection({
  roomId,
  roomName,
  isOwner,
  deleteOpen,
  onOpenDelete,
  onCancelDelete,
  onConfirmDelete,
  deleteConfirmation,
  onConfirmationChange,
  deletePending,
  deleteError,
  inventory,
  inventoryLoading,
  inventoryError,
  copy,
  locale,
}: DeleteRoomSectionProps) {
  if (!isOwner) return null

  return (
    <div className="workshop-card__danger">
      <strong>{copy.deleteRoomTitle}</strong>
      <p>{copy.deleteRoomDescription}</p>
      {deleteError ? (
        <div className="error-banner">
          {localizedRoomRequestMessage(deleteError.code, deleteError.status, deleteError.message, locale)}
        </div>
      ) : null}
      {deleteOpen ? (
        <>
          <DeleteRoomInventoryView
            inventory={inventory}
            loading={inventoryLoading}
            error={inventoryError}
            copy={copy}
          />
          <label htmlFor={`delete-room-${roomId}`}>
            {copy.deleteRoomPrompt.replace('{room}', roomName)}
          </label>
          <input
            id={`delete-room-${roomId}`}
            value={deleteConfirmation}
            autoComplete="off"
            onChange={(event) => onConfirmationChange(event.target.value)}
          />
          <div className="workshop-card__split-actions">
            <button
              type="button"
              className="button secondary"
              disabled={deletePending}
              onClick={onCancelDelete}
            >
              {copy.deleteRoomCancel}
            </button>
            <button
              type="button"
              className="button danger"
              disabled={deletePending || deleteConfirmation.trim() !== roomName}
              onClick={onConfirmDelete}
            >
              {deletePending ? copy.deleteRoomDeleting : copy.deleteRoomConfirm}
            </button>
          </div>
        </>
      ) : (
        <button
          type="button"
          className="workshop-card__quiet-action workshop-card__quiet-action--danger"
          onClick={onOpenDelete}
        >
          {copy.deleteRoomAction}
        </button>
      )}
    </div>
  )
}

export function RoomWorkspacePage({ roomId }: { roomId: string }) {
  const { locale } = useLocale()
  const copy = roomCopy(locale)
  const recent = recentRoomForId(roomId)
  const [room, setRoom] = useState<RoomSummary | null>(null)
  const [roomError, setRoomError] = useState<RoomApiError | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'missing' | 'error'>(
    recent ? 'loading' : 'missing',
  )
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteConfirmation, setDeleteConfirmation] = useState('')
  const [deletePending, setDeletePending] = useState(false)
  const [deleteError, setDeleteError] = useState<RoomApiError | null>(null)
  const [inventory, setInventory] = useState<DeleteRoomInventoryViewModel | null>(null)
  const [inventoryLoading, setInventoryLoading] = useState(false)
  const [inventoryError, setInventoryError] = useState(false)

  useEffect(() => {
    if (!recent) return
    let active = true

    void getRoom(roomId, recent.accessToken)
      .then((next) => {
        if (!active) return
        setRoom(next)
        setRoomError(null)
        setStatus('ready')
      })
      .catch((cause: unknown) => {
        if (!active) return
        if (isStaleRecentRoom(cause)) forgetRecentRoom(roomId)
        setRoomError(cause instanceof RoomApiError ? cause : null)
        setStatus('error')
      })

    const stopHeartbeat = startRoomHeartbeat(async () => {
      try {
        await heartbeatRoom(roomId, recent.accessToken)
      } catch (cause) {
        if (active) {
          setRoomError(cause instanceof RoomApiError ? cause : null)
          setStatus('error')
        }
      }
    })

    return () => {
      active = false
      stopHeartbeat()
    }
  }, [recent?.accessToken, roomId])

  function handleOpenDelete() {
    if (!recent) return
    setDeleteOpen(true)
    setInventory(null)
    setInventoryError(false)
    setInventoryLoading(true)
    void fetchDeleteRoomInventory(roomId, recent.accessToken)
      .then((data) => {
        setInventory(data)
      })
      .catch(() => {
        setInventoryError(true)
      })
      .finally(() => {
        setInventoryLoading(false)
      })
  }

  function handleCancelDelete() {
    setDeleteOpen(false)
    setDeleteConfirmation('')
    setDeleteError(null)
    setInventory(null)
    setInventoryLoading(false)
    setInventoryError(false)
  }

  function handleConfirmDelete() {
    if (!recent) return
    setDeletePending(true)
    setDeleteError(null)
    void deleteRoom(roomId, recent.accessToken)
      .then(() => {
        forgetRecentRoom(roomId)
        window.location.assign('/')
      })
      .catch((cause: unknown) => {
        setDeleteError(cause instanceof RoomApiError ? cause : null)
        setDeletePending(false)
      })
  }

  if (status === 'missing') {
    return (
      <main className="landing-page room-workspace-page">
        <section className="landing-card room-workspace-card">
          <p className="eyebrow">{copy.workspaceEyebrow}</p>
          <h1>Adventure Table</h1>
          <p>{copy.workspaceMissing}</p>
          <a className="button secondary" href="/">{copy.backHome}</a>
        </section>
      </main>
    )
  }

  if (status === 'loading') {
    return (
      <main className="landing-page room-workspace-page">
        <section className="landing-card room-workspace-card">
          <p className="eyebrow">{copy.workspaceEyebrow}</p>
          <h1>{copy.workspaceLoading}</h1>
        </section>
      </main>
    )
  }

  if (status === 'error' || !recent) {
    const message = isStaleRecentRoom(roomError)
      ? copy.workspaceStale
      : roomError
        ? localizedRoomRequestMessage(roomError.code, roomError.status, roomError.message, locale)
        : copy.workspaceError
    return (
      <main className="landing-page room-workspace-page">
        <section className="landing-card room-workspace-card">
          <p className="eyebrow">{copy.workspaceEyebrow}</p>
          <h1>Adventure Table</h1>
          <p>{message}</p>
          <a className="button secondary" href="/">{copy.backHome}</a>
        </section>
      </main>
    )
  }

  const roomName = room?.name ?? recent.name
  const isOwner = recent.authority === 'owner'

  return (
    <main className="landing-page room-workspace-page">
      <section className="landing-card room-workspace-card">
        <p className="eyebrow">{copy.workspaceEyebrow}</p>
        <h1>{roomName}</h1>
        <div className="room-workspace-meta">
          <code>{room?.code ?? recent.code}</code>
          <span>{copy.authority}: {recent.authority}</span>
        </div>
        <p>{copy.workspacePlaceholder}</p>
        <div className="workshop-card__split-actions">
          <a className="button primary" href={`/rooms/${roomId}/characters`}>
            {copy.charactersAction}
          </a>
          <a className="button primary" href={`/rooms/${roomId}/campaigns`}>
            {copy.campaignsAction}
          </a>
          <a className="button secondary" href="/">{copy.backHome}</a>
        </div>

        <DeleteRoomSection
          roomId={roomId}
          roomName={roomName}
          isOwner={isOwner}
          deleteOpen={deleteOpen}
          onOpenDelete={handleOpenDelete}
          onCancelDelete={handleCancelDelete}
          onConfirmDelete={handleConfirmDelete}
          deleteConfirmation={deleteConfirmation}
          onConfirmationChange={setDeleteConfirmation}
          deletePending={deletePending}
          deleteError={deleteError}
          inventory={inventory}
          inventoryLoading={inventoryLoading}
          inventoryError={inventoryError}
          copy={copy}
          locale={locale}
        />
      </section>
    </main>
  )
}
