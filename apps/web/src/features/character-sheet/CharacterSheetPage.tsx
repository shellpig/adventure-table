import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getCharacterSheet,
  listContent,
  patchCharacterState,
} from '../../api/character'
import type {
  CharacterSheetDTO,
  CharacterStatePatch,
  ContentEntry,
  InventoryDTO,
  InventoryStateEntry,
  PreparedSpellSelection,
  ResourceCounter,
} from '../../api/character'
import { SearchableSelect } from '../../components/SearchableSelect'
import type { SearchOption } from '../../components/SearchableSelect'

type CharacterTab = 'attributes' | 'spells' | 'inventory'

type CharacterSheetViewProps = {
  sheet: CharacterSheetDTO
  conditionContent?: ContentEntry[]
  inventoryContent?: ContentEntry[]
  initialTab?: CharacterTab
  busy?: boolean
  errorMessage?: string | null
  onPatch?: (patch: CharacterStatePatch) => Promise<void> | void
}

const ABILITY_LABELS: Record<string, string> = {
  strength: '力量 STR',
  dexterity: '敏捷 DEX',
  constitution: '體質 CON',
  intelligence: '智力 INT',
  wisdom: '感知 WIS',
  charisma: '魅力 CHA',
}

const ACCESS_LABELS: Record<string, string> = {
  known: 'Known',
  spellbook: 'Spellbook',
  prepared: 'Prepared List',
  always_prepared: 'Always Prepared',
  granted: 'Granted',
}

function signed(value: number) {
  return value >= 0 ? `+${value}` : String(value)
}

