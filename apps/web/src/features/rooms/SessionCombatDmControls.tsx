import { useState } from 'react'

import {
  addMonsterToCombat,
  advanceTurn,
  createMonsterFromContent,
  createQuickEnemy,
  finalizeInitiative,
  getSuggestedInitiativeOrder,
  requestInitiative,
  type CombatDetailView,
} from '../../api/combat'
import { SearchableSelect, type SearchOption } from '../../components/SearchableSelect'
import type { SessionCopy } from './sessionCopy'
import { requestId } from './SessionTableSurface'

type SessionCombatDmControlsProps = {
  combat: CombatDetailView
  copy: SessionCopy
  roomId: string
  campaignId: string
  sessionId: string
  token: string
  monsterOptions: SearchOption[]
  onError: (cause: unknown) => void
  refresh: () => void
}

export function SessionCombatDmControls({
  combat,
  copy,
  roomId,
  campaignId,
  sessionId,
  token,
  monsterOptions,
  onError,
  refresh,
}: SessionCombatDmControlsProps) {
  const [enemyMode, setEnemyMode] = useState<'srd' | 'quick'>('srd')
  const [pending, setPending] = useState(false)

  // SRD monster state
  const [selectedMonsterKey, setSelectedMonsterKey] = useState('')
  const [srdDisplayName, setSrdDisplayName] = useState('')
  const [srdVisibility, setSrdVisibility] = useState<'public' | 'hidden'>('public')
  const [srdPositionNote, setSrdPositionNote] = useState('')

  // Quick enemy state
  const [quickName, setQuickName] = useState('')
  const [quickAc, setQuickAc] = useState('10')
  const [quickMaxHp, setQuickMaxHp] = useState('10')
  const [attackName, setAttackName] = useState('')
  const [attackBonus, setAttackBonus] = useState('')
  const [damage, setDamage] = useState('')
  const [quickVisibility, setQuickVisibility] = useState<'public' | 'hidden'>('public')
  const [quickPositionNote, setQuickPositionNote] = useState('')

  const activeEntries = combat.entries.filter((entry) => entry.status === 'active')
  const canRequestInitiative =
    activeEntries.length > 0 &&
    activeEntries.some(
      (entry) =>
        entry.initiative_roll_request_id === null &&
        typeof entry.initiative_total !== 'number',
    )
  const canFinalizeInitiative =
    activeEntries.length > 0 &&
    activeEntries.every((entry) => typeof entry.initiative_total === 'number')

  const runMutation = async (mutation: () => Promise<void>) => {
    setPending(true)
    try {
      await mutation()
      refresh()
    } catch (cause) {
      onError(cause)
    } finally {
      setPending(false)
    }
  }

  const handleAddSrdMonster = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!selectedMonsterKey) return
    await runMutation(async () => {
      const created = await createMonsterFromContent(
        roomId,
        campaignId,
        sessionId,
        {
          content_key: selectedMonsterKey,
          name: srdDisplayName.trim() || null,
          visibility: srdVisibility,
          position_note: srdPositionNote.trim() || null,
          idempotency_key: requestId('monster-create'),
        },
        token,
      )
      await addMonsterToCombat(
        roomId,
        campaignId,
        sessionId,
        {
          monster_instance_id: created.id,
          idempotency_key: requestId('monster-add'),
        },
        token,
      )
      setSelectedMonsterKey('')
      setSrdDisplayName('')
      setSrdPositionNote('')
      setSrdVisibility('public')
    })
  }

  const handleAddQuickEnemy = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!quickName.trim()) return
    const ac = Number(quickAc)
    const hp = Number(quickMaxHp)
    if (isNaN(ac) || ac < 0 || ac > 30 || isNaN(hp) || hp < 1 || hp > 999) return

    // An attack needs both a name and damage dice; anything less stays a no-attack enemy.
    const trimmedAttackName = attackName.trim()
    const trimmedDamage = damage.trim()
    const attack =
      trimmedAttackName && trimmedDamage
        ? {
            name: trimmedAttackName,
            attack_bonus: attackBonus.trim() !== '' && !isNaN(Number(attackBonus)) ? Number(attackBonus) : null,
            damage: trimmedDamage,
          }
        : null

    await runMutation(async () => {
      const created = await createQuickEnemy(
        roomId,
        campaignId,
        sessionId,
        {
          name: quickName.trim(),
          armor_class: ac,
          max_hp: hp,
          attack,
          visibility: quickVisibility,
          position_note: quickPositionNote.trim() || null,
          idempotency_key: requestId('quick-enemy-create'),
        },
        token,
      )
      await addMonsterToCombat(
        roomId,
        campaignId,
        sessionId,
        {
          monster_instance_id: created.id,
          idempotency_key: requestId('quick-enemy-add'),
        },
        token,
      )
      setQuickName('')
      setQuickAc('10')
      setQuickMaxHp('10')
      setAttackName('')
      setAttackBonus('')
      setDamage('')
      setQuickPositionNote('')
      setQuickVisibility('public')
    })
  }

  const handleRequestInitiative = () =>
    runMutation(async () => {
      await requestInitiative(
        roomId,
        campaignId,
        sessionId,
        { entry_ids: [], modifier_mode: 'normal', idempotency_key: requestId('init-req') },
        token,
      )
    })

  const handleFinalizeInitiative = () =>
    runMutation(async () => {
      const ordered = await getSuggestedInitiativeOrder(roomId, campaignId, sessionId, token)
      await finalizeInitiative(
        roomId,
        campaignId,
        sessionId,
        { ordered_entry_ids: ordered, idempotency_key: requestId('init-finalize') },
        token,
      )
    })

  const handleAdvanceTurn = () =>
    runMutation(async () => {
      await advanceTurn(roomId, campaignId, sessionId, { idempotency_key: requestId('advance-turn') }, token)
    })

  return (
    <div className="session-combat__dm-controls" data-combat-dm-controls="true">
      {combat.status === 'initiative_pending' ? (
        <div className="session-combat__dm-initiative-bar">
          <button
            type="button"
            className="button secondary compact"
            disabled={pending || !canRequestInitiative}
            onClick={() => void handleRequestInitiative()}
          >
            {pending ? copy.combatRequestingInitiative : copy.combatRequestInitiative}
          </button>
          <button
            type="button"
            className="button primary compact"
            disabled={pending || !canFinalizeInitiative}
            onClick={() => void handleFinalizeInitiative()}
          >
            {pending ? copy.combatFinalizingInitiative : copy.combatFinalizeInitiative}
          </button>
          {!canFinalizeInitiative && activeEntries.length > 0 ? (
            <span className="session-combat__dm-hint">{copy.combatAwaitingRollHint}</span>
          ) : null}
        </div>
      ) : null}

      {combat.status === 'running' ? (
        <div className="session-combat__dm-running-bar">
          <button
            type="button"
            className="button secondary compact"
            disabled={pending}
            onClick={() => void handleAdvanceTurn()}
          >
            {pending ? copy.combatAdvancingTurn : copy.combatAdvanceTurn}
          </button>
        </div>
      ) : null}

      <div className="session-combat__add-enemy">
        <h4 className="session-combat__sub-heading">{copy.combatAddEnemyHeading}</h4>
        <div className="session-combat__mode-tabs">
          <button
            type="button"
            className={`session-combat__tab-btn${enemyMode === 'srd' ? ' session-combat__tab-btn--active' : ''}`}
            onClick={() => setEnemyMode('srd')}
          >
            {copy.combatModeSrdMonster}
          </button>
          <button
            type="button"
            className={`session-combat__tab-btn${enemyMode === 'quick' ? ' session-combat__tab-btn--active' : ''}`}
            onClick={() => setEnemyMode('quick')}
          >
            {copy.combatModeQuickEnemy}
          </button>
        </div>

        {enemyMode === 'srd' ? (
          <form className="session-combat__form" onSubmit={handleAddSrdMonster}>
            <SearchableSelect
              label={copy.combatMonsterPickerLabel}
              options={monsterOptions}
              value={selectedMonsterKey}
              onChange={setSelectedMonsterKey}
              placeholder={copy.combatMonsterPickerPlaceholder}
              disabled={pending}
            />
            <div className="session-combat__form-row">
              <label>
                <span>{copy.combatDisplayName}</span>
                <input
                  type="text"
                  value={srdDisplayName}
                  maxLength={120}
                  placeholder={copy.combatDisplayNamePlaceholder}
                  disabled={pending}
                  onChange={(e) => setSrdDisplayName(e.target.value)}
                />
              </label>
              <label>
                <span>{copy.combatVisibility}</span>
                <select
                  value={srdVisibility}
                  disabled={pending}
                  onChange={(e) =>
                    setSrdVisibility(e.target.value === 'hidden' ? 'hidden' : 'public')
                  }
                >
                  <option value="public">{copy.combatVisibilityPublic}</option>
                  <option value="hidden">{copy.combatVisibilityHidden}</option>
                </select>
              </label>
            </div>
            <label>
              <span>{copy.combatPositionNote}</span>
              <input
                type="text"
                value={srdPositionNote}
                maxLength={500}
                placeholder={copy.combatPositionNotePlaceholder}
                disabled={pending}
                onChange={(e) => setSrdPositionNote(e.target.value)}
              />
            </label>
            <div className="session-combat__form-actions">
              <button
                type="submit"
                className="button primary compact"
                disabled={pending || !selectedMonsterKey}
              >
                {pending ? copy.combatAddingEnemy : copy.combatAddEnemyButton}
              </button>
            </div>
          </form>
        ) : (
          <form className="session-combat__form" onSubmit={handleAddQuickEnemy}>
            <div className="session-combat__form-row">
              <label>
                <span>{copy.combatQuickEnemyName}</span>
                <input
                  type="text"
                  value={quickName}
                  maxLength={120}
                  required
                  disabled={pending}
                  onChange={(e) => setQuickName(e.target.value)}
                />
              </label>
              <label>
                <span>{copy.combatQuickEnemyAc}</span>
                <input
                  type="number"
                  min={0}
                  max={30}
                  value={quickAc}
                  required
                  disabled={pending}
                  onChange={(e) => setQuickAc(e.target.value)}
                />
              </label>
              <label>
                <span>{copy.combatQuickEnemyMaxHp}</span>
                <input
                  type="number"
                  min={1}
                  max={999}
                  value={quickMaxHp}
                  required
                  disabled={pending}
                  onChange={(e) => setQuickMaxHp(e.target.value)}
                />
              </label>
            </div>
            <div className="session-combat__form-row">
              <label>
                <span>{copy.combatQuickEnemyAttackName}</span>
                <input
                  type="text"
                  value={attackName}
                  maxLength={120}
                  disabled={pending}
                  onChange={(e) => setAttackName(e.target.value)}
                />
              </label>
              <label>
                <span>{copy.combatQuickEnemyAttackBonus}</span>
                <input
                  type="number"
                  value={attackBonus}
                  disabled={pending}
                  onChange={(e) => setAttackBonus(e.target.value)}
                />
              </label>
              <label>
                <span>{copy.combatQuickEnemyDamage}</span>
                <input
                  type="text"
                  value={damage}
                  maxLength={60}
                  placeholder={copy.combatQuickEnemyDamagePlaceholder}
                  disabled={pending}
                  onChange={(e) => setDamage(e.target.value)}
                />
              </label>
            </div>
            <div className="session-combat__form-row">
              <label>
                <span>{copy.combatVisibility}</span>
                <select
                  value={quickVisibility}
                  disabled={pending}
                  onChange={(e) =>
                    setQuickVisibility(e.target.value === 'hidden' ? 'hidden' : 'public')
                  }
                >
                  <option value="public">{copy.combatVisibilityPublic}</option>
                  <option value="hidden">{copy.combatVisibilityHidden}</option>
                </select>
              </label>
              <label>
                <span>{copy.combatPositionNote}</span>
                <input
                  type="text"
                  value={quickPositionNote}
                  maxLength={500}
                  placeholder={copy.combatPositionNotePlaceholder}
                  disabled={pending}
                  onChange={(e) => setQuickPositionNote(e.target.value)}
                />
              </label>
            </div>
            <div className="session-combat__form-actions">
              <button
                type="submit"
                className="button primary compact"
                disabled={pending || !quickName.trim()}
              >
                {pending ? copy.combatAddingEnemy : copy.combatAddEnemyButton}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
