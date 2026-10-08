import { useCallback, useEffect, useRef, useState } from 'react'

import {
  archiveBattleMap,
  copyBattleMap,
  createBattleMap,
  deleteBattleMap,
  getBattleMap,
  listBattleMaps,
  type BattleMap,
  type BattleMapSummary,
} from '../../api/battleMaps'
import { getRoomAssetContent, uploadRoomAsset } from '../../api/roomAssets'
import type { RoomAuthority } from '../../api/rooms'
import { SessionApiError } from '../../api/sessions'
import { useLocale } from '../../i18n/LocaleProvider'
import { BattleMapEditor } from './BattleMapEditor'
import {
  battleMapLibraryCopy,
  battleMapLibraryErrorMessage,
  type BattleMapLibraryCopy,
} from './battleMapLibraryCopy'
import {
  isValidGridOffsetInput,
  isValidGridPixelSizeInput,
  previewGridLines,
  resolveCreateImageGrid,
  useImageNaturalSize,
} from './battleMapImageGrid'
import { recentRoomForId } from './roomStorage'
import { sessionCopy } from './sessionCopy'
import './rooms.css'

const UUID_PATTERN = '[0-9a-fA-F-]{36}'

export type RoomBattleMapLibraryRoute = {
  roomId: string
}

export function roomBattleMapLibraryRouteFromPath(
  pathname: string,
): RoomBattleMapLibraryRoute | null {
  const match = pathname.match(
    new RegExp(`^/rooms/(${UUID_PATTERN})/battle-maps/?$`),
  )
  return match ? { roomId: match[1] } : null
}

export function libraryPermissions(authority: RoomAuthority | null | undefined): {
  canManage: boolean
} {
  return {
    canManage: authority === 'owner' || authority === 'dm',
  }
}

export type RoomBattleMapLibraryPageProps = {
  roomId: string
}

