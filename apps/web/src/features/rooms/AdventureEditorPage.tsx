import { useCallback, useEffect, useState } from 'react'

import {
  archiveAdventure,
  createAdventureEntry,
  deleteAdventureEntry,
  finalizeAdventure,
  getAdventure,
  linkAdventureEntryAsset,
  listAdventureEntries,
  patchAdventure,
  patchAdventureEntry,
  reorderAdventureEntries,
  unlinkAdventureEntryAsset,
  type AdventureDefinition,
  type AdventureEntry,
  type AdventureEntryCreate,
  type AdventureEntryKind,
  type AdventureEntryPatch,
  type AdventureEntryPayload,
  type AdventureEntryVisibility,
  type AdventureStatus,
} from '../../api/adventures'
import {
  uploadRoomAsset,
  type RoomAssetVisibility,
} from '../../api/roomAssets'
import { useLocale } from '../../i18n/LocaleProvider'
import { AssetThumbnail } from './AssetThumbnail'
import { adventureErrorMessage, adventuresCopy } from './adventuresCopy'
import { adventureActions } from './RoomAdventuresPage'
import './rooms.css'

export type EntryFormState = {
  kind: AdventureEntryKind
  title: string
  body: string
  visibility: AdventureEntryVisibility
  parentEntryId: string
  fields: Record<string, string>
}

export const ENTRY_KIND_FIELDS: Record<AdventureEntryKind, readonly string[]> = {
  section: [],
  scene: ['read_aloud', 'dm_summary'],
  npc: ['role', 'disposition'],
  item: ['rarity', 'value_gp', 'is_magic'],
  monster_ref: ['monster_template_ref', 'count', 'notes'],
  quest: ['objective', 'reward'],
  secret: ['reveal_condition'],
  dm_note: [],
  suggested_check: ['ability', 'skill', 'dc', 'on_success', 'on_failure'],
  map: ['caption'],
  lore: ['topic'],
  other: [],
}

export const ABILITIES = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const
export type Ability = (typeof ABILITIES)[number]

export const DISPOSITIONS = ['friendly', 'neutral', 'hostile', 'unknown'] as const
export type Disposition = (typeof DISPOSITIONS)[number]

function isAbility(value: unknown): value is Ability {
  return typeof value === 'string' && (ABILITIES as readonly string[]).includes(value)
}

function isDisposition(value: unknown): value is Disposition {
  return typeof value === 'string' && (DISPOSITIONS as readonly string[]).includes(value)
}

export function entryPayloadFromForm(form: EntryFormState): AdventureEntryPayload {
  const fields = form.fields
  switch (form.kind) {
    case 'section':
      return { kind: 'section' }
    case 'scene': {
      const readAloud = fields.read_aloud?.trim()
      const dmSummary = fields.dm_summary?.trim()
      return {
        kind: 'scene',
        ...(readAloud ? { read_aloud: readAloud } : {}),
        ...(dmSummary ? { dm_summary: dmSummary } : {}),
      }
    }
    case 'npc': {
      const role = fields.role?.trim()
      const rawDisposition = fields.disposition?.trim() ?? ''
      const disposition: Disposition = isDisposition(rawDisposition) ? rawDisposition : 'unknown'
      return {
        kind: 'npc',
        ...(role ? { role } : {}),
        disposition,
      }
    }
    case 'item': {
      const rarity = fields.rarity?.trim()
      const rawValueGp = fields.value_gp?.trim()
      const valueGp = rawValueGp ? Number.parseInt(rawValueGp, 10) : undefined
      return {
        kind: 'item',
        ...(rarity ? { rarity } : {}),
        ...(valueGp !== undefined && !Number.isNaN(valueGp) ? { value_gp: valueGp } : {}),
        is_magic: fields.is_magic === 'true',
      }
    }
    case 'monster_ref': {
      const ref = fields.monster_template_ref?.trim() ?? ''
      const rawCount = fields.count?.trim()
      const count = rawCount ? Number.parseInt(rawCount, 10) : undefined
      const notes = fields.notes?.trim()
      return {
        kind: 'monster_ref',
        monster_template_ref: ref,
        ...(count !== undefined && !Number.isNaN(count) ? { count } : {}),
        ...(notes ? { notes } : {}),
      }
    }
    case 'quest': {
      const objective = fields.objective?.trim() ?? ''
      const reward = fields.reward?.trim()
      return {
        kind: 'quest',
        objective,
        ...(reward ? { reward } : {}),
      }
    }
    case 'secret': {
      const reveal = fields.reveal_condition?.trim()
      return {
        kind: 'secret',
        ...(reveal ? { reveal_condition: reveal } : {}),
      }
    }
    case 'dm_note':
      return { kind: 'dm_note' }
    case 'suggested_check': {
      const rawAbility = fields.ability?.trim() ?? ''
      const ability: Ability = isAbility(rawAbility) ? rawAbility : 'str'
      const skill = fields.skill?.trim()
      const dc = Number.parseInt(fields.dc?.trim() ?? '', 10)
      const onSuccess = fields.on_success?.trim()
      const onFailure = fields.on_failure?.trim()
      return {
        kind: 'suggested_check',
        ability,
        dc,
        ...(skill ? { skill } : {}),
        ...(onSuccess ? { on_success: onSuccess } : {}),
        ...(onFailure ? { on_failure: onFailure } : {}),
      }
    }
    case 'map': {
      const caption = fields.caption?.trim()
      return {
        kind: 'map',
        ...(caption ? { caption } : {}),
      }
    }
    case 'lore': {
      const topic = fields.topic?.trim()
      return {
        kind: 'lore',
        ...(topic ? { topic } : {}),
      }
    }
    case 'other':
      return { kind: 'other' }
  }
}

