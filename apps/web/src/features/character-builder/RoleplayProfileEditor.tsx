import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import type { BuilderDraftPayload, BuilderView } from '../../api/characterBuilder'
import { useLocale } from '../../i18n/LocaleProvider'
import type { UiCopyKey } from '../../i18n/uiCopy'
import { useUiCopy } from '../../i18n/useUiCopy'

type RoleplayField = 'personality_traits' | 'ideals' | 'bonds' | 'flaws'

type RoleplayProfileEditorProps = {
  view: BuilderView
  disabled: boolean
  onSave: (payload: BuilderDraftPayload) => void
}

type RoleplaySuggestion = {
  suggestion_id: string
  field: RoleplayField
  position: number
  text: string
  missing_required: boolean
}

type BackgroundPresentation = {
  key: string
  locale: string
  roleplay_suggestions: RoleplaySuggestion[]
}

export type SystemSuggestionRef = {
  suggestion_id: string
  position: number
}

export type SystemSuggestionRefMap = Partial<Record<RoleplayField, SystemSuggestionRef[]>>

const FIELDS: {
  key: RoleplayField
  labelKey: UiCopyKey
  hintKey: UiCopyKey
}[] = [
  { key: 'personality_traits', labelKey: 'roleplay.personality', hintKey: 'roleplay.personalityHint' },
  { key: 'ideals', labelKey: 'roleplay.ideals', hintKey: 'roleplay.idealsHint' },
  { key: 'bonds', labelKey: 'roleplay.bonds', hintKey: 'roleplay.bondsHint' },
  { key: 'flaws', labelKey: 'roleplay.flaws', hintKey: 'roleplay.flawsHint' },
]

const EMPTY_SUGGESTIONS: RoleplaySuggestion[] = []

export function roleplayLines(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
}

export function roleplaySuggestionRefs(value: unknown): SystemSuggestionRefMap {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  const result: SystemSuggestionRefMap = {}
  for (const field of FIELDS) {
    const raw = (value as Record<string, unknown>)[field.key]
    if (!Array.isArray(raw)) continue
    const refs = raw
      .filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === 'object' && !Array.isArray(item),
      )
      .flatMap((item) => {
        const suggestionId = item.suggestion_id
        const position = item.position
        if (
          typeof suggestionId !== 'string' ||
          !suggestionId.trim() ||
          typeof position !== 'number' ||
          !Number.isInteger(position) ||
          position < 0
        ) {
          return []
        }
        return [{ suggestion_id: suggestionId, position }]
      })
    if (refs.length) result[field.key] = refs
  }
  return result
}

export function localizedRoleplayLines(
  value: unknown,
  refs: SystemSuggestionRef[] | undefined,
  suggestionTextById: Record<string, string>,
): string[] {
  const lines = roleplayLines(value)
  for (const ref of refs ?? []) {
    const localized = suggestionTextById[ref.suggestion_id]
    if (localized && ref.position < lines.length) lines[ref.position] = localized
  }
  return lines
}

function textFor(
  value: unknown,
  refs: SystemSuggestionRef[] | undefined,
  suggestionTextById: Record<string, string>,
): string {
  return localizedRoleplayLines(value, refs, suggestionTextById).join('\n')
}