export function RoomBattleMapLibraryPage({ roomId }: RoomBattleMapLibraryPageProps) {
  const { locale } = useLocale()
  const copy: BattleMapLibraryCopy = battleMapLibraryCopy(locale)
  const recent = recentRoomForId(roomId)
  const token = recent?.accessToken ?? ''
  const { canManage } = libraryPermissions(recent?.authority)

  const [maps, setMaps] = useState<BattleMapSummary[]>([])
  const [loadingList, setLoadingList] = useState(false)
  const [showArchived, setShowArchived] = useState(false)
  const [listError, setListError] = useState<string | null>(null)

  const [pendingAction, setPendingAction] = useState<
    'create' | 'upload' | 'copy' | 'archive' | 'delete' | null
  >(null)

  const [editingMap, setEditingMap] = useState<BattleMap | null>(null)
  const [editingImageUrl, setEditingImageUrl] = useState<string | null>(null)

  // Create Blank Modal State
  const [showCreateBlankModal, setShowCreateBlankModal] = useState(false)
  const [createBlankName, setCreateBlankName] = useState('')
  const [createBlankWidth, setCreateBlankWidth] = useState('20')
  const [createBlankHeight, setCreateBlankHeight] = useState('20')

  // Create Image Modal State
  const [showCreateImageModal, setShowCreateImageModal] = useState(false)
  const [createImageName, setCreateImageName] = useState('')
  const [createImageFile, setCreateImageFile] = useState<File | null>(null)
  const [createImageWidth, setCreateImageWidth] = useState('20')
  const [createImageHeight, setCreateImageHeight] = useState('20')
  // M07-D F13: grid alignment against the uploaded background image.
  // Empty inputs use the explicit new-upload defaults (size 40, offsets 0)
  // so the preview and the saved payload always agree.
  const [createImagePreviewUrl, setCreateImagePreviewUrl] = useState<string | null>(null)
  const createImageNaturalSize = useImageNaturalSize(createImagePreviewUrl)
  const createImagePreviewUrlRef = useRef<string | null>(null)
  createImagePreviewUrlRef.current = createImagePreviewUrl
  // Object URLs are revoked on replacement/close below; this only covers
  // unmount with the modal still open.
  useEffect(
    () => () => {
      if (createImagePreviewUrlRef.current) {
        URL.revokeObjectURL(createImagePreviewUrlRef.current)
      }
    },
    [],
  )
  const [createImageGridSize, setCreateImageGridSize] = useState('')
  const [createImageOffsetX, setCreateImageOffsetX] = useState('')
  const [createImageOffsetY, setCreateImageOffsetY] = useState('')

  // Copy Modal State
  const [showCopyModal, setShowCopyModal] = useState(false)
  const [copyTargetMap, setCopyTargetMap] = useState<BattleMapSummary | null>(null)
  const [copyNewName, setCopyNewName] = useState('')

  const loadMaps = useCallback(async () => {
    if (!token) return
    setLoadingList(true)
    try {
      const data = await listBattleMaps(roomId, token, { includeArchived: showArchived })
      setMaps(data)
    } catch (cause) {
      setListError(battleMapLibraryErrorMessage(cause, copy))
    } finally {
      setLoadingList(false)
    }
  }, [roomId, token, showArchived, copy])

  // Escape closes whichever map modal is open, unless an action is pending.
  useEffect(() => {
    if (!showCreateBlankModal && !showCreateImageModal && !showCopyModal) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || pendingAction !== null) return
      if (showCreateImageModal) resetCreateImageModal()
      setShowCreateBlankModal(false)
      setShowCopyModal(false)
      setCopyTargetMap(null)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showCreateBlankModal, showCreateImageModal, showCopyModal, pendingAction])

  useEffect(() => {
    if (canManage && token) {
      void loadMaps()
    }
  }, [canManage, token, loadMaps])

  const handleCreateBlank = async () => {
    const name = createBlankName.trim()
    if (!name || pendingAction) return
    const width = Math.min(200, Math.max(1, parseInt(createBlankWidth, 10) || 20))
    const height = Math.min(200, Math.max(1, parseInt(createBlankHeight, 10) || 20))
    setListError(null)
    setPendingAction('create')
    try {
      await createBattleMap(
        roomId,
        { name, source_kind: 'blank', width_cells: width, height_cells: height },
        token,
      )
      setShowCreateBlankModal(false)
      setCreateBlankName('')
      setCreateBlankWidth('20')
      setCreateBlankHeight('20')
      await loadMaps()
    } catch (cause) {
      setListError(battleMapLibraryErrorMessage(cause, copy))
      await loadMaps()
    } finally {
      setPendingAction(null)
    }
  }

  const setCreateImageFileAndPreview = (file: File | null) => {
    if (createImagePreviewUrl) {
      URL.revokeObjectURL(createImagePreviewUrl)
      setCreateImagePreviewUrl(null)
    }
    setCreateImageFile(file)
    if (file) {
      setCreateImagePreviewUrl(URL.createObjectURL(file))
    }
  }

  const resetCreateImageModal = () => {
    if (createImagePreviewUrl) URL.revokeObjectURL(createImagePreviewUrl)
    setShowCreateImageModal(false)
    setCreateImageName('')
    setCreateImageFile(null)
    setCreateImageWidth('20')
    setCreateImageHeight('20')
    setCreateImagePreviewUrl(null)
    setCreateImageGridSize('')
    setCreateImageOffsetX('')
    setCreateImageOffsetY('')
  }

  const createImageGridInvalid =
    !isValidGridPixelSizeInput(createImageGridSize)
    || !isValidGridOffsetInput(createImageOffsetX)
    || !isValidGridOffsetInput(createImageOffsetY)

  // Identical effective values for the preview overlay and the create payload.
  const createImageGrid = resolveCreateImageGrid(
    createImageGridSize,
    createImageOffsetX,
    createImageOffsetY,
  )

  const handleCreateImage = async () => {
    const name = createImageName.trim()
    if (!name || !createImageFile || pendingAction || createImageGridInvalid) return
    const width = Math.min(200, Math.max(1, parseInt(createImageWidth, 10) || 20))
    const height = Math.min(200, Math.max(1, parseInt(createImageHeight, 10) || 20))
    setListError(null)
    setPendingAction('upload')
    try {
      const asset = await uploadRoomAsset(roomId, token, {
        kind: 'battle_map_image',
        filename: createImageFile.name,
        file: createImageFile,
      })
      await createBattleMap(
        roomId,
        {
          name,
          source_kind: 'image',
          image_asset_id: asset.id,
          width_cells: width,
          height_cells: height,
          grid_pixel_size: createImageGrid.pixelSize,
          grid_offset_x: createImageGrid.offsetX,
          grid_offset_y: createImageGrid.offsetY,
        },
        token,
      )
      resetCreateImageModal()
      await loadMaps()
    } catch (cause) {
      setListError(battleMapLibraryErrorMessage(cause, copy))
      await loadMaps()
    } finally {
      setPendingAction(null)
    }
  }

  const handleCopy = async () => {
    if (!copyTargetMap || pendingAction) return
    setListError(null)
    setPendingAction('copy')
    try {
      await copyBattleMap(
        roomId,
        copyTargetMap.id,
        {
          expected_revision: copyTargetMap.revision,
          name: copyNewName.trim() || undefined,
        },
        token,
      )
      setShowCopyModal(false)
      setCopyTargetMap(null)
      setCopyNewName('')
      await loadMaps()
    } catch (cause) {
      setListError(battleMapLibraryErrorMessage(cause, copy))
      await loadMaps()
    } finally {
      setPendingAction(null)
    }
  }

  const handleArchive = async (map: BattleMapSummary) => {
    if (pendingAction) return
    if (!window.confirm(copy.archiveConfirm)) return
    setListError(null)
    setPendingAction('archive')
    try {
      await archiveBattleMap(
        roomId,
        map.id,
        { expected_revision: map.revision },
        token,
      )
      await loadMaps()
    } catch (cause) {
      setListError(battleMapLibraryErrorMessage(cause, copy))
      await loadMaps()
    } finally {
      setPendingAction(null)
    }
  }

  const handleDelete = async (map: BattleMapSummary) => {
    if (pendingAction) return
    if (!window.confirm(copy.deleteConfirm)) return
    setListError(null)
    setPendingAction('delete')
    try {
      await deleteBattleMap(roomId, map.id, map.revision, token)
      await loadMaps()
    } catch (cause) {
      setListError(battleMapLibraryErrorMessage(cause, copy))
      await loadMaps()
    } finally {
      setPendingAction(null)
    }
  }

  const handleOpenEditor = async (mapId: string) => {
    setListError(null)
    try {
      const fullMap = await getBattleMap(roomId, mapId, token)
      if (fullMap.image_asset_id) {
        const blob = await getRoomAssetContent(roomId, fullMap.image_asset_id, token)
        setEditingImageUrl(URL.createObjectURL(blob))
      }
      setEditingMap(fullMap)
    } catch (cause) {
      setListError(battleMapLibraryErrorMessage(cause, copy))
    }
  }

  if (!recent || !token) {
    return (
      <div className="battle-map-library page">
        <header className="page-header">
          <a className="page-header__back" href={`/rooms/${roomId}`}>
            {copy.backRoom}
          </a>
          <h1>{copy.title}</h1>
        </header>
        <div className="banner error">{copy.missingAccess}</div>
      </div>
    )
  }

  if (!canManage) {
    return (
      <div className="battle-map-library page">
        <header className="page-header">
          <a className="page-header__back" href={`/rooms/${roomId}`}>
            {copy.backRoom}
          </a>
          <h1>{copy.title}</h1>
        </header>
        <div className="banner warning" data-testid="map-library-forbidden">
          {copy.forbidden}
        </div>
      </div>
    )
  }

  if (editingMap) {
    return (
      <div className="battle-map-library battle-map-library--editing page">
        <header className="page-header">
          <a
            className="page-header__back"
            href={`/rooms/${roomId}`}
            data-testid="editor-back-link"
            onClick={(e) => {
              e.preventDefault()
              setEditingMap(null)
              if (editingImageUrl) {
                URL.revokeObjectURL(editingImageUrl)
                setEditingImageUrl(null)
              }
              void loadMaps()
            }}
          >
            {copy.backRoom}
          </a>
          <h1>{copy.title} — {editingMap.name}</h1>
        </header>
        <BattleMapEditor
          map={editingMap}
          copy={sessionCopy(locale)}
          locale={locale}
          roomId={roomId}
          token={token}
          imageUrl={editingImageUrl}
          fillViewportHeight
          onSaved={(savedMap) => {
            setEditingMap(savedMap)
            void loadMaps()
          }}
          onError={(cause) => {
            setListError(battleMapLibraryErrorMessage(cause, copy))
            if (cause instanceof SessionApiError && cause.status === 409) {
              void loadMaps()
            }
          }}
          onClose={() => {
            setEditingMap(null)
            if (editingImageUrl) {
              URL.revokeObjectURL(editingImageUrl)
              setEditingImageUrl(null)
            }
            void loadMaps()
          }}
        />
      </div>
    )
  }

  return (
    <div className="battle-map-library page">
      <header className="page-header">
        <a className="page-header__back" href={`/rooms/${roomId}`}>
          {copy.backRoom}
        </a>
        <h1>{copy.title}</h1>
        <p className="page-intro">{copy.intro}</p>
      </header>

      <div className="battle-map-library__toolbar">
        <div className="battle-map-library__actions">
          <button
            type="button"
            className="button primary"
            onClick={() => setShowCreateBlankModal(true)}
            data-testid="create-blank-map-btn"
          >
            {copy.createBlankAction}
          </button>
          <button
            type="button"
            className="button secondary"
            onClick={() => setShowCreateImageModal(true)}
            data-testid="create-image-map-btn"
          >
            {copy.createImageAction}
          </button>
          <button
            type="button"
            className="button secondary"
            onClick={() => void loadMaps()}
            data-testid="refresh-maps-btn"
          >
            {copy.refreshAction}
          </button>
        </div>

        <label className="battle-map-library__toggle">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
            data-testid="show-archived-toggle"
          />
          {copy.showArchived}
        </label>
      </div>

      {listError ? (
        <div className="banner error" data-testid="map-library-error">
          {listError}
        </div>
      ) : null}

      {loadingList ? (
        <p className="battle-map-library__loading">{copy.loadingList}</p>
      ) : maps.length === 0 ? (
        <p className="battle-map-library__empty" data-testid="empty-map-list">
          {copy.emptyList}
        </p>
      ) : (
        <div className="battle-map-library__grid" data-testid="map-library-list">
          {maps.map((m) => (
            <div
              key={m.id}
              className={`battle-map-card ${m.archived_at ? 'battle-map-card--archived' : ''}`}
              data-testid={`map-card-${m.id}`}
            >
              <div className="battle-map-card__header">
                <h3 className="battle-map-card__title" data-testid={`map-name-${m.id}`}>
                  {m.name}
                </h3>
                {m.archived_at ? (
                  <span className="badge warning" data-testid={`map-archived-badge-${m.id}`}>
                    {copy.badgeArchived}
                  </span>
                ) : null}
              </div>

              <div className="battle-map-card__meta">
                <span className="battle-map-card__dim">
                  {copy.gridDimensions
                    .replace('{width}', String(m.width_cells))
                    .replace('{height}', String(m.height_cells))}
                </span>
                <span className="battle-map-card__kind">
                  {m.source_kind === 'image' ? copy.sourceImage : copy.sourceBlank}
                </span>
                <span className="battle-map-card__rev">
                  {copy.revisionLabel} {m.revision}
                </span>
              </div>

              <div className="battle-map-card__actions">
                <button
                  type="button"
                  className="button secondary compact"
                  onClick={() => void handleOpenEditor(m.id)}
                  data-testid={`edit-map-btn-${m.id}`}
                >
                  {copy.editAction}
                </button>
                <button
                  type="button"
                  className="button secondary compact"
                  disabled={pendingAction === 'copy'}
                  onClick={() => {
                    setCopyTargetMap(m)
                    setCopyNewName('')
                    setShowCopyModal(true)
                  }}
                  data-testid={`copy-map-btn-${m.id}`}
                >
                  {copy.copyAction}
                </button>
                {!m.archived_at ? (
                  <button
                    type="button"
                    className="button secondary compact"
                    disabled={pendingAction === 'archive'}
                    onClick={() => void handleArchive(m)}
                    data-testid={`archive-map-btn-${m.id}`}
                  >
                    {pendingAction === 'archive' ? copy.archivingAction : copy.archiveAction}
                  </button>
                ) : null}
                <button
                  type="button"
                  className="button danger compact"
                  disabled={pendingAction === 'delete'}
                  onClick={() => void handleDelete(m)}
                  data-testid={`delete-map-btn-${m.id}`}
                >
                  {pendingAction === 'delete' ? copy.deletingAction : copy.deleteAction}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showCreateBlankModal ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal-card">
            <h3>{copy.createBlankModalTitle}</h3>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void handleCreateBlank()
              }}
            >
              <label>
                {copy.modalMapName}
                <input
                  type="text"
                  required
                  value={createBlankName}
                  onChange={(e) => setCreateBlankName(e.target.value)}
                  data-testid="create-blank-map-name"
                  placeholder={copy.modalMapName}
                  autoFocus
                />
              </label>
              <div className="modal-card__row">
                <label>
                  {copy.modalWidthCells}
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={createBlankWidth}
                    onChange={(e) => setCreateBlankWidth(e.target.value)}
                    data-testid="create-blank-map-width"
                  />
                </label>
                <label>
                  {copy.modalHeightCells}
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={createBlankHeight}
                    onChange={(e) => setCreateBlankHeight(e.target.value)}
                    data-testid="create-blank-map-height"
                  />
                </label>
              </div>
              <div className="modal-card__actions">
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => setShowCreateBlankModal(false)}
                >
                  {copy.cancel}
                </button>
                <button
                  type="submit"
                  className="button primary"
                  disabled={pendingAction === 'create' || !createBlankName.trim()}
                  data-testid="create-blank-map-submit"
                >
                  {pendingAction === 'create' ? copy.creatingAction : copy.submitCreate}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {showCreateImageModal ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal-card">
            <h3>{copy.createImageModalTitle}</h3>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void handleCreateImage()
              }}
            >
              <label>
                {copy.modalMapName}
                <input
                  type="text"
                  required
                  value={createImageName}
                  onChange={(e) => setCreateImageName(e.target.value)}
                  data-testid="create-image-map-name"
                  placeholder={copy.modalMapName}
                  autoFocus
                />
              </label>
              <label>
                {copy.modalImageFile}
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  required
                  onChange={(e) => {
                    const file = e.target.files?.[0] ?? null
                    setCreateImageFileAndPreview(file)
                    if (file && !createImageName) {
                      setCreateImageName(file.name.replace(/\.[^/.]+$/, ''))
                    }
                  }}
                  data-testid="create-image-map-file"
                />
              </label>
              {createImagePreviewUrl && createImageNaturalSize ? (
                <div data-testid="create-image-map-preview">
                  <h4>{copy.imagePreviewHeading}</h4>
                  <svg
                    viewBox={`0 0 ${createImageNaturalSize.width} ${createImageNaturalSize.height}`}
                    style={{ width: '100%' }}
                    role="img"
                    aria-label={copy.imagePreviewHeading}
                  >
                    <image
                      href={createImagePreviewUrl}
                      x={0}
                      y={0}
                      width={createImageNaturalSize.width}
                      height={createImageNaturalSize.height}
                      preserveAspectRatio="none"
                    />
                    {previewGridLines(
                      createImageNaturalSize,
                      createImageGrid.pixelSize,
                      createImageGrid.offsetX,
                      createImageGrid.offsetY,
                    ).map((line) => (
                      <line
                        key={line.key}
                        x1={line.x1}
                        y1={line.y1}
                        x2={line.x2}
                        y2={line.y2}
                        className="battle-map__grid-line"
                      />
                    ))}
                  </svg>
                </div>
              ) : null}
              <div className="modal-card__row">
                <label>
                  {copy.gridPixelSizeLabel}
                  <input
                    type="number"
                    min={1}
                    step={1}
                    value={createImageGridSize}
                    placeholder="40"
                    onChange={(e) => setCreateImageGridSize(e.target.value)}
                    data-testid="create-image-map-grid-size"
                  />
                </label>
                <label>
                  {copy.gridOffsetXLabel}
                  <input
                    type="number"
                    step={1}
                    value={createImageOffsetX}
                    placeholder="0"
                    onChange={(e) => setCreateImageOffsetX(e.target.value)}
                    data-testid="create-image-map-grid-offset-x"
                  />
                </label>
                <label>
                  {copy.gridOffsetYLabel}
                  <input
                    type="number"
                    step={1}
                    value={createImageOffsetY}
                    placeholder="0"
                    onChange={(e) => setCreateImageOffsetY(e.target.value)}
                    data-testid="create-image-map-grid-offset-y"
                  />
                </label>
              </div>
              <div className="modal-card__row">
                <label>
                  {copy.modalWidthCells}
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={createImageWidth}
                    onChange={(e) => setCreateImageWidth(e.target.value)}
                    data-testid="create-image-map-width"
                  />
                </label>
                <label>
                  {copy.modalHeightCells}
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={createImageHeight}
                    onChange={(e) => setCreateImageHeight(e.target.value)}
                    data-testid="create-image-map-height"
                  />
                </label>
              </div>
              <div className="modal-card__actions">
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => resetCreateImageModal()}
                >
                  {copy.cancel}
                </button>
                <button
                  type="submit"
                  className="button primary"
                  disabled={pendingAction === 'upload' || !createImageName.trim() || !createImageFile || createImageGridInvalid}
                  data-testid="create-image-map-submit"
                >
                  {pendingAction === 'upload' ? copy.uploadingAction : copy.submitUpload}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {showCopyModal && copyTargetMap ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal-card">
            <h3>{copy.copyModalTitle}</h3>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void handleCopy()
              }}
            >
              <label>
                {copy.modalCopyNameOptional}
                <input
                  type="text"
                  value={copyNewName}
                  onChange={(e) => setCopyNewName(e.target.value)}
                  placeholder={copyTargetMap.name}
                  data-testid="copy-map-name"
                  autoFocus
                />
              </label>
              <div className="modal-card__actions">
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => {
                    setShowCopyModal(false)
                    setCopyTargetMap(null)
                  }}
                >
                  {copy.cancel}
                </button>
                <button
                  type="submit"
                  className="button primary"
                  disabled={pendingAction === 'copy'}
                  data-testid="copy-map-submit"
                >
                  {pendingAction === 'copy' ? copy.copyingAction : copy.submitCopy}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  )
}