export function entryFormFromEntry(entry: AdventureEntry): EntryFormState {
  const fields: Record<string, string> = {}
  const data = entry.data
  switch (data.kind) {
    case 'section':
      break
    case 'scene':
      fields.read_aloud = data.read_aloud ?? ''
      fields.dm_summary = data.dm_summary ?? ''
      break
    case 'npc':
      fields.role = data.role ?? ''
      fields.disposition = data.disposition ?? 'unknown'
      break
    case 'item':
      fields.rarity = data.rarity ?? ''
      fields.value_gp = data.value_gp != null ? String(data.value_gp) : ''
      fields.is_magic = data.is_magic ? 'true' : 'false'
      break
    case 'monster_ref':
      fields.monster_template_ref = data.monster_template_ref ?? ''
      fields.count = data.count != null ? String(data.count) : ''
      fields.notes = data.notes ?? ''
      break
    case 'quest':
      fields.objective = data.objective ?? ''
      fields.reward = data.reward ?? ''
      break
    case 'secret':
      fields.reveal_condition = data.reveal_condition ?? ''
      break
    case 'dm_note':
      break
    case 'suggested_check':
      fields.ability = data.ability ?? ''
      fields.skill = data.skill ?? ''
      fields.dc = data.dc != null ? String(data.dc) : ''
      fields.on_success = data.on_success ?? ''
      fields.on_failure = data.on_failure ?? ''
      break
    case 'map':
      fields.caption = data.caption ?? ''
      break
    case 'lore':
      fields.topic = data.topic ?? ''
      break
    case 'other':
      break
  }

  return {
    kind: entry.kind,
    title: entry.title ?? '',
    body: entry.body ?? '',
    visibility: entry.visibility,
    parentEntryId: entry.parent_entry_id ?? '',
    fields,
  }
}

export function entryCreateFromForm(form: EntryFormState): AdventureEntryCreate {
  const title = form.title.trim()
  const body = form.body.trim()
  const parentId = form.parentEntryId.trim()
  return {
    kind: form.kind,
    title: title.length > 0 ? title : null,
    body: body.length > 0 ? body : null,
    visibility: form.visibility,
    parent_entry_id: parentId.length > 0 ? parentId : null,
    data: entryPayloadFromForm(form),
  }
}

export function entryPatchFromForm(form: EntryFormState): AdventureEntryPatch {
  const title = form.title.trim()
  const body = form.body.trim()
  const parentId = form.parentEntryId.trim()
  return {
    title: title.length > 0 ? title : null,
    body: body.length > 0 ? body : null,
    visibility: form.visibility,
    parent_entry_id: parentId.length > 0 ? parentId : null,
    data: entryPayloadFromForm(form),
  }
}