export function parseRoleplayText(value: string): string[] {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

export function appendRoleplaySuggestion(text: string, suggestion: string): string[] {
  const current = parseRoleplayText(text)
  const normalized = suggestion.trim()
  if (!normalized || current.includes(normalized)) return current
  return [...current, normalized]
}

async function getBackgroundPresentation(
  reference: string,
  locale: string,
): Promise<BackgroundPresentation> {
  const response = await fetch(
    `/api/rules/presentation/${encodeURIComponent(reference)}?locale=${encodeURIComponent(locale)}`,
  )
  if (!response.ok) throw new Error(String(response.status))
  return (await response.json()) as BackgroundPresentation
}

export function RoleplayProfileEditor({
  view,
  disabled,
  onSave,
}: RoleplayProfileEditorProps) {
  const { t } = useUiCopy()
  const { locale } = useLocale()
  const profile = view.draft.draft_payload.roleplay_profile ?? {}
  const backgroundRef = view.draft.draft_payload.background_selection?.reference_id ?? ''
  const systemRefs = roleplaySuggestionRefs(profile.system_suggestion_refs)
  const [draftText, setDraftText] = useState<Record<RoleplayField, string>>({
    personality_traits: '',
    ideals: '',
    bonds: '',
    flaws: '',
  })

  const backgroundQuery = useQuery({
    queryKey: ['background-roleplay-suggestions', backgroundRef, locale],
    queryFn: () => getBackgroundPresentation(backgroundRef, locale),
    enabled: Boolean(backgroundRef),
  })
  const suggestions = backgroundQuery.data?.roleplay_suggestions ?? EMPTY_SUGGESTIONS
  const suggestionTextById = useMemo(
    () => Object.fromEntries(suggestions.map((suggestion) => [suggestion.suggestion_id, suggestion.text])),
    [suggestions],
  )

  useEffect(() => {
    setDraftText({
      personality_traits: textFor(
        profile.personality_traits,
        systemRefs.personality_traits,
        suggestionTextById,
      ),
      ideals: textFor(profile.ideals, systemRefs.ideals, suggestionTextById),
      bonds: textFor(profile.bonds, systemRefs.bonds, suggestionTextById),
      flaws: textFor(profile.flaws, systemRefs.flaws, suggestionTextById),
    })
  }, [
    profile.personality_traits,
    profile.ideals,
    profile.bonds,
    profile.flaws,
    profile.system_suggestion_refs,
    suggestionTextById,
  ])

  const saveField = (field: RoleplayField, text: string) => {
    const next = parseRoleplayText(text)
    const renderedCurrent = localizedRoleplayLines(
      profile[field],
      systemRefs[field],
      suggestionTextById,
    )
    if (JSON.stringify(next) === JSON.stringify(renderedCurrent)) return

    // Once the player manually changes a field, those lines become verbatim
    // player-authored text. Do not guess which edited line still corresponds to
    // a system suggestion.
    const nextRefs = { ...systemRefs }
    delete nextRefs[field]
    onSave({
      roleplay_profile: {
        ...profile,
        [field]: next,
        system_suggestion_refs: nextRefs,
      },
    })
  }

  const addSuggestion = (field: RoleplayField, suggestion: RoleplaySuggestion) => {
    const currentRefs = systemRefs[field] ?? []
    if (currentRefs.some((ref) => ref.suggestion_id === suggestion.suggestion_id)) return
    const next = appendRoleplaySuggestion(draftText[field], suggestion.text)
    const current = parseRoleplayText(draftText[field])
    if (JSON.stringify(next) === JSON.stringify(current)) return
    const ref: SystemSuggestionRef = {
      suggestion_id: suggestion.suggestion_id,
      position: next.length - 1,
    }
    setDraftText((value) => ({ ...value, [field]: next.join('\n') }))
    onSave({
      roleplay_profile: {
        ...profile,
        [field]: next,
        system_suggestion_refs: {
          ...systemRefs,
          [field]: [...currentRefs, ref],
        },
      },
    })
  }

  return (
    <div className="builder-optional roleplay-editor">
      <h3>
        {t('roleplay.title')} <span>{t('shared.optional')}</span>
      </h3>
      <p className="builder-hint">{t('roleplay.description')}</p>
      {!backgroundRef ? (
        <p className="builder-muted">{t('roleplay.chooseBackground')}</p>
      ) : null}
      {backgroundQuery.error ? (
        <div className="error-banner">
          {t('sheet.contentError', { message: backgroundQuery.error.message })}
        </div>
      ) : null}

      <div className="roleplay-grid">
        {FIELDS.map((field) => {
          const fieldSuggestions = suggestions.filter((suggestion) => suggestion.field === field.key)
          const selectedIds = new Set((systemRefs[field.key] ?? []).map((ref) => ref.suggestion_id))
          const label = t(field.labelKey)
          return (
            <div className="roleplay-field" key={field.key}>
              <label className="builder-field">
                <span>{label}</span>
                <textarea
                  value={draftText[field.key]}
                  disabled={disabled}
                  placeholder={t(field.hintKey)}
                  onChange={(event) =>
                    setDraftText((current) => ({
                      ...current,
                      [field.key]: event.target.value,
                    }))
                  }
                  onBlur={() => saveField(field.key, draftText[field.key])}
                />
              </label>
              {fieldSuggestions.length ? (
                <div className="roleplay-suggestions" aria-label={t('roleplay.suggestionsAria', { label })}>
                  {fieldSuggestions.map((suggestion) => (
                    <button
                      type="button"
                      className="roleplay-suggestion"
                      disabled={
                        disabled ||
                        selectedIds.has(suggestion.suggestion_id) ||
                        parseRoleplayText(draftText[field.key]).includes(suggestion.text)
                      }
                      key={suggestion.suggestion_id}
                      onClick={() => addSuggestion(field.key, suggestion)}
                    >
                      + {suggestion.text}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}
