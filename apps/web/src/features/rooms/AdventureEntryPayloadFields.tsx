import type {
  AdventureEntryKind,
  AdventureEntryPayload,
} from '../../api/adventures'
import type { adventuresCopy } from './adventuresCopy'

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

export function isAbility(value: unknown): value is Ability {
  return typeof value === 'string' && (ABILITIES as readonly string[]).includes(value)
}

export function isDisposition(value: unknown): value is Disposition {
  return typeof value === 'string' && (DISPOSITIONS as readonly string[]).includes(value)
}

export function fieldLabel(field: string, copy: ReturnType<typeof adventuresCopy>): string {
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

export function abilityLabel(ability: Ability, copy: ReturnType<typeof adventuresCopy>): string {
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

export function dispositionLabel(
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

export function entryFieldsFromPayload(data: AdventureEntryPayload): Record<string, string> {
  const fields: Record<string, string> = {}
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
  return fields
}

export function entryPayloadFromForm(form: {
  kind: AdventureEntryKind
  fields: Record<string, string>
}): AdventureEntryPayload {
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
      const disposition: Disposition = (DISPOSITIONS as readonly string[]).includes(rawDisposition)
        ? (rawDisposition as Disposition)
        : 'unknown'
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
      const ability: Ability = (ABILITIES as readonly string[]).includes(rawAbility)
        ? (rawAbility as Ability)
        : 'str'
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

export type AdventureEntryPayloadFieldsProps = {
  kind: AdventureEntryKind
  fields: Record<string, string>
  copy: ReturnType<typeof adventuresCopy>
  onChange: (field: string, value: string) => void
  disabled?: boolean
}

export function AdventureEntryPayloadFields({
  kind,
  fields,
  copy,
  onChange,
  disabled = false,
}: AdventureEntryPayloadFieldsProps) {
  const fieldList = ENTRY_KIND_FIELDS[kind]

  return (
    <>
      {fieldList.map((field) => {
        if (field === 'disposition') {
          return (
            <label className="room-field" key={field}>
              <span>{fieldLabel(field, copy)}</span>
              <select
                disabled={disabled}
                value={fields.disposition || 'unknown'}
                onChange={(e) => onChange('disposition', e.target.value)}
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
                disabled={disabled}
                value={fields.ability || 'str'}
                onChange={(e) => onChange('ability', e.target.value)}
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
                checked={fields.is_magic === 'true'}
                disabled={disabled}
                type="checkbox"
                onChange={(e) => onChange('is_magic', e.target.checked ? 'true' : 'false')}
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
                disabled={disabled}
                max={40}
                min={1}
                required
                type="number"
                value={fields.dc ?? ''}
                onChange={(e) => onChange('dc', e.target.value)}
              />
            </label>
          )
        }
        if (field === 'count') {
          return (
            <label className="room-field" key={field}>
              <span>{fieldLabel(field, copy)}</span>
              <input
                disabled={disabled}
                min={1}
                type="number"
                value={fields.count ?? ''}
                onChange={(e) => onChange('count', e.target.value)}
              />
            </label>
          )
        }
        if (field === 'value_gp') {
          return (
            <label className="room-field" key={field}>
              <span>{fieldLabel(field, copy)}</span>
              <input
                disabled={disabled}
                min={0}
                type="number"
                value={fields.value_gp ?? ''}
                onChange={(e) => onChange('value_gp', e.target.value)}
              />
            </label>
          )
        }
        if (field === 'monster_template_ref') {
          return (
            <label className="room-field" key={field}>
              <span>{fieldLabel(field, copy)}</span>
              <input
                disabled={disabled}
                required
                type="text"
                value={fields.monster_template_ref ?? ''}
                onChange={(e) => onChange('monster_template_ref', e.target.value)}
              />
            </label>
          )
        }
        if (field === 'objective') {
          return (
            <label className="room-field" key={field}>
              <span>{fieldLabel(field, copy)}</span>
              <input
                disabled={disabled}
                required
                type="text"
                value={fields.objective ?? ''}
                onChange={(e) => onChange('objective', e.target.value)}
              />
            </label>
          )
        }
        return (
          <label className="room-field" key={field}>
            <span>{fieldLabel(field, copy)}</span>
            <input
              disabled={disabled}
              type="text"
              value={fields[field] ?? ''}
              onChange={(e) => onChange(field, e.target.value)}
            />
          </label>
        )
      })}
    </>
  )
}