export function moveEntry(
  entries: AdventureEntry[],
  entryId: string,
  direction: -1 | 1,
): string[] | null {
  const index = entries.findIndex((e) => e.id === entryId)
  if (index === -1) return null
  const targetIndex = index + direction
  if (targetIndex < 0 || targetIndex >= entries.length) return null

  const result = entries.map((e) => e.id)
  const temp = result[index]
  result[index] = result[targetIndex]
  result[targetIndex] = temp
  return result
}

export function sectionOptions(
  entries: AdventureEntry[],
  excludeId: string | null,
): AdventureEntry[] {
  return entries.filter(
    (e) => e.kind === 'section' && (excludeId === null || e.id !== excludeId),
  )
}

export function entryKindLabel(
  kind: AdventureEntryKind,
  copy: ReturnType<typeof adventuresCopy>,
): string {
  switch (kind) {
    case 'section':
      return copy.kindSection
    case 'scene':
      return copy.kindScene
    case 'npc':
      return copy.kindNpc
    case 'item':
      return copy.kindItem
    case 'monster_ref':
      return copy.kindMonsterRef
    case 'quest':
      return copy.kindQuest
    case 'secret':
      return copy.kindSecret
    case 'dm_note':
      return copy.kindDmNote
    case 'suggested_check':
      return copy.kindSuggestedCheck
    case 'map':
      return copy.kindMap
    case 'lore':
      return copy.kindLore
    case 'other':
      return copy.kindOther
  }
}

function fieldLabel(field: string, copy: ReturnType<typeof adventuresCopy>): string {
  switch (field) {
    case 'read_aloud':
      return copy.fieldReadAloud
    case 'dm_summary':
      return copy.fieldDmSummary
    case 'role':
      return copy.fieldRole
    case 'disposition':
      return copy.fieldDisposition
    case 'rarity':
      return copy.fieldRarity
    case 'value_gp':
      return copy.fieldValueGp
    case 'is_magic':
      return copy.fieldIsMagic
    case 'monster_template_ref':
      return copy.fieldMonsterTemplateRef
    case 'count':
      return copy.fieldCount
    case 'notes':
      return copy.fieldNotes
    case 'objective':
      return copy.fieldObjective
    case 'reward':
      return copy.fieldReward
    case 'reveal_condition':
      return copy.fieldRevealCondition
    case 'ability':
      return copy.fieldAbility
    case 'skill':
      return copy.fieldSkill
    case 'dc':
      return copy.fieldDc
    case 'on_success':
      return copy.fieldOnSuccess
    case 'on_failure':
      return copy.fieldOnFailure
    case 'caption':
      return copy.fieldCaption
    case 'topic':
      return copy.fieldTopic
    default:
      return field
  }
}

function abilityLabel(ability: Ability, copy: ReturnType<typeof adventuresCopy>): string {
  switch (ability) {
    case 'str':
      return copy.abilityStr
    case 'dex':
      return copy.abilityDex
    case 'con':
      return copy.abilityCon
    case 'int':
      return copy.abilityInt
    case 'wis':
      return copy.abilityWis
    case 'cha':
      return copy.abilityCha
  }
}

function dispositionLabel(
  disposition: Disposition,
  copy: ReturnType<typeof adventuresCopy>,
): string {
  switch (disposition) {
    case 'friendly':
      return copy.dispositionFriendly
    case 'neutral':
      return copy.dispositionNeutral
    case 'hostile':
      return copy.dispositionHostile
    case 'unknown':
      return copy.dispositionUnknown
  }
}

export type EntryAssetUploadFormProps = {
  copy: ReturnType<typeof adventuresCopy>
  pending?: boolean
  onSubmit: (file: File, visibility: RoomAssetVisibility, role: 'image' | 'map') => void
}

