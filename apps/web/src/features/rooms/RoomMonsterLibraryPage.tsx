import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'

import {
  archiveCustomMonster,
  copyCustomMonster,
  createCustomMonster,
  createCustomMonsterFromContent,
  deleteCustomMonster,
  getMonsterLibraryEntry,
  listMonsterLibrary,
  patchCustomMonster,
  type CreateCustomMonsterInput,
  type MonsterLibraryDetailView,
  type MonsterLibraryListOptions,
  type MonsterLibrarySummaryView,
  type PatchCustomMonsterInput,
} from '../../api/monsterLibrary'
import type { RoomAuthority } from '../../api/rooms'
import { useLocale } from '../../i18n/LocaleProvider'
import {
  customMonsterFormFromDetail,
  customMonsterScalarPatch,
  monsterSpeedString,
  type CustomMonsterFormValues,
} from './monsterLibraryForm'
import {
  CHALLENGE_RATINGS,
  formatAbilityName,
  formatChallengeRating,
  formatMonsterName,
  formatMonsterRuleField,
  formatWalkSpeed,
  monsterLibraryCopy,
  monsterLibraryErrorMessage,
  SRD_ALIGNMENTS,
  SRD_SIZES,
  SRD_TYPES,
  type MonsterLibraryCopy,
} from './monsterLibraryCopy'
import {
  clampListWidth,
  MAX_LIST_WIDTH,
  MIN_LIST_WIDTH,
  readListWidth,
  resolveKeyboardListWidth,
  writeListWidth,
} from './monsterLibraryLayout'
import { recentRoomForId } from './roomStorage'
import './rooms.css'

const UUID_PATTERN = '[0-9a-fA-F-]{36}'

export type RoomMonsterLibraryRoute = {
  roomId: string
}

type EditableMonsterAbility = {
  sourceIndex: number | null
  name: string
  desc: string
}

function toEditableAbilities(
  items: Array<{ name: string; desc?: string | null }> | undefined,
): EditableMonsterAbility[] {
  if (!Array.isArray(items)) return []
  return items
    .filter((item) => typeof item === 'object' && item !== null)
    .map((item, sourceIndex) => ({
      sourceIndex,
      name: typeof item.name === 'string' ? item.name : '',
      desc: typeof item.desc === 'string' ? item.desc : '',
    }))
}

