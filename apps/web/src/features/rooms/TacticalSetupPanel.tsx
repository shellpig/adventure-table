import { useCallback, useEffect, useState } from 'react'

import type { BattleMap, BattleMapSummary } from '../../api/battleMaps'
import { createBattleMap, getBattleMap, listBattleMaps } from '../../api/battleMaps'
import { startTacticalCombat, type TacticalStartInput } from '../../api/tacticalCombat'
import { SessionApiError } from '../../api/sessions'
import { BattleMapEditor } from './BattleMapEditor'
import { libraryPermissions } from './RoomBattleMapLibraryPage'
import {
  battleMapLibraryCopy,
  monsterPlacementProblemMessage,
} from './battleMapLibraryCopy'
import { extractPlacementProblems } from './mapMonsterPlacements'
import { recentRoomForId } from './roomStorage'
import type { SessionCopy } from './sessionCopy'
import { requestId } from './requestId'
import type { Locale } from '../../i18n/locale'

export type TacticalStartSelection =
  | { kind: 'library-map'; mapId: string; loadMonsters: boolean }
  | { kind: 'blank'; width: number; height: number }

/**
 * Exact POST body for the tactical start from the panel selection.
 * `load_map_monsters` is only ever true for a library-map source; blank (and
 * temporary) sources always start map-only, matching the server contract.
 */
export function tacticalStartBody(
  selection: TacticalStartSelection,
  idempotencyKey: string,
): TacticalStartInput {
  if (selection.kind === 'blank') {
    return {
      blank_width_cells: selection.width,
      blank_height_cells: selection.height,
      include_active_party: true,
      load_map_monsters: false,
      idempotency_key: idempotencyKey,
    }
  }
  return {
    battle_map_id: selection.mapId,
    include_active_party: true,
    load_map_monsters: selection.loadMonsters,
    idempotency_key: idempotencyKey,
  }
}

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
  const recent = recentRoomForId(roomId)
  const { canManage } = libraryPermissions(recent?.authority)

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
  // M07-C: library-map starts offer map-only vs with-monsters; default map-only.
  const [loadMonsters, setLoadMonsters] = useState(false)
  const [loadProblems, setLoadProblems] = useState<
    Array<{ placement_id: string; code: string }>
  >([])

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
    setLoadProblems([])
    try {
      if (useBlank) {
        const width = Math.max(1, parseInt(blankWidth, 10) || 20)
        const height = Math.max(1, parseInt(blankHeight, 10) || 20)
        await startTacticalCombat(
          roomId,
          campaignId,
          sessionId,
          tacticalStartBody({ kind: 'blank', width, height }, requestId('tactical-start')),
          token,
        )
      } else if (selectedMapId) {
        await startTacticalCombat(
          roomId,
          campaignId,
          sessionId,
          tacticalStartBody(
            { kind: 'library-map', mapId: selectedMapId, loadMonsters },
            requestId('tactical-start'),
          ),
          token,
        )
      } else {
        return
      }
      refresh()
      onClose()
    } catch (cause) {
      if (
        cause instanceof SessionApiError &&
        cause.code === 'map_monster_placement_invalid'
      ) {
        // DM-only problem list; the panel stays open so the DM can fix the
        // library placements and retry with the same selection.
        setLoadProblems(extractPlacementProblems(cause))
      }
      onError(cause)
      if (cause instanceof SessionApiError && cause.code === 'battle_map_archived') {
        void loadMaps()
      }
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
                      setLoadProblems([])
                    }}
                  />
                  {m.name} ({m.width_cells}×{m.height_cells})
                </label>
                {canManage ? (
                  <button
                    type="button"
                    className="button secondary compact"
                    onClick={() => void handleEdit(m.id)}
                    data-testid={`tactical-edit-map-${m.id}`}
                  >
                    {copy.tacticalMapOpenEditor}
                  </button>
                ) : null}
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
            onChange={() => {
              setUseBlank(true)
              setLoadProblems([])
            }}
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

      {canManage ? (
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
      ) : null}

      {selectedMapId && !useBlank ? (
        <div className="tactical-setup__section" data-testid="tactical-load-monsters-option">
          <h4>{copy.tacticalLoadMonstersHeading}</h4>
          <label>
            <input
              type="radio"
              name="tactical-load-monsters"
              checked={!loadMonsters}
              onChange={() => setLoadMonsters(false)}
              data-testid="tactical-load-map-only"
            />
            {copy.tacticalLoadMapOnly}
          </label>
          <label>
            <input
              type="radio"
              name="tactical-load-monsters"
              checked={loadMonsters}
              onChange={() => setLoadMonsters(true)}
              data-testid="tactical-load-with-monsters"
            />
            {copy.tacticalLoadMapWithMonsters}
          </label>
        </div>
      ) : null}

      {loadProblems.length > 0 ? (
        <div
          className="tactical-setup__load-problems"
          data-testid="tactical-load-problems"
        >
          <h4>{copy.tacticalLoadProblemsHeading}</h4>
          <ul>
            {loadProblems.map((problem, index) => (
              <li
                key={`${problem.placement_id}-${problem.code}-${index}`}
                data-placement-id={problem.placement_id}
                data-problem-code={problem.code}
              >
                {problem.placement_id.slice(0, 8)}:{' '}
                {monsterPlacementProblemMessage(
                  problem.code,
                  battleMapLibraryCopy(locale),
                )}
              </li>
            ))}
          </ul>
          <p>{copy.tacticalLoadProblemsRetryHint}</p>
        </div>
      ) : null}

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