export function EntryAssetUploadForm({
  copy,
  pending = false,
  onSubmit,
}: EntryAssetUploadFormProps) {
  const [file, setFile] = useState<File | null>(null)
  const [role, setRole] = useState<'image' | 'map'>('image')
  const [visibility, setVisibility] = useState<RoomAssetVisibility>('dm_only')
  const [fileInputKey, setFileInputKey] = useState(0)

  return (
    <form
      className="adventure-entry__upload"
      onSubmit={(e) => {
        e.preventDefault()
        if (!file) return
        onSubmit(file, visibility, role)
        setFile(null)
        setFileInputKey((k) => k + 1)
      }}
    >
      <label className="room-field">
        <span>{copy.assetFileLabel}</span>
        <input
          accept="image/png,image/jpeg,image/webp"
          disabled={pending}
          key={fileInputKey}
          type="file"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </label>
      <label className="room-field">
        <span>{copy.assetRoleLabel}</span>
        <select
          disabled={pending}
          value={role}
          onChange={(e) => setRole(e.target.value as 'image' | 'map')}
        >
          <option value="image">{copy.roleImage}</option>
          <option value="map">{copy.roleMap}</option>
        </select>
      </label>
      <label className="room-field">
        <span>{copy.assetVisibilityLabel}</span>
        <select
          disabled={pending}
          value={visibility}
          onChange={(e) => setVisibility(e.target.value as RoomAssetVisibility)}
        >
          <option value="room">{copy.assetVisibilityRoom}</option>
          <option value="dm_only">{copy.assetVisibilityDmOnly}</option>
        </select>
      </label>
      <button
        className="button primary"
        disabled={pending || !file}
        type="submit"
      >
        {copy.uploadAttach}
      </button>
    </form>
  )
}

export type AdventureEntryListProps = {
  entries: AdventureEntry[]
  copy: ReturnType<typeof adventuresCopy>
  readOnly: boolean
  pending?: boolean
  roomId: string
  token: string
  onEdit: (entry: AdventureEntry) => void
  onDelete: (entryId: string) => void
  onMove: (entryId: string, direction: -1 | 1) => void
  onLinkAsset: (
    entryId: string,
    file: File,
    visibility: RoomAssetVisibility,
    role: 'image' | 'map',
  ) => void
  onUnlinkAsset: (entryId: string, assetId: string) => void
  onAssetError: (error: unknown) => void
}

