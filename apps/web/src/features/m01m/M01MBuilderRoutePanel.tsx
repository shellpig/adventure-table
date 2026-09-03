import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getBuilderDraft,
  patchBuilderDraft,
  type BuilderView,
} from '../../api/characterBuilder'
import { useContentPresentations } from '../../i18n/useContentPresentations'
import { CharacterBuilderRoutePage as BaseCharacterBuilderRoutePage } from '../artificer/ArtificerRoutePanels'

const SCAG_TIEFLING_VARIANT = 'scag:race-variant:tiefling-variants'
const APPEARANCE_FIELDS = Array.from(
  { length: 12 },
  (_, index) => `data.appearance_suggestions.${index}`,
)

const COPY = {
  en: {
    eyebrow: 'M01-M · Optional Roleplay Helper',
    title: 'Tiefling Appearance',
    hint: 'Optional. Add a supplied SCAG appearance suggestion to the existing appearance text. This never changes ancestry legality or Build mechanics.',
    add: 'Add',
    added: 'Added',
  },
  'zh-TW': {
    eyebrow: 'M01-M · 選用角色扮演輔助',
    title: '提夫林外貌',
    hint: '完全選填。可把 SCAG 提供的外貌建議加入既有外貌文字；這不會改變祖源合法性或任何角色配置規則。',
    add: '加入',
    added: '已加入',
  },
} as const

function M01MAppearancePanel({ view }: { view: BuilderView }) {
  const queryClient = useQueryClient()
  const { locale, fieldFor } = useContentPresentations(
    [SCAG_TIEFLING_VARIANT],
    { [SCAG_TIEFLING_VARIANT]: APPEARANCE_FIELDS },
  )
  const copy = COPY[locale]
  const currentAppearance = String(
    view.draft.draft_payload.roleplay_profile?.appearance ?? '',
  ).trim()
  const suggestions = APPEARANCE_FIELDS.map((fieldPath) =>
    fieldFor(SCAG_TIEFLING_VARIANT, fieldPath, ''),
  ).filter(Boolean)

  const mutation = useMutation({
    mutationFn: (suggestion: string) => {
      const appearance = currentAppearance
        ? `${currentAppearance} · ${suggestion}`
        : suggestion
      return patchBuilderDraft(view.draft.id, view.draft.revision, {
        roleplay_profile: { appearance },
      })
    },
    onSuccess: (next) => {
      queryClient.setQueryData(['builder-draft', view.draft.id], next)
    },
  })

  return (
    <section className="artificer-route-panel" aria-label={copy.title}>
      <div className="artificer-panel-heading">
        <div>
          <p className="eyebrow">{copy.eyebrow}</p>
          <h2>{copy.title}</h2>
          <p>{copy.hint}</p>
        </div>
      </div>

      {mutation.error instanceof Error ? (
        <div className="error-banner" role="alert">{mutation.error.message}</div>
      ) : null}

      <div className="artificer-resource-list">
        {suggestions.map((suggestion) => {
          const alreadyAdded = currentAppearance.includes(suggestion)
          return (
            <div key={suggestion}>
              <span>{suggestion}</span>
              <button
                type="button"
                className="button secondary compact"
                disabled={mutation.isPending || alreadyAdded}
                onClick={() => mutation.mutate(suggestion)}
              >
                {alreadyAdded ? copy.added : copy.add}
              </button>
            </div>
          )
        })}
      </div>
    </section>
  )
}

export function CharacterBuilderRoutePage({ draftId }: { draftId: string }) {
  const draftQuery = useQuery({
    queryKey: ['builder-draft', draftId],
    queryFn: () => getBuilderDraft(draftId),
  })
  const selectedVariant =
    draftQuery.data?.draft.draft_payload.race_variant_selection?.reference_id

  return (
    <>
      <BaseCharacterBuilderRoutePage draftId={draftId} />
      {draftQuery.data && selectedVariant === SCAG_TIEFLING_VARIANT ? (
        <M01MAppearancePanel view={draftQuery.data} />
      ) : null}
    </>
  )
}