export function roomMonsterLibraryRouteFromPath(
  pathname: string,
): RoomMonsterLibraryRoute | null {
  const match = pathname.match(
    new RegExp(`^/rooms/(${UUID_PATTERN})/monster-library/?$`),
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

function formatModifier(score: number): string {
  const mod = Math.floor((score - 10) / 2)
  return mod >= 0 ? `+${mod}` : `${mod}`
}

export type RoomMonsterLibraryPageProps = {
  roomId: string
}

export function RoomMonsterLibraryPage({ roomId }: RoomMonsterLibraryPageProps) {
  const { locale } = useLocale()
  const copy = monsterLibraryCopy(locale)
  const recent = recentRoomForId(roomId)
  const token = recent?.accessToken ?? ''
  const { canManage } = libraryPermissions(recent?.authority)

  const [monsters, setMonsters] = useState<MonsterLibrarySummaryView[]>([])
  const [loadingList, setLoadingList] = useState(false)
  const [listError, setListError] = useState<string | null>(null)

  const [searchQuery, setSearchQuery] = useState('')
  const [sourceFilter, setSourceFilter] = useState<'all' | 'builtin' | 'custom'>('all')
  const [showArchived, setShowArchived] = useState(false)

  // D.4 sort & filter ('' = all/unlimited; any change resets to offset 0)
  const [sortField, setSortField] = useState('name')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc')
  const [sizeFilter, setSizeFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [crMode, setCrMode] = useState<'any' | 'eq' | 'range'>('any')
  const [crEq, setCrEq] = useState('0')
  const [crMin, setCrMin] = useState('')
  const [crMax, setCrMax] = useState('')

  // CR range guards the fetch: min > max shows an inline message and skips
  // the request instead of sending an invalid combination to the server.
  const crRangeInvalid =
    crMode === 'range' && crMin !== '' && crMax !== '' && Number(crMin) > Number(crMax)

  const [selectedRef, setSelectedRef] = useState<string | null>(null)
  const [detail, setDetail] = useState<MonsterLibraryDetailView | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [actionNotice, setActionNotice] = useState<string | null>(null)

  const [pendingAction, setPendingAction] = useState<
    'create' | 'copy' | 'save' | 'archive' | 'delete' | 'fromContent' | null
  >(null)

  // Custom monster form fields ('' / null = not set in the stored rules; see monsterLibraryForm.ts)
  const [formName, setFormName] = useState('')
  const [formAc, setFormAc] = useState<number>(10)
  const [formMaxHp, setFormMaxHp] = useState<number>(10)
  const [formCr, setFormCr] = useState<number>(0)
  const [formSize, setFormSize] = useState('')
  const [formType, setFormType] = useState('')
  const [formAlignment, setFormAlignment] = useState('')
  const [formSpeed, setFormSpeed] = useState('30 ft.')
  const [formStr, setFormStr] = useState<number | null>(null)
  const [formDex, setFormDex] = useState<number | null>(null)
  const [formCon, setFormCon] = useState<number | null>(null)
  const [formInt, setFormInt] = useState<number | null>(null)
  const [formWis, setFormWis] = useState<number | null>(null)
  const [formCha, setFormCha] = useState<number | null>(null)
  const [formDescription, setFormDescription] = useState('')
  const [formTraits, setFormTraits] = useState<EditableMonsterAbility[]>([])
  const [formActions, setFormActions] = useState<EditableMonsterAbility[]>([])
  // Snapshot of the loaded rules the dirty-field save diffs against.
  const [formBaseline, setFormBaseline] = useState<CustomMonsterFormValues | null>(null)

  // Modal dialog states
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newMonsterName, setNewMonsterName] = useState('')
  const [newMonsterAc, setNewMonsterAc] = useState(10)
  const [newMonsterHp, setNewMonsterHp] = useState(10)

  const [showCopyModal, setShowCopyModal] = useState(false)
  const [copyMonsterName, setCopyMonsterName] = useState('')

  const [showFromContentModal, setShowFromContentModal] = useState(false)
  const [fromContentName, setFromContentName] = useState('')

  const [listWidth, setListWidth] = useState(() => readListWidth())
  const listWidthRef = useRef(listWidth)
  const layoutRef = useRef<HTMLDivElement | null>(null)

  const applyListWidth = (next: number, persist: boolean) => {
    listWidthRef.current = next
    setListWidth(next)
    if (persist) writeListWidth(next)
  }

  const handleSplitterPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const handleSplitterPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const layout = layoutRef.current
    if (!layout || !event.currentTarget.hasPointerCapture(event.pointerId)) return
    const rect = layout.getBoundingClientRect()
    applyListWidth(clampListWidth(event.clientX - rect.left, rect.width), false)
  }

  const handleSplitterPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
    event.currentTarget.releasePointerCapture(event.pointerId)
    writeListWidth(listWidthRef.current)
  }

  const handleSplitterKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const next = resolveKeyboardListWidth(
      listWidthRef.current,
      event.key,
      layoutRef.current?.getBoundingClientRect().width,
    )
    if (next === null) return
    event.preventDefault()
    applyListWidth(next, true)
  }

  const PAGE_SIZE = 50
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)

  // Only the latest list request may update state; an older response that
  // arrives later (e.g. the initial load after a search) is dropped.
  const listRequestSeq = useRef(0)

  const reloadList = async (reset = true) => {
    if (crRangeInvalid) return
    const requestSeq = ++listRequestSeq.current
    if (reset) {
      setLoadingList(true)
    } else {
      setLoadingMore(true)
    }
    try {
      const offset = reset ? 0 : monsters.length
      const options: MonsterLibraryListOptions = {
        query: searchQuery.trim() || undefined,
        include_archived: showArchived,
        source: sourceFilter,
        limit: PAGE_SIZE,
        offset,
      }
      if (sortField !== 'name') options.sort = sortField
      if (sortOrder !== 'asc') options.order = sortOrder
      if (sizeFilter) options.size = sizeFilter
      if (typeFilter) options.type = typeFilter
      if (crMode === 'eq' && crEq !== '') options.cr_eq = Number(crEq)
      if (crMode === 'range' && crMin !== '') options.cr_min = Number(crMin)
      if (crMode === 'range' && crMax !== '') options.cr_max = Number(crMax)
      const items = await listMonsterLibrary(roomId, token, options)
      if (requestSeq !== listRequestSeq.current) return
      if (reset) {
        setMonsters(items)
      } else {
        setMonsters((prev) => [...prev, ...items])
      }
      setHasMore(items.length >= PAGE_SIZE)
      setListError(null)
    } catch (cause) {
      if (requestSeq !== listRequestSeq.current) return
      setListError(monsterLibraryErrorMessage(cause, copy))
    } finally {
      if (requestSeq === listRequestSeq.current) {
        setLoadingList(false)
        setLoadingMore(false)
      }
    }
  }

  useEffect(() => {
    if (!recent || !canManage) return
    if (crRangeInvalid) return
    void reloadList(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, token, canManage, sourceFilter, showArchived, sortField, sortOrder, sizeFilter, typeFilter, crMode, crEq, crMin, crMax, crRangeInvalid])

  // Escape closes whichever monster modal is open, unless an action is pending.
  useEffect(() => {
    if (!showCreateModal && !showFromContentModal && !showCopyModal) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || pendingAction !== null) return
      setShowCreateModal(false)
      setShowFromContentModal(false)
      setShowCopyModal(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [showCreateModal, showFromContentModal, showCopyModal, pendingAction])

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    void reloadList(true)
  }

  // Load detail when selectedRef changes
  useEffect(() => {
    if (!selectedRef || !recent || !canManage) {
      setDetail(null)
      return
    }
    let active = true
    setLoadingDetail(true)
    setDetailError(null)
    setActionNotice(null)

    void getMonsterLibraryEntry(roomId, selectedRef, token)
      .then((data) => {
        if (!active) return
        setDetail(data)
        if (data.source_kind === 'custom') {
          // One atomic computation: the loader never throws on partial
          // shapes (e.g. Quick Enemy templates), so the form is either
          // fully initialized or left untouched on error.
          const form = customMonsterFormFromDetail(data)
          setFormName(form.name)
          setFormAc(form.armorClass)
          setFormMaxHp(form.maxHp)
          setFormCr(form.challengeRating)
          setFormSize(form.size)
          setFormType(form.type)
          setFormAlignment(form.alignment)
          setFormSpeed(form.speed)
          setFormStr(form.abilities.strength)
          setFormDex(form.abilities.dexterity)
          setFormCon(form.abilities.constitution)
          setFormInt(form.abilities.intelligence)
          setFormWis(form.abilities.wisdom)
          setFormCha(form.abilities.charisma)
          setFormDescription(form.description)

          setFormTraits(toEditableAbilities(data.rules.traits))
          setFormActions(toEditableAbilities(data.rules.actions))
          setFormBaseline(form)
        }
      })
      .catch((cause) => {
        if (!active) return
        setDetailError(monsterLibraryErrorMessage(cause, copy))
      })
      .finally(() => {
        if (active) setLoadingDetail(false)
      })

    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRef, roomId, token, canManage])

  const handleCreateCustom = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newMonsterName.trim()) return
    setPendingAction('create')
    setDetailError(null)

    const payload: CreateCustomMonsterInput = {
      name: newMonsterName.trim(),
      armor_class: newMonsterAc,
      max_hp: newMonsterHp,
    }

    try {
      const created = await createCustomMonster(roomId, token, payload)
      setShowCreateModal(false)
      setNewMonsterName('')
      await reloadList()
      setSelectedRef(created.ref)
    } catch (cause) {
      setDetailError(monsterLibraryErrorMessage(cause, copy))
      await reloadList()
    } finally {
      setPendingAction(null)
    }
  }

  const handleCreateFromContent = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!detail) return
    setPendingAction('fromContent')
    setDetailError(null)

    try {
      const created = await createCustomMonsterFromContent(roomId, token, {
        content_key: detail.source_key ?? detail.ref,
        name: fromContentName.trim() || null,
      })
      setShowFromContentModal(false)
      setFromContentName('')
      await reloadList()
      setSelectedRef(created.ref)
    } catch (cause) {
      setDetailError(monsterLibraryErrorMessage(cause, copy))
      await reloadList()
    } finally {
      setPendingAction(null)
    }
  }

  const handleCopyCustom = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!detail || detail.revision === null || detail.revision === undefined) return
    setPendingAction('copy')
    setDetailError(null)

    const templateId = detail.ref.replace(/^custom:/, '')
    try {
      const copied = await copyCustomMonster(roomId, templateId, token, {
        expected_revision: detail.revision,
        name: copyMonsterName.trim() || null,
      })
      setShowCopyModal(false)
      setCopyMonsterName('')
      await reloadList()
      setSelectedRef(copied.ref)
    } catch (cause) {
      setDetailError(monsterLibraryErrorMessage(cause, copy))
      await reloadList()
    } finally {
      setPendingAction(null)
    }
  }

  const handleSaveCustom = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!detail || detail.revision === null || detail.revision === undefined) return
    if (!formBaseline) return
    setPendingAction('save')
    setDetailError(null)
    setActionNotice(null)

    const templateId = detail.ref.replace(/^custom:/, '')
    const current: CustomMonsterFormValues = {
      name: formName,
      armorClass: formAc,
      maxHp: formMaxHp,
      challengeRating: formCr,
      size: formSize,
      type: formType,
      alignment: formAlignment,
      speed: formSpeed,
      abilities: {
        strength: formStr,
        dexterity: formDex,
        constitution: formCon,
        intelligence: formInt,
        wisdom: formWis,
        charisma: formCha,
      },
      description: formDescription,
    }
    // Dirty-field save: only actually-changed scalars go out; fields still
    // unset are never sent, so editor defaults can't pollute stored rules.
    const payload: PatchCustomMonsterInput = customMonsterScalarPatch(
      formBaseline,
      current,
      detail.revision,
    )
    const rules = detail.rules
    if (formSpeed !== monsterSpeedString(rules.speed)) {
      payload.speed =
        typeof rules.speed === 'object' && rules.speed !== null
          ? { ...rules.speed, walk: formSpeed }
          : formSpeed
    }

    const traits = rules.traits ?? []
    if (
      formTraits.length !== traits.length
      || formTraits.some((trait, index) =>
        trait.sourceIndex !== index
        || trait.name !== traits[index]?.name
        || trait.desc !== (traits[index]?.desc ?? ''),
      )
    ) {
      payload.traits = formTraits.map((trait) => {
        const edit = { source_index: trait.sourceIndex, name: trait.name }
        return trait.sourceIndex === null
          || trait.desc !== (traits[trait.sourceIndex]?.desc ?? '')
          ? { ...edit, desc: trait.desc }
          : edit
      })
    }

    const actions = rules.actions ?? []
    if (
      formActions.length !== actions.length
      || formActions.some((action, index) =>
        action.sourceIndex !== index
        || action.name !== actions[index]?.name
        || action.desc !== (actions[index]?.desc ?? ''),
      )
    ) {
      payload.actions = formActions.map((action) => {
        const edit = { source_index: action.sourceIndex, name: action.name }
        return action.sourceIndex === null
          || action.desc !== (actions[action.sourceIndex]?.desc ?? '')
          ? { ...edit, desc: action.desc }
          : edit
      })
    }

    try {
      const updated = await patchCustomMonster(roomId, templateId, token, payload)
      setDetail(updated)
      // Rebase both the form and the diff baseline on the saved truth so a
      // second save without edits sends nothing.
      const savedForm = customMonsterFormFromDetail(updated)
      setFormName(savedForm.name)
      setFormAc(savedForm.armorClass)
      setFormMaxHp(savedForm.maxHp)
      setFormCr(savedForm.challengeRating)
      setFormSize(savedForm.size)
      setFormType(savedForm.type)
      setFormAlignment(savedForm.alignment)
      setFormSpeed(savedForm.speed)
      setFormStr(savedForm.abilities.strength)
      setFormDex(savedForm.abilities.dexterity)
      setFormCon(savedForm.abilities.constitution)
      setFormInt(savedForm.abilities.intelligence)
      setFormWis(savedForm.abilities.wisdom)
      setFormCha(savedForm.abilities.charisma)
      setFormDescription(savedForm.description)
      setFormTraits(toEditableAbilities(updated.rules.traits))
      setFormActions(toEditableAbilities(updated.rules.actions))
      setFormBaseline(savedForm)
      setActionNotice(copy.saveAction)
      await reloadList()
    } catch (cause) {
      // Keep form intact on error!
      setDetailError(monsterLibraryErrorMessage(cause, copy))
    } finally {
      setPendingAction(null)
    }
  }

  const handleArchiveCustom = async () => {
    if (!detail || detail.revision === null || detail.revision === undefined) return
    if (!window.confirm(copy.archiveConfirm)) return
    setPendingAction('archive')
    setDetailError(null)

    const templateId = detail.ref.replace(/^custom:/, '')
    try {
      const updated = await archiveCustomMonster(roomId, templateId, token, {
        expected_revision: detail.revision,
      })
      setDetail(updated)
      await reloadList()
    } catch (cause) {
      setDetailError(monsterLibraryErrorMessage(cause, copy))
    } finally {
      setPendingAction(null)
    }
  }

  const handleDeleteCustom = async () => {
    if (!detail || detail.revision === null || detail.revision === undefined) return
    if (!window.confirm(copy.deleteConfirm)) return
    setPendingAction('delete')
    setDetailError(null)

    const templateId = detail.ref.replace(/^custom:/, '')
    try {
      await deleteCustomMonster(roomId, templateId, token, detail.revision)
      setDetail(null)
      setSelectedRef(null)
      await reloadList()
    } catch (cause) {
      setDetailError(monsterLibraryErrorMessage(cause, copy))
    } finally {
      setPendingAction(null)
    }
  }

  // Not logged in to room
  if (!recent) {
    return (
      <main className="landing-page room-workspace-page">
        <section className="landing-card room-workspace-card">
          <h1>{copy.title}</h1>
          <p>{copy.missingAccess}</p>
          <a className="button secondary" href="/">{copy.backRoom}</a>
        </section>
      </main>
    )
  }

  // Member lacks authority: show mapped error and no data
  if (!canManage) {
    return (
      <main className="landing-page room-workspace-page">
        <section className="landing-card room-workspace-card">
          <h1>{copy.title}</h1>
          <p>{copy.errMonsterLibraryForbidden}</p>
          <a className="button secondary" href={`/rooms/${roomId}`}>{copy.backRoom}</a>
        </section>
      </main>
    )
  }

  const isBuiltin = detail?.source_kind === 'builtin'
  const isCustom = detail?.source_kind === 'custom'
  const isArchived = Boolean(detail?.archived_at)

  return (
    <main className="landing-page room-workspace-page monster-library-page">
      <section className="landing-card room-workspace-card monster-library-card">
        <div className="monster-library__header">
          <div>
            <h1>{copy.title}</h1>
            <p>{copy.intro}</p>
          </div>
          <div className="monster-library__top-actions">
            <button
              className="button primary"
              type="button"
              disabled={pendingAction !== null}
              onClick={() => {
                setNewMonsterName('')
                setNewMonsterAc(10)
                setNewMonsterHp(10)
                setShowCreateModal(true)
              }}
            >
              {copy.createAction}
            </button>
            <a className="button secondary" href={`/rooms/${roomId}`}>
              {copy.backRoom}
            </a>
          </div>
        </div>

        {listError ? <div className="form-error">{listError}</div> : null}

        {/* Search & Filters */}
        <form className="monster-library__filters" onSubmit={handleSearchSubmit}>
          <input
            type="search"
            value={searchQuery}
            placeholder={copy.searchPlaceholder}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value as 'all' | 'builtin' | 'custom')}
          >
            <option value="all">{copy.filterAll}</option>
            <option value="builtin">{copy.filterBuiltin}</option>
            <option value="custom">{copy.filterCustom}</option>
          </select>
          <label className="monster-library__checkbox-label">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
            />
            {copy.showArchived}
          </label>
          <label className="monster-library__filter-label">
            <span>{copy.sortLabel}</span>
            <select value={sortField} onChange={(e) => setSortField(e.target.value)}>
              <option value="name">{copy.sortName}</option>
              <option value="armor_class">{copy.sortArmorClass}</option>
              <option value="max_hp">{copy.sortMaxHp}</option>
              <option value="challenge_rating">{copy.sortChallengeRating}</option>
              <option value="walk_speed">{copy.sortWalkSpeed}</option>
            </select>
          </label>
          <label className="monster-library__filter-label">
            <span>{copy.orderLabel}</span>
            <select
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value as 'asc' | 'desc')}
            >
              <option value="asc">{copy.orderAsc}</option>
              <option value="desc">{copy.orderDesc}</option>
            </select>
          </label>
          <label className="monster-library__filter-label">
            <span>{copy.filterSizeLabel}</span>
            <select value={sizeFilter} onChange={(e) => setSizeFilter(e.target.value)}>
              <option value="">{copy.filterAllOption}</option>
              {SRD_SIZES.map((size) => (
                <option key={size} value={size}>
                  {formatMonsterRuleField('size', size, locale)}
                </option>
              ))}
            </select>
          </label>
          <label className="monster-library__filter-label">
            <span>{copy.filterTypeLabel}</span>
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="">{copy.filterAllOption}</option>
              {SRD_TYPES.map((monsterType) => (
                <option key={monsterType} value={monsterType}>
                  {formatMonsterRuleField('type', monsterType, locale)}
                </option>
              ))}
            </select>
          </label>
          <label className="monster-library__filter-label">
            <span>{copy.crModeLabel}</span>
            <select
              value={crMode}
              onChange={(e) => setCrMode(e.target.value as 'any' | 'eq' | 'range')}
            >
              <option value="any">{copy.crModeAny}</option>
              <option value="eq">{copy.crModeEq}</option>
              <option value="range">{copy.crModeRange}</option>
            </select>
          </label>
          {crMode === 'eq' ? (
            <label className="monster-library__filter-label">
              <span>{copy.crEqLabel}</span>
              <select value={crEq} onChange={(e) => setCrEq(e.target.value)}>
                {CHALLENGE_RATINGS.map((cr) => (
                  <option key={cr} value={String(cr)}>
                    {formatChallengeRating(cr)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {crMode === 'range' ? (
            <>
              <label className="monster-library__filter-label">
                <span>{copy.crMinLabel}</span>
                <select value={crMin} onChange={(e) => setCrMin(e.target.value)}>
                  <option value="">{copy.crUnlimitedOption}</option>
                  {CHALLENGE_RATINGS.map((cr) => (
                    <option key={cr} value={String(cr)}>
                      {formatChallengeRating(cr)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="monster-library__filter-label">
                <span>{copy.crMaxLabel}</span>
                <select value={crMax} onChange={(e) => setCrMax(e.target.value)}>
                  <option value="">{copy.crUnlimitedOption}</option>
                  {CHALLENGE_RATINGS.map((cr) => (
                    <option key={cr} value={String(cr)}>
                      {formatChallengeRating(cr)}
                    </option>
                  ))}
                </select>
              </label>
            </>
          ) : null}
          {crRangeInvalid ? (
            <p className="monster-library__filter-error" role="alert">
              {copy.errCrRangeInvalid}
            </p>
          ) : null}
          <button className="button secondary" type="submit" disabled={loadingList}>
            {copy.refreshAction}
          </button>
        </form>

        <div
          ref={layoutRef}
          className="monster-library__layout"
          style={{ '--monster-library-list-width': `${listWidth}px` } as CSSProperties}
        >
          {/* List panel */}
          <aside className="monster-library__sidebar" aria-label={copy.title}>
            {loadingList ? (
              <p className="room-empty-text">{copy.loadingList}</p>
            ) : monsters.length === 0 ? (
              <p className="room-empty-text">{copy.emptyList}</p>
            ) : (
              <>
                <ul className="monster-library__list">
                  {monsters.map((item) => {
                    const isSelected = item.ref === selectedRef
                    const displayName = formatMonsterName(item, locale)
                    return (
                      <li
                        key={item.ref}
                        className={`monster-library__item${isSelected ? ' monster-library__item--selected' : ''}`}
                      >
                        <button
                          type="button"
                          className="monster-library__item-button"
                          onClick={() => setSelectedRef(item.ref)}
                        >
                          <div className="monster-library__item-title-row">
                            <strong className="monster-library__item-name">{displayName}</strong>
                            <span className={`badge ${item.source_kind}`}>
                              {item.source_kind === 'builtin' ? copy.sourceBuiltin : copy.sourceCustom}
                            </span>
                            {item.archived_at ? (
                              <span className="badge archived">{copy.badgeArchived}</span>
                            ) : null}
                          </div>
                          <div className="monster-library__item-meta">
                            {item.type ? (
                              <span>{formatMonsterRuleField('type', item.type, locale)}</span>
                            ) : null}
                            {item.challenge_rating !== null && item.challenge_rating !== undefined ? (
                              <span>CR {item.challenge_rating}</span>
                            ) : null}
                            {item.armor_class !== null && item.armor_class !== undefined ? (
                              <span>AC {item.armor_class}</span>
                            ) : null}
                            {item.max_hp !== null && item.max_hp !== undefined ? (
                              <span>HP {item.max_hp}</span>
                            ) : null}
                            {item.walk_speed !== null && item.walk_speed !== undefined ? (
                              <span>{formatWalkSpeed(item.walk_speed, locale)}</span>
                            ) : null}
                          </div>
                        </button>
                      </li>
                    )
                  })}
                </ul>
                {hasMore ? (
                  <div className="monster-library__load-more-row">
                    <button
                      type="button"
                      className="button secondary monster-library__load-more-btn"
                      disabled={loadingMore || loadingList}
                      onClick={() => void reloadList(false)}
                    >
                      {loadingMore ? copy.loadingMore : copy.loadMore}
                    </button>
                  </div>
                ) : null}
              </>
            )}
          </aside>

          <div
            className="monster-library__splitter"
            role="separator"
            tabIndex={0}
            aria-orientation="vertical"
            aria-label={copy.resizeList}
            title={copy.resizeListHint}
            aria-valuemin={MIN_LIST_WIDTH}
            aria-valuemax={MAX_LIST_WIDTH}
            aria-valuenow={listWidth}
            onPointerDown={handleSplitterPointerDown}
            onPointerMove={handleSplitterPointerMove}
            onPointerUp={handleSplitterPointerUp}
            onKeyDown={handleSplitterKeyDown}
          />

          {/* Detail panel */}
          <section className="monster-library__detail" aria-label="Monster details">
            {loadingDetail ? (
              <p className="room-empty-text">{copy.loadingDetail}</p>
            ) : !detail ? (
              <p className="room-empty-text">{copy.selectPrompt}</p>
            ) : (
              <div className="monster-library__detail-body">
                {detailError ? <div className="form-error">{detailError}</div> : null}
                {actionNotice ? <div className="form-success">{actionNotice}</div> : null}

                {/* Built-in Monster: Read Only */}
                {isBuiltin ? (
                  <div className="monster-library__builtin-view">
                    <div className="monster-library__action-bar">
                      <div className="monster-library__title-block">
                        <h2>{formatMonsterName(detail, locale)}</h2>
                        <span className="badge builtin">{copy.sourceBuiltin}</span>
                      </div>
                      <button
                        type="button"
                        className="button primary"
                        disabled={pendingAction !== null}
                        onClick={() => {
                          setFromContentName('')
                          setShowFromContentModal(true)
                        }}
                      >
                        {copy.createFromContentAction}
                      </button>
                    </div>

                    <p className="monster-library__notice">{copy.readOnlyNotice}</p>

                    <div className="monster-library__stat-block">
                      <h3>{copy.coreStatsHeading}</h3>
                      <div className="monster-library__stats-grid">
                        <div className="monster-library__stats-row">
                        <div>
                          <strong>{copy.fieldArmorClass}:</strong> {detail.rules.armor_class}
                        </div>
                        <div>
                          <strong>{copy.fieldMaxHp}:</strong> {detail.rules.max_hp}
                        </div>
                        {detail.rules.challenge_rating !== null &&
                        detail.rules.challenge_rating !== undefined ? (
                          <div>
                            <strong>{copy.fieldChallengeRating}:</strong>{' '}
                            {detail.rules.challenge_rating}
                          </div>
                        ) : null}
                        <div>
                          <strong>{copy.fieldSpeed}:</strong> {monsterSpeedString(detail.rules.speed)}
                        </div>
                        </div>
                        <div className="monster-library__stats-row">
                        <div>
                          <strong>{copy.fieldSize}:</strong>{' '}
                          {formatMonsterRuleField('size', detail.rules.size, locale)}
                        </div>
                        <div>
                          <strong>{copy.fieldType}:</strong>{' '}
                          {formatMonsterRuleField('type', detail.rules.type, locale)}
                        </div>
                        <div>
                          <strong>{copy.fieldAlignment}:</strong>{' '}
                          {formatMonsterRuleField('alignment', detail.rules.alignment, locale)}
                        </div>
                        </div>
                      </div>

                      {/* Ability Scores */}
                      <h3>{copy.abilitiesHeading}</h3>
                      <div className="monster-library__abilities-grid">
                        {(
                          [
                            ['STR', detail.rules.ability_scores.strength],
                            ['DEX', detail.rules.ability_scores.dexterity],
                            ['CON', detail.rules.ability_scores.constitution],
                            ['INT', detail.rules.ability_scores.intelligence],
                            ['WIS', detail.rules.ability_scores.wisdom],
                            ['CHA', detail.rules.ability_scores.charisma],
                          ] as const
                        ).map(([label, val]) => (
                          <div key={label} className="monster-library__ability-box">
                            <strong>{label}</strong>
                            <span>
                              {val} ({formatModifier(val)})
                            </span>
                          </div>
                        ))}
                      </div>

                      {/* Traits */}
                      <h3>{copy.traitsHeading}</h3>
                      {Array.isArray(detail.rules.traits) && detail.rules.traits.length > 0 ? (
                        <div className="monster-library__abilities-list">
                          {detail.rules.traits.map((t, idx) => {
                            const tName = formatAbilityName(
                              t,
                              idx,
                              'traits',
                              detail.presentation,
                              locale,
                            )
                            return (
                              <article key={idx} className="monster-library__ability-entry">
                                <h4>
                                  {tName}
                                  {locale === 'zh-TW' && detail.presentation?.desc_is_english ? (
                                    <span className="monster-library__desc-lang-label">
                                      {' '}
                                      ({copy.englishOriginal})
                                    </span>
                                  ) : null}
                                </h4>
                                {t.desc ? <p>{t.desc}</p> : null}
                              </article>
                            )
                          })}
                        </div>
                      ) : (
                        <p className="room-empty-text">{copy.noTraits}</p>
                      )}

                      {/* Actions */}
                      <h3>{copy.actionsHeading}</h3>
                      {Array.isArray(detail.rules.actions) && detail.rules.actions.length > 0 ? (
                        <div className="monster-library__abilities-list">
                          {detail.rules.actions.map((a, idx) => {
                            const aName = formatAbilityName(
                              a,
                              idx,
                              'actions',
                              detail.presentation,
                              locale,
                            )
                            return (
                              <article key={idx} className="monster-library__ability-entry">
                                <h4>
                                  {aName}
                                  {locale === 'zh-TW' && detail.presentation?.desc_is_english ? (
                                    <span className="monster-library__desc-lang-label">
                                      {' '}
                                      ({copy.englishOriginal})
                                    </span>
                                  ) : null}
                                </h4>
                                {a.desc ? <p>{a.desc}</p> : null}
                              </article>
                            )
                          })}
                        </div>
                      ) : (
                        <p className="room-empty-text">{copy.noActions}</p>
                      )}

                      {/* Bonus Actions */}
                      {Array.isArray(detail.rules.bonus_actions) &&
                      detail.rules.bonus_actions.length > 0 ? (
                        <div>
                          <h3>{copy.bonusActionsHeading}</h3>
                          <div className="monster-library__abilities-list">
                            {detail.rules.bonus_actions.map((ba, idx) => {
                              const baName = formatAbilityName(
                                ba,
                                idx,
                                'bonus_actions',
                                detail.presentation,
                                locale,
                              )
                              return (
                                <article key={idx} className="monster-library__ability-entry">
                                  <h4>
                                    {baName}
                                    {locale === 'zh-TW' && detail.presentation?.desc_is_english ? (
                                      <span className="monster-library__desc-lang-label">
                                        {' '}
                                        ({copy.englishOriginal})
                                      </span>
                                    ) : null}
                                  </h4>
                                  {ba.desc ? <p>{ba.desc}</p> : null}
                                </article>
                              )
                            })}
                          </div>
                        </div>
                      ) : null}

                      {/* Reactions */}
                      {Array.isArray(detail.rules.reactions) &&
                      detail.rules.reactions.length > 0 ? (
                        <div>
                          <h3>{copy.reactionsHeading}</h3>
                          <div className="monster-library__abilities-list">
                            {detail.rules.reactions.map((r, idx) => {
                              const rName = formatAbilityName(
                                r,
                                idx,
                                'reactions',
                                detail.presentation,
                                locale,
                              )
                              return (
                                <article key={idx} className="monster-library__ability-entry">
                                  <h4>
                                    {rName}
                                    {locale === 'zh-TW' && detail.presentation?.desc_is_english ? (
                                      <span className="monster-library__desc-lang-label">
                                        {' '}
                                        ({copy.englishOriginal})
                                      </span>
                                    ) : null}
                                  </h4>
                                  {r.desc ? <p>{r.desc}</p> : null}
                                </article>
                              )
                            })}
                          </div>
                        </div>
                      ) : null}

                      {/* Legendary Actions */}
                      {Array.isArray(detail.rules.legendary_actions) &&
                      detail.rules.legendary_actions.length > 0 ? (
                        <div>
                          <h3>{copy.legendaryActionsHeading}</h3>
                          <div className="monster-library__abilities-list">
                            {detail.rules.legendary_actions.map((la, idx) => {
                              const laName = formatAbilityName(
                                la,
                                idx,
                                'legendary_actions',
                                detail.presentation,
                                locale,
                              )
                              return (
                                <article key={idx} className="monster-library__ability-entry">
                                  <h4>
                                    {laName}
                                    {locale === 'zh-TW' && detail.presentation?.desc_is_english ? (
                                      <span className="monster-library__desc-lang-label">
                                        {' '}
                                        ({copy.englishOriginal})
                                      </span>
                                    ) : null}
                                  </h4>
                                  {la.desc ? <p>{la.desc}</p> : null}
                                </article>
                              )
                            })}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </div>
                ) : isCustom ? (
                  /* Custom Monster: Editable */
                  <form className="monster-library__custom-form" onSubmit={handleSaveCustom}>
                    <div className="monster-library__action-bar">
                      <div className="monster-library__title-block">
                        <h2>{formatMonsterName(detail, locale)}</h2>
                        <span className="badge custom">{copy.sourceCustom}</span>
                        {isArchived ? (
                          <span className="badge archived">{copy.badgeArchived}</span>
                        ) : null}
                        {detail.revision !== null && detail.revision !== undefined ? (
                          <span className="monster-library__revision">
                            {copy.revisionLabel}: {detail.revision}
                          </span>
                        ) : null}
                      </div>

                      <div className="monster-library__buttons-row">
                        <button
                          type="submit"
                          className="button primary"
                          disabled={pendingAction !== null}
                        >
                          {pendingAction === 'save' ? copy.savingAction : copy.saveAction}
                        </button>
                        <button
                          type="button"
                          className="button secondary"
                          disabled={pendingAction !== null}
                          onClick={() => {
                            setCopyMonsterName(`${detail.name} (${copy.copyAction})`)
                            setShowCopyModal(true)
                          }}
                        >
                          {copy.copyAction}
                        </button>
                        {!isArchived ? (
                          <button
                            type="button"
                            className="button secondary"
                            disabled={pendingAction !== null}
                            onClick={handleArchiveCustom}
                          >
                            {pendingAction === 'archive' ? copy.archivingAction : copy.archiveAction}
                          </button>
                        ) : null}
                        <button
                          type="button"
                          className="button danger"
                          disabled={pendingAction !== null}
                          onClick={handleDeleteCustom}
                        >
                          {pendingAction === 'delete' ? copy.deletingAction : copy.deleteAction}
                        </button>
                      </div>
                    </div>

                    {isArchived ? (
                      <p className="monster-library__notice">{copy.archivedNotice}</p>
                    ) : null}

                    {/* Core stats editing */}
                    <h3>{copy.coreStatsHeading}</h3>
                    <div className="monster-library__form-grid">
                      <label>
                        <span>{copy.fieldName}</span>
                        <input
                          type="text"
                          required
                          value={formName}
                          disabled={pendingAction !== null}
                          onChange={(e) => setFormName(e.target.value)}
                        />
                      </label>
                      <label>
                        <span>{copy.fieldArmorClass}</span>
                        <input
                          type="number"
                          min={0}
                          max={40}
                          required
                          value={formAc}
                          disabled={pendingAction !== null}
                          onChange={(e) => setFormAc(Number(e.target.value))}
                        />
                      </label>
                      <label>
                        <span>{copy.fieldMaxHp}</span>
                        <input
                          type="number"
                          min={1}
                          max={9999}
                          required
                          value={formMaxHp}
                          disabled={pendingAction !== null}
                          onChange={(e) => setFormMaxHp(Number(e.target.value))}
                        />
                      </label>
                      <label>
                        <span>{copy.fieldChallengeRating}</span>
                        <input
                          type="number"
                          min={0}
                          step="any"
                          value={formCr}
                          disabled={pendingAction !== null}
                          onChange={(e) => setFormCr(Number(e.target.value))}
                        />
                      </label>
                      <label>
                        <span>{copy.fieldSpeed}</span>
                        <input
                          type="text"
                          value={formSpeed}
                          disabled={pendingAction !== null}
                          onChange={(e) => setFormSpeed(e.target.value)}
                        />
                      </label>
                      <label>
                        <span>{copy.fieldSize}</span>
                        <select
                          value={formSize}
                          disabled={pendingAction !== null}
                          onChange={(e) => setFormSize(e.target.value)}
                        >
                          <option value="">{copy.unsetOption}</option>
                          {!SRD_SIZES.includes(formSize as (typeof SRD_SIZES)[number]) && formSize ? (
                            <option value={formSize}>
                              {formatMonsterRuleField('size', formSize, locale)}
                            </option>
                          ) : null}
                          {SRD_SIZES.map((s) => (
                            <option key={s} value={s}>
                              {formatMonsterRuleField('size', s, locale)}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        <span>{copy.fieldType}</span>
                        <select
                          value={formType}
                          disabled={pendingAction !== null}
                          onChange={(e) => setFormType(e.target.value)}
                        >
                          <option value="">{copy.unsetOption}</option>
                          {!SRD_TYPES.includes(formType as (typeof SRD_TYPES)[number]) && formType ? (
                            <option value={formType}>
                              {formatMonsterRuleField('type', formType, locale)}
                            </option>
                          ) : null}
                          {SRD_TYPES.map((t) => (
                            <option key={t} value={t}>
                              {formatMonsterRuleField('type', t, locale)}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        <span>{copy.fieldAlignment}</span>
                        <select
                          value={formAlignment}
                          disabled={pendingAction !== null}
                          onChange={(e) => setFormAlignment(e.target.value)}
                        >
                          <option value="">{copy.unsetOption}</option>
                          {!SRD_ALIGNMENTS.includes(formAlignment as (typeof SRD_ALIGNMENTS)[number]) && formAlignment ? (
                            <option value={formAlignment}>
                              {formatMonsterRuleField('alignment', formAlignment, locale)}
                            </option>
                          ) : null}
                          {SRD_ALIGNMENTS.map((a) => (
                            <option key={a} value={a}>
                              {formatMonsterRuleField('alignment', a, locale)}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>

                    {/* Ability Scores editing (empty = not set; never sent back) */}
                    <h3>{copy.abilitiesHeading}</h3>
                    <div className="monster-library__abilities-grid">
                      <label className="monster-library__ability-input">
                        <span>{copy.fieldStr}</span>
                        <input
                          type="number"
                          min={1}
                          max={30}
                          value={formStr ?? ''}
                          placeholder={copy.unsetOption}
                          disabled={pendingAction !== null}
                          onChange={(e) => setFormStr(e.target.value === '' ? null : Number(e.target.value))}
                        />
                      </label>
                      <label className="monster-library__ability-input">
                        <span>{copy.fieldDex}</span>
                        <input
                          type="number"
                          min={1}
                          max={30}
                          value={formDex ?? ''}
                          placeholder={copy.unsetOption}
                          disabled={pendingAction !== null}
                          onChange={(e) => setFormDex(e.target.value === '' ? null : Number(e.target.value))}
                        />
                      </label>
                      <label className="monster-library__ability-input">
                        <span>{copy.fieldCon}</span>
                        <input
                          type="number"
                          min={1}
                          max={30}
                          value={formCon ?? ''}
                          placeholder={copy.unsetOption}
                          disabled={pendingAction !== null}
                          onChange={(e) => setFormCon(e.target.value === '' ? null : Number(e.target.value))}
                        />
                      </label>
                      <label className="monster-library__ability-input">
                        <span>{copy.fieldInt}</span>
                        <input
                          type="number"
                          min={1}
                          max={30}
                          value={formInt ?? ''}
                          placeholder={copy.unsetOption}
                          disabled={pendingAction !== null}
                          onChange={(e) => setFormInt(e.target.value === '' ? null : Number(e.target.value))}
                        />
                      </label>
                      <label className="monster-library__ability-input">
                        <span>{copy.fieldWis}</span>
                        <input
                          type="number"
                          min={1}
                          max={30}
                          value={formWis ?? ''}
                          placeholder={copy.unsetOption}
                          disabled={pendingAction !== null}
                          onChange={(e) => setFormWis(e.target.value === '' ? null : Number(e.target.value))}
                        />
                      </label>
                      <label className="monster-library__ability-input">
                        <span>{copy.fieldCha}</span>
                        <input
                          type="number"
                          min={1}
                          max={30}
                          value={formCha ?? ''}
                          placeholder={copy.unsetOption}
                          disabled={pendingAction !== null}
                          onChange={(e) => setFormCha(e.target.value === '' ? null : Number(e.target.value))}
                        />
                      </label>
                    </div>

                    {/* Description editing */}
                    <h3>{copy.descriptionHeading}</h3>
                    <label>
                      <textarea
                        rows={3}
                        value={formDescription}
                        disabled={pendingAction !== null}
                        onChange={(e) => setFormDescription(e.target.value)}
                      />
                    </label>

                    {/* Traits editing */}
                    <div className="monster-library__subhead-row">
                      <h3>{copy.traitsHeading}</h3>
                      <button
                        type="button"
                        className="button secondary compact"
                        disabled={pendingAction !== null}
                        onClick={() =>
                          setFormTraits([...formTraits, { sourceIndex: null, name: '', desc: '' }])
                        }
                      >
                        {copy.addTrait}
                      </button>
                    </div>
                    {formTraits.map((t, idx) => (
                      <div key={idx} className="monster-library__item-edit-row">
                        <input
                          type="text"
                          placeholder={copy.traitName}
                          value={t.name}
                          disabled={pendingAction !== null}
                          onChange={(e) => {
                            const updated = [...formTraits]
                            updated[idx] = { ...updated[idx], name: e.target.value }
                            setFormTraits(updated)
                          }}
                        />
                        <textarea
                          placeholder={copy.traitDesc}
                          rows={2}
                          value={t.desc}
                          disabled={pendingAction !== null}
                          onChange={(e) => {
                            const updated = [...formTraits]
                            updated[idx] = { ...updated[idx], desc: e.target.value }
                            setFormTraits(updated)
                          }}
                        />
                        <button
                          type="button"
                          className="button danger compact"
                          disabled={pendingAction !== null}
                          onClick={() => {
                            setFormTraits(formTraits.filter((_, i) => i !== idx))
                          }}
                        >
                          {copy.remove}
                        </button>
                      </div>
                    ))}

                    {/* Actions editing */}
                    <div className="monster-library__subhead-row">
                      <h3>{copy.actionsHeading}</h3>
                      <button
                        type="button"
                        className="button secondary compact"
                        disabled={pendingAction !== null}
                        onClick={() =>
                          setFormActions([...formActions, { sourceIndex: null, name: '', desc: '' }])
                        }
                      >
                        {copy.addAction}
                      </button>
                    </div>
                    {formActions.map((a, idx) => (
                      <div key={idx} className="monster-library__item-edit-row">
                        <input
                          type="text"
                          placeholder={copy.actionName}
                          value={a.name}
                          disabled={pendingAction !== null}
                          onChange={(e) => {
                            const updated = [...formActions]
                            updated[idx] = { ...updated[idx], name: e.target.value }
                            setFormActions(updated)
                          }}
                        />
                        <textarea
                          placeholder={copy.actionDesc}
                          rows={2}
                          value={a.desc}
                          disabled={pendingAction !== null}
                          onChange={(e) => {
                            const updated = [...formActions]
                            updated[idx] = { ...updated[idx], desc: e.target.value }
                            setFormActions(updated)
                          }}
                        />
                        <button
                          type="button"
                          className="button danger compact"
                          disabled={pendingAction !== null}
                          onClick={() => {
                            setFormActions(formActions.filter((_, i) => i !== idx))
                          }}
                        >
                          {copy.remove}
                        </button>
                      </div>
                    ))}
                  </form>
                ) : null}
              </div>
            )}
          </section>
        </div>

        {/* Modal: Create from zero */}
        {showCreateModal ? (
          <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="monster-create-modal-title">
            <div className="modal-dialog">
              <h3 id="monster-create-modal-title">{copy.createModalTitle}</h3>
              <form onSubmit={handleCreateCustom}>
                <label>
                  <span>{copy.modalNameRequired}</span>
                  <input
                    type="text"
                    required
                    value={newMonsterName}
                    autoFocus
                    disabled={pendingAction !== null}
                    onChange={(e) => setNewMonsterName(e.target.value)}
                  />
                </label>
                <label>
                  <span>{copy.fieldArmorClass}</span>
                  <input
                    type="number"
                    min={0}
                    max={40}
                    required
                    value={newMonsterAc}
                    disabled={pendingAction !== null}
                    onChange={(e) => setNewMonsterAc(Number(e.target.value))}
                  />
                </label>
                <label>
                  <span>{copy.fieldMaxHp}</span>
                  <input
                    type="number"
                    min={1}
                    max={9999}
                    required
                    value={newMonsterHp}
                    disabled={pendingAction !== null}
                    onChange={(e) => setNewMonsterHp(Number(e.target.value))}
                  />
                </label>
                <div className="modal-actions">
                  <button
                    type="button"
                    className="button secondary"
                    disabled={pendingAction !== null}
                    onClick={() => setShowCreateModal(false)}
                  >
                    {copy.cancel}
                  </button>
                  <button
                    type="submit"
                    className="button primary"
                    disabled={pendingAction !== null || !newMonsterName.trim()}
                  >
                    {pendingAction === 'create' ? copy.creatingAction : copy.submitCreate}
                  </button>
                </div>
              </form>
            </div>
          </div>
        ) : null}

        {/* Modal: Create from Content */}
        {showFromContentModal ? (
          <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="monster-from-content-modal-title">
            <div className="modal-dialog">
              <h3 id="monster-from-content-modal-title">{copy.fromContentModalTitle}</h3>
              <form onSubmit={handleCreateFromContent}>
                <label>
                  <span>{copy.modalNameOptional}</span>
                  <input
                    type="text"
                    value={fromContentName}
                    autoFocus
                    placeholder={detail?.name}
                    disabled={pendingAction !== null}
                    onChange={(e) => setFromContentName(e.target.value)}
                  />
                </label>
                <div className="modal-actions">
                  <button
                    type="button"
                    className="button secondary"
                    disabled={pendingAction !== null}
                    onClick={() => setShowFromContentModal(false)}
                  >
                    {copy.cancel}
                  </button>
                  <button
                    type="submit"
                    className="button primary"
                    disabled={pendingAction !== null}
                  >
                    {pendingAction === 'fromContent' ? copy.creatingAction : copy.submitCreate}
                  </button>
                </div>
              </form>
            </div>
          </div>
        ) : null}

        {/* Modal: Copy Custom */}
        {showCopyModal ? (
          <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="monster-copy-modal-title">
            <div className="modal-dialog">
              <h3 id="monster-copy-modal-title">{copy.copyModalTitle}</h3>
              <form onSubmit={handleCopyCustom}>
                <label>
                  <span>{copy.modalNameOptional}</span>
                  <input
                    type="text"
                    value={copyMonsterName}
                    autoFocus
                    disabled={pendingAction !== null}
                    onChange={(e) => setCopyMonsterName(e.target.value)}
                  />
                </label>
                <div className="modal-actions">
                  <button
                    type="button"
                    className="button secondary"
                    disabled={pendingAction !== null}
                    onClick={() => setShowCopyModal(false)}
                  >
                    {copy.cancel}
                  </button>
                  <button
                    type="submit"
                    className="button primary"
                    disabled={pendingAction !== null}
                  >
                    {pendingAction === 'copy' ? copy.copyingAction : copy.submitCopy}
                  </button>
                </div>
              </form>
            </div>
          </div>
        ) : null}
      </section>
    </main>
  )
}