export function AdventureEntryList({
  entries,
  copy,
  readOnly,
  pending = false,
  roomId,
  token,
  onEdit,
  onDelete,
  onMove,
  onLinkAsset,
  onUnlinkAsset,
  onAssetError,
}: AdventureEntryListProps) {
  if (entries.length === 0) {
    return <p className="room-empty-text">{copy.entriesEmpty}</p>
  }

  return (
    <div className="adventure-entry-list">
      {entries.map((entry, index) => {
        const titleText =
          entry.title && entry.title.trim().length > 0
            ? entry.title
            : entryKindLabel(entry.kind, copy)
        const visibilityLabel =
          entry.visibility === 'public' ? copy.visibilityPublic : copy.visibilityDmOnly

        return (
          <article
            className={`adventure-entry${entry.parent_entry_id !== null ? ' adventure-entry--child' : ''}`}
            key={entry.id}
          >
            <div className="adventure-entry__content">
              <div className="adventure-entry__meta">
                <span className="adventure-entry__kind">{entryKindLabel(entry.kind, copy)}</span>
                <span className="adventure-entry__visibility">{visibilityLabel}</span>
              </div>
              <h3 className="adventure-entry__title">{titleText}</h3>
              {entry.body ? <p className="adventure-entry__body">{entry.body}</p> : null}
              {entry.assets.length > 0 ? (
                <div className="adventure-entry__assets">
                  {entry.assets.map((entryAsset) => {
                    const isImageOrMap =
                      entryAsset.role === 'image' || entryAsset.role === 'map'
                    return (
                      <div className="adventure-asset" key={entryAsset.asset.id}>
                        {isImageOrMap ? (
                          <>
                            <AssetThumbnail
                              alt={entryAsset.asset.original_filename}
                              assetId={entryAsset.asset.id}
                              onError={onAssetError}
                              roomId={roomId}
                              token={token}
                            />
                            <div className="adventure-asset__caption">
                              <span>{entryAsset.role === 'map' ? copy.roleMap : copy.roleImage}</span>
                              {entryAsset.asset.visibility === 'dm_only' ? (
                                <span className="adventure-entry__visibility">
                                  {copy.assetDmOnly}
                                </span>
                              ) : null}
                            </div>
                          </>
                        ) : (
                          <span className="adventure-asset__caption">
                            {entryAsset.asset.original_filename}
                          </span>
                        )}
                        {!readOnly ? (
                          <button
                            className="button secondary"
                            disabled={pending}
                            type="button"
                            onClick={() => {
                              if (!window.confirm(copy.unlinkConfirm)) return
                              onUnlinkAsset(entry.id, entryAsset.asset.id)
                            }}
                          >
                            {copy.unlinkAsset}
                          </button>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
              ) : null}
              {!readOnly ? (
                <EntryAssetUploadForm
                  copy={copy}
                  pending={pending}
                  onSubmit={(file, visibility, role) =>
                    onLinkAsset(entry.id, file, visibility, role)
                  }
                />
              ) : null}
            </div>
            {!readOnly ? (
              <div className="adventure-entry__actions">
                <button
                  className="button secondary"
                  disabled={pending}
                  type="button"
                  onClick={() => onEdit(entry)}
                >
                  {copy.editEntry}
                </button>
                <button
                  className="button danger"
                  disabled={pending}
                  type="button"
                  onClick={() => {
                    if (!window.confirm(copy.entryDeleteConfirm)) return
                    onDelete(entry.id)
                  }}
                >
                  {copy.deleteEntry}
                </button>
                <button
                  className="button secondary"
                  disabled={pending || index === 0}
                  type="button"
                  onClick={() => onMove(entry.id, -1)}
                >
                  {copy.moveUp}
                </button>
                <button
                  className="button secondary"
                  disabled={pending || index === entries.length - 1}
                  type="button"
                  onClick={() => onMove(entry.id, 1)}
                >
                  {copy.moveDown}
                </button>
              </div>
            ) : null}
          </article>
        )
      })}
    </div>
  )
}

function initialEntryFormState(kind: AdventureEntryKind = 'section'): EntryFormState {
  return {
    kind,
    title: '',
    body: '',
    visibility: 'public',
    parentEntryId: '',
    fields: {},
  }
}

export type AdventureEditorPageProps = {
  roomId: string
  adventureId: string
  token: string
}

export function AdventureEditorPage({ roomId, adventureId, token }: AdventureEditorPageProps) {
  const { locale } = useLocale()
  const copy = adventuresCopy(locale)

  const [adventure, setAdventure] = useState<AdventureDefinition | null>(null)
  const [entries, setEntries] = useState<AdventureEntry[]>([])
  const [name, setName] = useState('')
  const [summary, setSummary] = useState('')
  const [editMode, setEditMode] = useState<{ kind: 'create' } | { kind: 'edit'; entryId: string }>({
    kind: 'create',
  })
  const [entryForm, setEntryForm] = useState<EntryFormState>(initialEntryFormState('section'))
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reloadEntriesOnly = async () => {
    const entList = await listAdventureEntries(roomId, adventureId, token)
    setEntries(entList)
  }

  const reloadAll = async () => {
    const [adv, entList] = await Promise.all([
      getAdventure(roomId, adventureId, token),
      listAdventureEntries(roomId, adventureId, token),
    ])
    setAdventure(adv)
    setEntries(entList)
    setName(adv.name)
    setSummary(adv.summary ?? '')
  }

  const runMutation = (operation: () => Promise<unknown>, reload: () => Promise<void> = reloadAll) => {
    setPending(true)
    setError(null)
    void operation()
      .then(() => reload())
      .catch((cause: unknown) => setError(adventureErrorMessage(cause, copy)))
      .finally(() => setPending(false))
  }

  const handleAssetError = useCallback(
    (cause: unknown) => {
      setError(adventureErrorMessage(cause, copy))
    },
    [copy],
  )

  useEffect(() => {
    let active = true
    setPending(true)
    setError(null)
    Promise.all([
      getAdventure(roomId, adventureId, token),
      listAdventureEntries(roomId, adventureId, token),
    ])
      .then(([adv, entList]) => {
        if (!active) return
        setAdventure(adv)
        setEntries(entList)
        setName(adv.name)
        setSummary(adv.summary ?? '')
      })
      .catch((cause: unknown) => {
        if (!active) return
        setError(adventureErrorMessage(cause, copy))
      })
      .finally(() => {
        if (active) setPending(false)
      })

    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, adventureId, token])

  const isArchived = adventure?.status === 'archived'
  const actions = adventure
    ? adventureActions(adventure.status)
    : { finalize: false, archive: false, delete: false }

  const statusLabel = (status: AdventureStatus) => {
    switch (status) {
      case 'draft':
        return copy.statusDraft
      case 'finalized':
        return copy.statusFinalized
      case 'archived':
        return copy.statusArchived
    }
  }

  const setFieldValue = (key: string, value: string) => {
    setEntryForm((prev) => ({
      ...prev,
      fields: {
        ...prev.fields,
        [key]: value,
      },
    }))
  }

  return (
    <main className="landing-page room-workspace-page adventure-editor">
      <header className="landing-card room-workspace-card">
        <h1>{adventure?.name ?? copy.editorTitle}</h1>
        {adventure ? (
          <p className="adventure-card__status">
            {copy.statusLabel}: {statusLabel(adventure.status)}
          </p>
        ) : null}
        {isArchived ? <p className="adventure-card__summary">{copy.readOnlyNotice}</p> : null}
        <div className="adventure-card__actions">
          <a className="button secondary" href={`/rooms/${roomId}/adventures`}>
            {copy.backAdventures}
          </a>
          {actions.finalize ? (
            <button
              className="button secondary"
              disabled={pending}
              type="button"
              onClick={() => runMutation(() => finalizeAdventure(roomId, adventureId, token))}
            >
              {copy.finalize}
            </button>
          ) : null}
          {actions.archive ? (
            <button
              className="button secondary"
              disabled={pending}
              type="button"
              onClick={() => {
                if (!window.confirm(copy.archiveConfirm)) return
                runMutation(() => archiveAdventure(roomId, adventureId, token))
              }}
            >
              {copy.archive}
            </button>
          ) : null}
        </div>
        {error ? <p className="form-error">{error}</p> : null}
      </header>

      {!isArchived && adventure ? (
        <section className="landing-card room-workspace-card">
          <h2>{copy.definitionTitle}</h2>
          <form
            className="room-form"
            onSubmit={(e) => {
              e.preventDefault()
              runMutation(() =>
                patchAdventure(roomId, adventureId, token, {
                  name: name.trim(),
                  summary: summary.trim() || null,
                }),
              )
            }}
          >
            <label className="room-field">
              <span>{copy.nameLabel}</span>
              <input
                required
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label className="room-field">
              <span>{copy.summaryLabel}</span>
              <textarea
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
              />
            </label>
            <button className="button primary" disabled={pending || !name.trim()} type="submit">
              {copy.saveDefinition}
            </button>
          </form>
        </section>
      ) : null}

      <section className="landing-card room-workspace-card">
        <h2>{copy.entriesTitle}</h2>
        <AdventureEntryList
          copy={copy}
          entries={entries}
          pending={pending}
          readOnly={isArchived}
          roomId={roomId}
          token={token}
          onAssetError={handleAssetError}
          onDelete={(entryId) => {
            runMutation(
              () => deleteAdventureEntry(roomId, adventureId, entryId, token),
              reloadEntriesOnly,
            )
          }}
          onEdit={(entry) => {
            setEditMode({ kind: 'edit', entryId: entry.id })
            setEntryForm(entryFormFromEntry(entry))
          }}
          onLinkAsset={(entryId, file, visibility, role) => {
            runMutation(
              () =>
                uploadRoomAsset(roomId, token, {
                  kind: 'image',
                  filename: file.name,
                  visibility,
                  file,
                }).then((asset) =>
                  linkAdventureEntryAsset(roomId, adventureId, entryId, token, {
                    asset_id: asset.id,
                    role,
                  }),
                ),
              reloadEntriesOnly,
            )
          }}
          onMove={(entryId, direction) => {
            const nextIds = moveEntry(entries, entryId, direction)
            if (!nextIds) return
            runMutation(
              () => reorderAdventureEntries(roomId, adventureId, token, { entry_ids: nextIds }),
              reloadEntriesOnly,
            )
          }}
          onUnlinkAsset={(entryId, assetId) => {
            runMutation(
              () => unlinkAdventureEntryAsset(roomId, adventureId, entryId, assetId, token),
              reloadEntriesOnly,
            )
          }}
        />
      </section>

      {!isArchived ? (
        <section className="landing-card room-workspace-card">
          <h2>{editMode.kind === 'edit' ? copy.editEntryTitle : copy.addEntryTitle}</h2>
          <form
            className="room-form"
            onSubmit={(e) => {
              e.preventDefault()
              if (editMode.kind === 'edit') {
                runMutation(
                  () =>
                    patchAdventureEntry(
                      roomId,
                      adventureId,
                      editMode.entryId,
                      token,
                      entryPatchFromForm(entryForm),
                    ),
                  async () => {
                    await reloadEntriesOnly()
                    setEditMode({ kind: 'create' })
                    setEntryForm(initialEntryFormState(entryForm.kind))
                  },
                )
              } else {
                runMutation(
                  () =>
                    createAdventureEntry(
                      roomId,
                      adventureId,
                      token,
                      entryCreateFromForm(entryForm),
                    ),
                  async () => {
                    await reloadEntriesOnly()
                    setEditMode({ kind: 'create' })
                    setEntryForm(initialEntryFormState(entryForm.kind))
                  },
                )
              }
            }}
          >
            <label className="room-field">
              <span>{copy.entryKindLabel}</span>
              <select
                disabled={editMode.kind === 'edit'}
                value={entryForm.kind}
                onChange={(e) => {
                  const nextKind = e.target.value as AdventureEntryKind
                  setEntryForm((prev) => ({
                    ...prev,
                    kind: nextKind,
                    fields: {},
                  }))
                }}
              >
                {(Object.keys(ENTRY_KIND_FIELDS) as AdventureEntryKind[]).map((kind) => (
                  <option key={kind} value={kind}>
                    {entryKindLabel(kind, copy)}
                  </option>
                ))}
              </select>
            </label>

            <label className="room-field">
              <span>{copy.entryTitleLabel}</span>
              <input
                type="text"
                value={entryForm.title}
                onChange={(e) => setEntryForm((prev) => ({ ...prev, title: e.target.value }))}
              />
            </label>

            <label className="room-field">
              <span>{copy.entryBodyLabel}</span>
              <textarea
                value={entryForm.body}
                onChange={(e) => setEntryForm((prev) => ({ ...prev, body: e.target.value }))}
              />
            </label>

            <label className="room-field">
              <span>{copy.entryVisibilityLabel}</span>
              <select
                value={entryForm.visibility}
                onChange={(e) =>
                  setEntryForm((prev) => ({
                    ...prev,
                    visibility: e.target.value as AdventureEntryVisibility,
                  }))
                }
              >
                <option value="public">{copy.visibilityPublic}</option>
                <option value="dm_only">{copy.visibilityDmOnly}</option>
              </select>
            </label>

            <label className="room-field">
              <span>{copy.entryParentLabel}</span>
              <select
                value={entryForm.parentEntryId}
                onChange={(e) =>
                  setEntryForm((prev) => ({ ...prev, parentEntryId: e.target.value }))
                }
              >
                <option value="">{copy.entryParentNone}</option>
                {sectionOptions(
                  entries,
                  editMode.kind === 'edit' ? editMode.entryId : null,
                ).map((sec) => (
                  <option key={sec.id} value={sec.id}>
                    {sec.title && sec.title.trim().length > 0
                      ? sec.title
                      : entryKindLabel('section', copy)}
                  </option>
                ))}
              </select>
            </label>

            {ENTRY_KIND_FIELDS[entryForm.kind].map((field) => {
              if (field === 'disposition') {
                return (
                  <label className="room-field" key={field}>
                    <span>{fieldLabel(field, copy)}</span>
                    <select
                      value={entryForm.fields.disposition || 'unknown'}
                      onChange={(e) => setFieldValue('disposition', e.target.value)}
                    >
                      {DISPOSITIONS.map((disp) => (
                        <option key={disp} value={disp}>
                          {dispositionLabel(disp, copy)}
                        </option>
                      ))}
                    </select>
                  </label>
                )
              }
              if (field === 'ability') {
                return (
                  <label className="room-field" key={field}>
                    <span>{fieldLabel(field, copy)}</span>
                    <select
                      value={entryForm.fields.ability || 'str'}
                      onChange={(e) => setFieldValue('ability', e.target.value)}
                    >
                      {ABILITIES.map((ab) => (
                        <option key={ab} value={ab}>
                          {abilityLabel(ab, copy)}
                        </option>
                      ))}
                    </select>
                  </label>
                )
              }
              if (field === 'is_magic') {
                return (
                  <label className="room-field room-field--inline" key={field}>
                    <input
                      checked={entryForm.fields.is_magic === 'true'}
                      type="checkbox"
                      onChange={(e) =>
                        setFieldValue('is_magic', e.target.checked ? 'true' : 'false')
                      }
                    />
                    <span>{fieldLabel(field, copy)}</span>
                  </label>
                )
              }
              if (field === 'dc') {
                return (
                  <label className="room-field" key={field}>
                    <span>{fieldLabel(field, copy)}</span>
                    <input
                      max={40}
                      min={1}
                      required
                      type="number"
                      value={entryForm.fields.dc ?? ''}
                      onChange={(e) => setFieldValue('dc', e.target.value)}
                    />
                  </label>
                )
              }
              if (field === 'count') {
                return (
                  <label className="room-field" key={field}>
                    <span>{fieldLabel(field, copy)}</span>
                    <input
                      min={1}
                      type="number"
                      value={entryForm.fields.count ?? ''}
                      onChange={(e) => setFieldValue('count', e.target.value)}
                    />
                  </label>
                )
              }
              if (field === 'value_gp') {
                return (
                  <label className="room-field" key={field}>
                    <span>{fieldLabel(field, copy)}</span>
                    <input
                      min={0}
                      type="number"
                      value={entryForm.fields.value_gp ?? ''}
                      onChange={(e) => setFieldValue('value_gp', e.target.value)}
                    />
                  </label>
                )
              }
              if (field === 'monster_template_ref') {
                return (
                  <label className="room-field" key={field}>
                    <span>{fieldLabel(field, copy)}</span>
                    <input
                      required
                      type="text"
                      value={entryForm.fields.monster_template_ref ?? ''}
                      onChange={(e) => setFieldValue('monster_template_ref', e.target.value)}
                    />
                  </label>
                )
              }
              if (field === 'objective') {
                return (
                  <label className="room-field" key={field}>
                    <span>{fieldLabel(field, copy)}</span>
                    <input
                      required
                      type="text"
                      value={entryForm.fields.objective ?? ''}
                      onChange={(e) => setFieldValue('objective', e.target.value)}
                    />
                  </label>
                )
              }
              return (
                <label className="room-field" key={field}>
                  <span>{fieldLabel(field, copy)}</span>
                  <input
                    type="text"
                    value={entryForm.fields[field] ?? ''}
                    onChange={(e) => setFieldValue(field, e.target.value)}
                  />
                </label>
              )
            })}

            <div className="adventure-card__actions">
              <button className="button primary" disabled={pending} type="submit">
                {editMode.kind === 'edit' ? copy.saveEntry : copy.addEntry}
              </button>
              {editMode.kind === 'edit' ? (
                <button
                  className="button secondary"
                  disabled={pending}
                  type="button"
                  onClick={() => {
                    setEditMode({ kind: 'create' })
                    setEntryForm(initialEntryFormState(entryForm.kind))
                  }}
                >
                  {copy.cancelEdit}
                </button>
              ) : null}
            </div>
          </form>
        </section>
      ) : null}
    </main>
  )
}