function titleCase(value: string) {
  return value
    .replaceAll('-', ' ')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function inventoryState(inventory: InventoryDTO[]): InventoryStateEntry[] {
  return inventory.map(({ entry_id, item_ref, quantity, equipped, carried }) => ({
    entry_id,
    item_ref,
    quantity,
    equipped,
    carried,
  }))
}

function countersToPatch(source: Record<string, ResourceCounter>) {
  return Object.fromEntries(
    Object.entries(source).map(([key, value]) => [key, { ...value }]),
  )
}

function describeRules(rules: Record<string, unknown>): string[] {
  const details: string[] = []
  const damage = rules.damage as { damage_dice?: unknown; damage_type?: { name?: unknown } } | undefined
  const armorClass = rules.armor_class as { base?: unknown; dex_bonus?: unknown; max_bonus?: unknown } | undefined
  const cost = rules.cost as { quantity?: unknown; unit?: unknown } | undefined
  const category = rules.equipment_category as { name?: unknown } | undefined

  if (category?.name) details.push(String(category.name))
  if (damage?.damage_dice) {
    details.push(
      `${String(damage.damage_dice)}${damage.damage_type?.name ? ` ${String(damage.damage_type.name)}` : ''}`,
    )
  }
  if (armorClass?.base) {
    const dex = armorClass.dex_bonus ? ' + DEX' : ''
    const cap = armorClass.max_bonus ? ` (max +${String(armorClass.max_bonus)})` : ''
    details.push(`AC ${String(armorClass.base)}${dex}${cap}`)
  }
  if (cost?.quantity !== undefined && cost?.unit) {
    details.push(`${String(cost.quantity)} ${String(cost.unit)}`)
  }
  return details.slice(0, 3)
}

function NumberSaveField({
  label,
  value,
  min = 0,
  max,
  busy,
  testId,
  onSave,
}: {
  label: string
  value: number
  min?: number
  max?: number
  busy?: boolean
  testId?: string
  onSave: (value: number) => Promise<void> | void
}) {
  const [draft, setDraft] = useState(String(value))

  return (
    <form
      className="number-save"
      onSubmit={(event) => {
        event.preventDefault()
        const next = Number(draft)
        if (Number.isFinite(next)) void onSave(next)
      }}
    >
      <label>
        <span>{label}</span>
        <input
          data-testid={testId}
          type="number"
          min={min}
          max={max}
          value={draft}
          disabled={busy}
          onChange={(event) => setDraft(event.target.value)}
        />
      </label>
      <button
        className="button secondary compact"
        type="submit"
        data-testid={testId ? `${testId}-save` : undefined}
        disabled={busy || draft === String(value)}
      >
        儲存
      </button>
    </form>
  )
}

export function CharacterSheetView({
  sheet,
  conditionContent = [],
  inventoryContent = [],
  initialTab = 'attributes',
  busy = false,
  errorMessage = null,
  onPatch = async () => {},
}: CharacterSheetViewProps) {
  const [tab, setTab] = useState<CharacterTab>(initialTab)
  const [conditionRef, setConditionRef] = useState('')
  const [conditionNote, setConditionNote] = useState('')
  const [itemRef, setItemRef] = useState('')
  const [spellFilter, setSpellFilter] = useState('')
  const [inventoryFilter, setInventoryFilter] = useState('')

  const conditionOptions = useMemo<SearchOption[]>(
    () =>
      conditionContent.map((entry) => ({
        value: entry.key,
        label: entry.name,
      })),
    [conditionContent],
  )

  const inventoryOptions = useMemo<SearchOption[]>(
    () =>
      inventoryContent.map((entry) => ({
        value: entry.key,
        label: entry.name,
        description: String((entry.data.equipment_category as { name?: unknown } | undefined)?.name ?? ''),
      })),
    [inventoryContent],
  )

  const classSummary = sheet.classes.map((entry) => `${entry.name} ${entry.level}`).join(' / ')
  const classNameByRef = new Map(sheet.classes.map((entry) => [entry.class_ref, entry.name]))
  const preparedIds = sheet.spells
    .filter((spell) => spell.access_type === 'spellbook' && spell.prepared && !spell.source_profile_id)
    .map((spell) => spell.entry_id)
  const preparedSelections: PreparedSpellSelection[] = sheet.spells
    .filter(
      (spell) =>
        spell.prepared &&
        Boolean(spell.source_profile_id) &&
        (spell.access_type === 'spellbook' || spell.access_type === 'prepared'),
    )
    .map((spell) => ({
      spell_key: spell.spell_key,
      source_profile_id: spell.source_profile_id as string,
      source_access_entry_id: spell.source_access_entry_id ?? undefined,
    }))
  const filteredSpells = sheet.spells.filter((spell) =>
    `${spell.name} ${ACCESS_LABELS[spell.access_type] ?? spell.access_type}`
      .toLocaleLowerCase()
      .includes(spellFilter.toLocaleLowerCase()),
  )
  const filteredInventory = sheet.inventory.filter((item) =>
    item.name.toLocaleLowerCase().includes(inventoryFilter.toLocaleLowerCase()),
  )

  const patchInventory = (next: InventoryStateEntry[]) => onPatch({ inventory_state: next })
  const mutateInventoryItem = (entryId: string, update: Partial<InventoryStateEntry>) => {
    const next = inventoryState(sheet.inventory).map((entry) =>
      entry.entry_id === entryId ? { ...entry, ...update } : entry,
    )
    return patchInventory(next)
  }

  const updateCounter = (
    key: string,
    source: Record<string, ResourceCounter>,
    direction: 'use' | 'restore',
    field: 'spell_slots' | 'resources',
  ) => {
    const current = source[key]
    if (!current) return
    const next = countersToPatch(source)
    if (direction === 'use' && current.remaining > 0) {
      next[key] = { used: current.used + 1, remaining: current.remaining - 1 }
    } else if (direction === 'restore' && current.used > 0) {
      next[key] = { used: current.used - 1, remaining: current.remaining + 1 }
    } else {
      return
    }
    return onPatch({ [field]: next })
  }

  return (
    <main className="character-page">
      <div className="ambient ambient-one" />
      <div className="ambient ambient-two" />

      <section className="sheet-shell" aria-label={`${sheet.name} 角色卡`}>
        <header className="character-hero">
          <div className="hero-copy">
            <p className="eyebrow">Adventure Table · Character Sheet</p>
            <h1>{sheet.name}</h1>
            <p className="character-meta">
              <strong>Lv. {sheet.total_level}</strong>
              <span>{classSummary}</span>
              <span>PB {signed(sheet.proficiency_bonus)}</span>
              <span>Build v{sheet.version_no}</span>
            </p>
          </div>

          <div className="hero-stats" aria-label="角色即時狀態">
            <div className="hero-stat hp-stat">
              <span>HP</span>
              <strong data-testid="header-hp">{sheet.current_hp}</strong>
              <small>/ {sheet.max_hp}</small>
            </div>
            <div className="hero-stat">
              <span>Temp</span>
              <strong data-testid="header-temp-hp">{sheet.temporary_hp}</strong>
            </div>
            <div className="hero-stat">
              <span>AC</span>
              <strong data-testid="header-ac">{sheet.armor_class}</strong>
            </div>
            <div className="hero-stat">
              <span>Init</span>
              <strong>{signed(sheet.initiative_modifier)}</strong>
            </div>
          </div>

          <div className="hero-live-row">
            <div className="hero-editors">
              <NumberSaveField
                label="目前 HP"
                value={sheet.current_hp}
                min={0}
                max={sheet.max_hp}
                busy={busy}
                testId="current-hp-input"
                onSave={(value) => onPatch({ current_hp: value })}
              />
              <NumberSaveField
                label="暫時 HP"
                value={sheet.temporary_hp}
                min={0}
                busy={busy}
                testId="temporary-hp-input"
                onSave={(value) => onPatch({ temporary_hp: value })}
              />
            </div>
            <div className="condition-strip" aria-label="Conditions">
              <span className="condition-label">Conditions</span>
              {sheet.conditions.length ? (
                sheet.conditions.map((condition) => (
                  <button
                    type="button"
                    className="condition-chip"
                    key={condition.condition_ref}
                    title={condition.note ? `${condition.note} · 點擊移除` : '點擊移除'}
                    disabled={busy}
                    onClick={() =>
                      onPatch({
                        conditions: sheet.conditions
                          .filter((entry) => entry.condition_ref !== condition.condition_ref)
                          .map((entry) => ({ condition_ref: entry.condition_ref, note: entry.note })),
                      })
                    }
                  >
                    {condition.name} ×
                  </button>
                ))
              ) : (
                <span className="quiet-pill">無</span>
              )}
            </div>
          </div>
        </header>

        {errorMessage ? <div className="error-banner" role="alert">{errorMessage}</div> : null}

        <nav className="sheet-tabs" role="tablist" aria-label="角色卡分頁">
          {([
            ['attributes', '屬性與技能', '01'],
            ['spells', '法術', '02'],
            ['inventory', '物品欄', '03'],
          ] as const).map(([value, label, number]) => (
            <button
              key={value}
              role="tab"
              type="button"
              aria-selected={tab === value}
              className={tab === value ? 'sheet-tab is-active' : 'sheet-tab'}
              onClick={() => setTab(value)}
            >
              <span>{number}</span>
              {label}
            </button>
          ))}
        </nav>

        {tab === 'attributes' ? (
          <section className="sheet-content" role="tabpanel" aria-label="屬性與技能">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Core Profile</p>
                <h2>屬性與技能</h2>
              </div>
              <div className="passive-card">
                <span>Passive Perception</span>
                <strong>{sheet.passive_perception}</strong>
              </div>
            </div>

            <div className="ability-grid">
              {Object.entries(sheet.abilities).map(([key, ability]) => (
                <article className="ability-card" key={key}>
                  <span>{ABILITY_LABELS[key] ?? titleCase(key)}</span>
                  <strong>{signed(ability.modifier)}</strong>
                  <small>Score {ability.score}</small>
                </article>
              ))}
            </div>

            <div className="two-column-grid">
              <article className="panel">
                <div className="panel-title"><h3>Saving Throws</h3><span>豁免</span></div>
                <div className="stat-list">
                  {Object.entries(sheet.saving_throws).map(([key, value]) => (
                    <div key={key}><span>{ABILITY_LABELS[key] ?? titleCase(key)}</span><strong>{signed(value)}</strong></div>
                  ))}
                </div>
              </article>
              <article className="panel">
                <div className="panel-title"><h3>Skills</h3><span>技能</span></div>
                <div className="stat-list skill-list">
                  {Object.entries(sheet.skills).map(([key, value]) => (
                    <div key={key}><span>{titleCase(key)}</span><strong>{signed(value)}</strong></div>
                  ))}
                </div>
              </article>
            </div>

            <div className="two-column-grid">
              <article className="panel">
                <div className="panel-title"><h3>Hit Dice</h3><span>Available / Total</span></div>
                <div className="dice-grid">
                  {sheet.hit_dice.map((hitDie) => (
                    <div className="die-card" key={hitDie.die}>
                      <strong>{hitDie.die}</strong>
                      <span data-testid={`hit-die-${hitDie.die}`}>{hitDie.available}/{hitDie.total}</span>
                      <div className="stepper">
                        <button
                          type="button"
                          aria-label={`${hitDie.die} 使用一顆`}
                          disabled={busy || hitDie.available <= 0}
                          onClick={() => {
                            const next = Object.fromEntries(sheet.hit_dice.map((entry) => [entry.die, entry.available]))
                            next[hitDie.die] = hitDie.available - 1
                            void onPatch({ hit_dice_state: next })
                          }}
                        >−</button>
                        <button
                          type="button"
                          aria-label={`${hitDie.die} 恢復一顆`}
                          disabled={busy || hitDie.available >= hitDie.total}
                          onClick={() => {
                            const next = Object.fromEntries(sheet.hit_dice.map((entry) => [entry.die, entry.available]))
                            next[hitDie.die] = hitDie.available + 1
                            void onPatch({ hit_dice_state: next })
                          }}
                        >+</button>
                      </div>
                    </div>
                  ))}
                </div>
              </article>

              <article className="panel">
                <div className="panel-title"><h3>Conditions</h3><span>即時狀態</span></div>
                <SearchableSelect
                  label="新增狀態"
                  options={conditionOptions}
                  value={conditionRef}
                  onChange={setConditionRef}
                  disabled={busy}
                />
                <label className="text-field">
                  <span>備註（選填）</span>
                  <input
                    value={conditionNote}
                    placeholder="來源、持續時間…"
                    disabled={busy}
                    onChange={(event) => setConditionNote(event.target.value)}
                  />
                </label>
                <button
                  type="button"
                  className="button primary full"
                  disabled={busy || !conditionRef || sheet.conditions.some((entry) => entry.condition_ref === conditionRef)}
                  onClick={async () => {
                    await onPatch({
                      conditions: [
                        ...sheet.conditions.map((entry) => ({ condition_ref: entry.condition_ref, note: entry.note })),
                        { condition_ref: conditionRef, note: conditionNote.trim() || undefined },
                      ],
                    })
                    setConditionRef('')
                    setConditionNote('')
                  }}
                >
                  加入 Condition
                </button>
              </article>
            </div>

            <article className="panel feature-panel">
              <div className="panel-title"><h3>Features & Traits</h3><span>角色能力</span></div>
              <div className="feature-chips">
                {sheet.features.length ? sheet.features.map((feature) => <span key={feature.key}>{feature.name}</span>) : <em>無資料</em>}
              </div>
            </article>

            <details className="roleplay-panel">
              <summary>
                <span><strong>Roleplay / Biography</strong><small>選填資料，不影響角色可用性</small></span>
                <span>展開</span>
              </summary>
              <div className="roleplay-grid">
                {sheet.roleplay_profile.appearance ? <div><span>Appearance</span><p>{sheet.roleplay_profile.appearance}</p></div> : null}
                {sheet.roleplay_profile.biography ? <div><span>Biography</span><p>{sheet.roleplay_profile.biography}</p></div> : null}
                {sheet.roleplay_profile.personality_traits.length ? <div><span>Personality</span><p>{sheet.roleplay_profile.personality_traits.join(' · ')}</p></div> : null}
                {sheet.roleplay_profile.ideals.length ? <div><span>Ideals</span><p>{sheet.roleplay_profile.ideals.join(' · ')}</p></div> : null}
                {sheet.roleplay_profile.bonds.length ? <div><span>Bonds</span><p>{sheet.roleplay_profile.bonds.join(' · ')}</p></div> : null}
                {sheet.roleplay_profile.flaws.length ? <div><span>Flaws</span><p>{sheet.roleplay_profile.flaws.join(' · ')}</p></div> : null}
                {!sheet.roleplay_profile.appearance &&
                !sheet.roleplay_profile.biography &&
                !sheet.roleplay_profile.personality_traits.length &&
                !sheet.roleplay_profile.ideals.length &&
                !sheet.roleplay_profile.bonds.length &&
                !sheet.roleplay_profile.flaws.length ? (
                  <p className="empty-copy">尚未填寫角色扮演資料。</p>
                ) : null}
              </div>
            </details>
          </section>
        ) : null}

        {tab === 'spells' ? (
          <section className="sheet-content" role="tabpanel" aria-label="法術">
            <div className="section-heading">
              <div><p className="eyebrow">Spellbook & Resources</p><h2>法術</h2></div>
              <label className="inline-search"><span>搜尋法術</span><input value={spellFilter} placeholder="名稱或類型" onChange={(event) => setSpellFilter(event.target.value)} /></label>
            </div>

            <div className="spellcasting-grid">
              {sheet.spellcasting.map((source) => (
                <article className="spellcasting-card" key={source.source_key}>
                  <span>{source.source_name}</span>
                  <strong>{titleCase(source.ability)}</strong>
                  <div><small>Save DC</small><b>{source.save_dc}</b><small>Attack</small><b>{signed(source.attack_modifier)}</b></div>
                </article>
              ))}
            </div>

            <article className="panel">
              <div className="panel-title"><h3>Spell Slots</h3><span>Server State</span></div>
              <div className="slot-grid">
                {Object.entries(sheet.spell_slots).sort(([a], [b]) => Number(a) - Number(b)).map(([level, counter]) => (
                  <div className="slot-card" key={level}>
                    <span>Level {level}</span>
                    <strong data-testid={`spell-slot-${level}-counter`}>{counter.remaining} / {counter.used + counter.remaining}</strong>
                    <small>Remaining / Total</small>
                    <div className="slot-actions">
                      <button type="button" data-testid={`spell-slot-${level}-use`} disabled={busy || counter.remaining <= 0} onClick={() => void updateCounter(level, sheet.spell_slots, 'use', 'spell_slots')}>使用 1 格</button>
                      <button type="button" disabled={busy || counter.used <= 0} onClick={() => void updateCounter(level, sheet.spell_slots, 'restore', 'spell_slots')}>恢復 1 格</button>
                    </div>
                  </div>
                ))}
              </div>
            </article>

            {Object.keys(sheet.resources).length ? (
              <article className="panel">
                <div className="panel-title"><h3>Class Resources</h3><span>資源</span></div>
                <div className="resource-list">
                  {Object.entries(sheet.resources).map(([key, counter]) => (
                    <div key={key}>
                      <span>{titleCase(key.split(':').at(-1) ?? key)}</span>
                      <strong>{counter.remaining} / {counter.used + counter.remaining}</strong>
                      <div className="mini-actions">
                        <button type="button" disabled={busy || counter.remaining <= 0} onClick={() => void updateCounter(key, sheet.resources, 'use', 'resources')}>使用</button>
                        <button type="button" disabled={busy || counter.used <= 0} onClick={() => void updateCounter(key, sheet.resources, 'restore', 'resources')}>恢復</button>
                      </div>
                    </div>
                  ))}
                </div>
              </article>
            ) : null}

            <div className="spell-list">
              {filteredSpells.map((spell) => {
                const canonicalPrepare =
                  (spell.access_type === 'spellbook' || spell.access_type === 'prepared') &&
                  Boolean(spell.source_profile_id)
                const legacyPrepare = spell.access_type === 'spellbook' && !spell.source_profile_id
                const canPrepare = canonicalPrepare || legacyPrepare
                return (
                  <article className={spell.prepared ? 'spell-card is-prepared' : 'spell-card'} key={spell.entry_id}>
                    <div>
                      <span className="access-badge">{ACCESS_LABELS[spell.access_type] ?? spell.access_type}</span>
                      <h3>{spell.name}</h3>
                      <p>{classNameByRef.get(spell.source_key) ?? titleCase(spell.source_type)} · {spell.source_type}</p>
                    </div>
                    <div className="prepared-control">
                      <span className={spell.prepared ? 'prepared-badge on' : 'prepared-badge'}>{spell.prepared ? 'Prepared' : 'Unprepared'}</span>
                      {canPrepare ? (
                        <button
                          type="button"
                          className="button secondary compact"
                          disabled={busy}
                          onClick={() => {
                            if (canonicalPrepare && spell.source_profile_id) {
                              const next = spell.prepared
                                ? preparedSelections.filter(
                                    (selection) =>
                                      selection.source_profile_id !== spell.source_profile_id ||
                                      selection.spell_key !== spell.spell_key,
                                  )
                                : [
                                    ...preparedSelections,
                                    {
                                      spell_key: spell.spell_key,
                                      source_profile_id: spell.source_profile_id,
                                      source_access_entry_id: spell.source_access_entry_id ?? undefined,
                                    },
                                  ]
                              void onPatch({ prepared_spells: next })
                              return
                            }
                            const next = spell.prepared
                              ? preparedIds.filter((entryId) => entryId !== spell.entry_id)
                              : [...preparedIds, spell.entry_id]
                            void onPatch({ prepared_spell_entry_ids: next })
                          }}
                        >
                          {spell.prepared ? '取消準備' : '準備'}
                        </button>
                      ) : null}
                    </div>
                  </article>
                )
              })}
              {!filteredSpells.length ? <p className="empty-copy">沒有符合搜尋條件的法術。</p> : null}
            </div>
          </section>
        ) : null}

        {tab === 'inventory' ? (
          <section className="sheet-content" role="tabpanel" aria-label="物品欄">
            <div className="section-heading">
              <div><p className="eyebrow">Live Inventory</p><h2>物品欄</h2></div>
              <label className="inline-search"><span>搜尋持有物</span><input value={inventoryFilter} placeholder="例如 Shield" onChange={(event) => setInventoryFilter(event.target.value)} /></label>
            </div>

            <article className="panel add-inventory-panel">
              <div className="panel-title"><h3>加入物品</h3><span>SRD Reference</span></div>
              <div className="add-inventory-row">
                <SearchableSelect label="物品名稱" options={inventoryOptions} value={itemRef} onChange={setItemRef} disabled={busy} />
                <button
                  type="button"
                  className="button primary"
                  disabled={busy || !itemRef}
                  onClick={async () => {
                    const entryId = `inventory:ui:${typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : Date.now()}`
                    await patchInventory([
                      ...inventoryState(sheet.inventory),
                      { entry_id: entryId, item_ref: itemRef, quantity: 1, equipped: false, carried: true },
                    ])
                    setItemRef('')
                  }}
                >
                  ＋ 加入 Inventory
                </button>
              </div>
            </article>

            <div className="inventory-list">
              {filteredInventory.map((item) => {
                const ruleDetails = describeRules(item.rules)
                return (
                  <article className="inventory-card" key={item.entry_id} data-testid={`inventory-${item.entry_id}`}>
                    <div className="inventory-main">
                      <div className="item-monogram" aria-hidden="true">{item.name.slice(0, 1)}</div>
                      <div>
                        <h3>{item.name}</h3>
                        <p>{ruleDetails.length ? ruleDetails.join(' · ') : 'SRD item'}</p>
                        <div className="item-badges">
                          <span className={item.equipped ? 'item-badge active' : 'item-badge'}>{item.equipped ? 'Equipped' : 'Unequipped'}</span>
                          <span className={item.carried ? 'item-badge active' : 'item-badge'}>{item.carried ? 'Carried' : 'Stored'}</span>
                        </div>
                      </div>
                    </div>
                    <div className="inventory-actions">
                      <div className="quantity-stepper">
                        <span>Qty</span>
                        <button type="button" aria-label={`${item.name} 數量減一`} data-testid={`inventory-${item.entry_id}-decrement`} disabled={busy || item.quantity <= 1} onClick={() => void mutateInventoryItem(item.entry_id, { quantity: item.quantity - 1 })}>−</button>
                        <strong data-testid={`inventory-${item.entry_id}-quantity`}>{item.quantity}</strong>
                        <button type="button" aria-label={`${item.name} 數量加一`} disabled={busy} onClick={() => void mutateInventoryItem(item.entry_id, { quantity: item.quantity + 1 })}>＋</button>
                      </div>
                      <button type="button" className="button secondary compact" data-testid={`inventory-${item.entry_id}-equip`} disabled={busy} onClick={() => void mutateInventoryItem(item.entry_id, { equipped: !item.equipped })}>{item.equipped ? 'Unequip' : 'Equip'}</button>
                      <button type="button" className="button secondary compact" disabled={busy} onClick={() => void mutateInventoryItem(item.entry_id, { carried: !item.carried })}>{item.carried ? '放下' : '攜帶'}</button>
                      <button type="button" className="icon-danger" aria-label={`移除 ${item.name}`} disabled={busy} onClick={() => void patchInventory(inventoryState(sheet.inventory).filter((entry) => entry.entry_id !== item.entry_id))}>×</button>
                    </div>
                  </article>
                )
              })}
              {!filteredInventory.length ? <p className="empty-copy">沒有符合搜尋條件的物品。</p> : null}
            </div>
          </section>
        ) : null}

        <footer className="sheet-footer">
          <span>Ruleset: {sheet.ruleset}</span>
          <span>Server authoritative state</span>
          {busy ? <strong>Saving…</strong> : <strong>Synced</strong>}
        </footer>
      </section>
    </main>
  )
}

export function CharacterSheetPage({ characterId }: { characterId: string }) {
  const queryClient = useQueryClient()
  const sheetQuery = useQuery({
    queryKey: ['character-sheet', characterId],
    queryFn: () => getCharacterSheet(characterId),
  })
  const conditionQuery = useQuery({
    queryKey: ['rules-content', 'conditions'],
    queryFn: () => listContent('conditions'),
  })
  const equipmentQuery = useQuery({
    queryKey: ['rules-content', 'equipment'],
    queryFn: () => listContent('equipment'),
  })
  const itemQuery = useQuery({
    queryKey: ['rules-content', 'magic-items'],
    queryFn: () => listContent('magic-items'),
  })

  const mutation = useMutation({
    mutationFn: (patch: CharacterStatePatch) => patchCharacterState(characterId, patch),
    onSuccess: (authoritativeSheet) => {
      queryClient.setQueryData(['character-sheet', characterId], authoritativeSheet)
    },
  })

  if (sheetQuery.isPending) {
    return (
      <main className="character-page loading-page">
        <div className="loading-card"><span className="loading-mark">AT</span><h1>讀取角色卡…</h1><p>正在取得 Server authoritative state</p></div>
      </main>
    )
  }

  if (sheetQuery.isError || !sheetQuery.data) {
    return (
      <main className="character-page loading-page">
        <div className="loading-card error-state"><span className="loading-mark">!</span><h1>無法開啟角色卡</h1><p>{sheetQuery.error instanceof Error ? sheetQuery.error.message : '未知錯誤'}</p></div>
      </main>
    )
  }

  const contentError = [conditionQuery.error, equipmentQuery.error, itemQuery.error].find(Boolean)
  const mutationError = mutation.error
  const errorMessage = mutationError instanceof Error
    ? mutationError.message
    : contentError instanceof Error
      ? `選單資料載入失敗：${contentError.message}`
      : null

  return (
    <CharacterSheetView
      sheet={sheetQuery.data}
      conditionContent={conditionQuery.data ?? []}
      inventoryContent={[...(equipmentQuery.data ?? []), ...(itemQuery.data ?? [])]}
      busy={mutation.isPending}
      errorMessage={errorMessage}
      onPatch={async (patch) => {
        await mutation.mutateAsync(patch)
      }}
    />
  )
}
