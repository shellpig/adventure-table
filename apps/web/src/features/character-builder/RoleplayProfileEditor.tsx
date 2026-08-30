import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import type { BuilderDraftPayload, BuilderView } from '../../api/characterBuilder'


type RoleplayField = 'personality_traits' | 'ideals' | 'bonds' | 'flaws'

type RoleplayProfileEditorProps = {
  view: BuilderView
  disabled: boolean
  onSave: (payload: BuilderDraftPayload) => void
}

type BackgroundContent = {
  data?: {
    roleplay_suggestions?: Partial<Record<RoleplayField, string[]>>
  }
}

const FIELDS: { key: RoleplayField; label: string; hint: string }[] = [
  { key: 'personality_traits', label: 'Personality Traits', hint: 'Mannerisms, habits, and recognizable personality.' },
  { key: 'ideals', label: 'Ideals', hint: 'Principles and values that guide the character.' },
  { key: 'bonds', label: 'Bonds', hint: 'People, places, promises, or causes that matter.' },
  { key: 'flaws', label: 'Flaws', hint: 'Weaknesses, temptations, blind spots, or bad habits.' },
]

export function roleplayLines(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
}

function textFor(value: unknown): string {
  return roleplayLines(value).join('\n')
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

async function getBackgroundContent(reference: string): Promise<BackgroundContent> {
  const response = await fetch(`/api/rules/content/backgrounds/${encodeURIComponent(reference)}`)
  if (!response.ok) throw new Error(`Unable to load background suggestions (${response.status})`)
  return (await response.json()) as BackgroundContent
}

export function RoleplayProfileEditor({
  view,
  disabled,
  onSave,
}: RoleplayProfileEditorProps) {
  const profile = view.draft.draft_payload.roleplay_profile ?? {}
  const backgroundRef = view.draft.draft_payload.background_selection?.reference_id ?? ''
  const [draftText, setDraftText] = useState<Record<RoleplayField, string>>({
    personality_traits: '',
    ideals: '',
    bonds: '',
    flaws: '',
  })

  useEffect(() => {
    setDraftText({
      personality_traits: textFor(profile.personality_traits),
      ideals: textFor(profile.ideals),
      bonds: textFor(profile.bonds),
      flaws: textFor(profile.flaws),
    })
  }, [profile.personality_traits, profile.ideals, profile.bonds, profile.flaws])

  const backgroundQuery = useQuery({
    queryKey: ['background-roleplay-suggestions', backgroundRef],
    queryFn: () => getBackgroundContent(backgroundRef),
    enabled: Boolean(backgroundRef),
  })

  const saveField = (field: RoleplayField, text: string) => {
    const next = parseRoleplayText(text)
    const current = roleplayLines(profile[field])
    if (JSON.stringify(next) === JSON.stringify(current)) return
    onSave({
      roleplay_profile: {
        ...profile,
        [field]: next,
      },
    })
  }

  const addSuggestion = (field: RoleplayField, suggestion: string) => {
    const next = appendRoleplaySuggestion(draftText[field], suggestion)
    const current = parseRoleplayText(draftText[field])
    if (JSON.stringify(next) === JSON.stringify(current)) return
    setDraftText((value) => ({ ...value, [field]: next.join('\n') }))
    onSave({
      roleplay_profile: {
        ...profile,
        [field]: next,
      },
    })
  }

  const suggestions = backgroundQuery.data?.data?.roleplay_suggestions ?? {}

  return (
    <div className="builder-optional roleplay-editor">
      <h3>
        Roleplay Profile <span>Optional</span>
      </h3>
      <p className="builder-hint">
        Type your own notes, leave any field blank, or use a background suggestion. One line becomes one saved entry.
      </p>
      {!backgroundRef ? (
        <p className="builder-muted">Choose a background to reveal its suggested characteristics.</p>
      ) : null}
      {backgroundQuery.error ? (
        <div className="error-banner">{backgroundQuery.error.message}</div>
      ) : null}

      <div className="roleplay-grid">
        {FIELDS.map((field) => {
          const fieldSuggestions = suggestions[field.key] ?? []
          return (
            <div className="roleplay-field" key={field.key}>
              <label className="builder-field">
                <span>{field.label}</span>
                <textarea
                  value={draftText[field.key]}
                  disabled={disabled}
                  placeholder={field.hint}
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
                <div className="roleplay-suggestions" aria-label={`${field.label} suggestions`}>
                  {fieldSuggestions.map((suggestion) => (
                    <button
                      type="button"
                      className="roleplay-suggestion"
                      disabled={disabled || parseRoleplayText(draftText[field.key]).includes(suggestion)}
                      key={suggestion}
                      onClick={() => addSuggestion(field.key, suggestion)}
                    >
                      + {suggestion}
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
