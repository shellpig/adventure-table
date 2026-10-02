import { useCallback, useEffect, useState } from 'react'

import type { BattleMap, BattleMapSummary } from '../../api/battleMaps'
import { createBattleMap, getBattleMap, listBattleMaps } from '../../api/battleMaps'
import { startTacticalCombat } from '../../api/tacticalCombat'
import { BattleMapEditor } from './BattleMapEditor'
import type { SessionCopy } from './sessionCopy'
import { requestId } from './requestId'
import type { Locale } from '../../i18n/locale'

type TacticalSetupPanelProps = {
  copy: SessionCopy
  locale: Locale
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  onError: (cause: unknown) => void
  refresh: () => void
  onClose: () => void
}

export function TacticalSetupPanel({
  copy,
  locale,
  roomId,
  campaignId,
  sessionId,
  token,
  onError,
  refresh,
  onClose,
}: TacticalSetupPanelProps) {
  const [maps, setMaps] = useState<BattleMapSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedMapId, setSelectedMapId] = useState<string | null>(null)
  const [useBlank, setUseBlank] = useState(false)
  const [blankWidth, setBlankWidth] = useState('20')
  const [blankHeight, setBlankHeight] = useState('20')
  const [starting, setStarting] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newMapName, setNewMapName] = useState('')
  const [editingMap, setEditingMap] = useState<BattleMap | null>(null)

  const loadMaps = useCallback(async () => {
    setLoading(true)
    try {
      const list = await listBattleMaps(roomId, token)
      setMaps(list)
    } catch (cause) {
      onError(cause)
    } finally {
      setLoading(false)
    }
  }, [roomId, token, onError])

  useEffect(() => {
    void loadMaps()
  }, [loadMaps])

  const handleCreateBlank = async () => {
    const name = newMapName.trim()
    if (!name || creating) return
    setCreating(true)
    try {
      const width = Math.max(1, parseInt(blankWidth, 10) || 20)
      const height = Math.max(1, parseInt(blankHeight, 10) || 20)
      await createBattleMap(
        roomId,
        { name, source_kind: 'blank', width_cells: width, height_cells: height },
        token,
      )
      setNewMapName('')
      await loadMaps()
    } catch (cause) {
      onError(cause)
    } finally {
      setCreating(false)
    }
  }

  const handleEdit = async (mapId: string) => {
    try {
      const map = await getBattleMap(roomId, mapId, token)
      setEditingMap(map)
    } catch (cause) {
      onError(cause)
    }
  }

  const handleStart = async () => {
    if (starting) return
    setStarting(true)
    try {
      if (useBlank) {
        const width = Math.max(1, parseInt(blankWidth, 10) || 20)
        const height = Math.max(1, parseInt(blankHeight, 10) || 20)
        await startTacticalCombat(
          roomId,
          campaignId,
          sessionId,
          {
            blank_width_cells: width,
            blank_height_cells: height,
            include_active_party: true,
            idempotency_key: requestId('tactical-start'),
          },
          token,
        )
      } else if (selectedMapId) {
        await startTacticalCombat(
          roomId,
          campaignId,
          sessionId,
          {
            battle_map_id: selectedMapId,
            include_active_party: true,
            idempotency_key: requestId('tactical-start'),
          },
          token,
        )
      } else {
        return
      }
      refresh()
      onClose()
    } catch (cause) {
      onError(cause)
    } finally {
      setStarting(false)
    }
  }

  if (editingMap) {
    return (
      <BattleMapEditor
        map={editingMap}
        copy={copy}
        locale={locale}
        roomId={roomId}
        token={token}
        onSaved={(saved) => {
          setEditingMap(saved)
          void loadMaps()
        }}
        onError={onError}
        onClose={() => setEditingMap(null)}
      />
    )
  }

  return (
    <section className="tactical-setup" aria-label={copy.tacticalStartButton}>
      <header className="tactical-setup__header">
        <h3>{copy.tacticalStartButton}</h3>
        <button
          type="button"
          className="button secondary compact"
          onClick={onClose}
          aria-label={copy.close}
        >
          ×
        </button>
      </header>

      <div className="tactical-setup__section">
        <h4>{copy.tacticalMapListHeading}</h4>
        {loading ? (
          <p>{copy.tacticalBoardLoading}</p>
        ) : maps.length === 0 ? (
          <p>{copy.tacticalMapListEmpty}</p>
        ) : (
          <ul className="tactical-setup__map-list">
            {maps.map((m) => (
              <li key={m.id} data-testid={`tactical-map-${m.id}`}>
                <label>
                  <input
                    type="radio"
                    name="tactical-map"
                    checked={selectedMapId === m.id && !useBlank}
                    onChange={() => {
                      setSelectedMapId(m.id)
                      setUseBlank(false)
                    }}
                  />
                  {m.name} ({m.width_cells}×{m.height_cells})
                </label>
                <button
                  type="button"
                  className="button secondary compact"
                  onClick={() => void handleEdit(m.id)}
                  data-testid={`tactical-edit-map-${m.id}`}
                >
                  {copy.tacticalMapOpenEditor}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="tactical-setup__section">
        <label>
          <input
            type="radio"
            name="tactical-map"
            checked={useBlank}
            onChange={() => setUseBlank(true)}
          />
          {copy.tacticalStartBlank}
        </label>
        {useBlank ? (
          <div className="tactical-setup__blank-dims">
            <label>
              {copy.tacticalMapWidth}:
              <input
                type="number"
                min={1}
                max={200}
                value={blankWidth}
                onChange={(e) => setBlankWidth(e.target.value)}
              />
            </label>
            <label>
              {copy.tacticalMapHeight}:
              <input
                type="number"
                min={1}
                max={200}
                value={blankHeight}
                onChange={(e) => setBlankHeight(e.target.value)}
              />
            </label>
          </div>
        ) : null}
      </div>

      <div className="tactical-setup__section">
        <h4>{copy.tacticalMapCreate}</h4>
        <div className="tactical-setup__create-row">
          <input
            type="text"
            placeholder={copy.tacticalMapName}
            value={newMapName}
            onChange={(e) => setNewMapName(e.target.value)}
            data-testid="tactical-new-map-name"
          />
          <button
            type="button"
            className="button secondary compact"
            disabled={creating || !newMapName.trim()}
            onClick={() => void handleCreateBlank()}
            data-testid="tactical-create-map"
          >
            {creating ? copy.tacticalMapSaving : copy.tacticalMapCreate}
          </button>
        </div>
      </div>

      <div className="tactical-setup__actions">
        <button
          type="button"
          className="button primary"
          disabled={starting || (!useBlank && !selectedMapId)}
          onClick={() => void handleStart()}
          data-testid="tactical-start-confirm"
        >
          {starting ? copy.tacticalStarting : copy.tacticalStartButton}
        </button>
      </div>
    </section>
  )
}
