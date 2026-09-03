import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getCharacterSheet,
  patchCharacterState,
  type CharacterSheetDTO,
} from '../../api/character'
import { useContentPresentations } from '../../i18n/useContentPresentations'
import { CharacterSheetRoutePage as BaseCharacterSheetRoutePage } from '../artificer/ArtificerRoutePanels'

const M01M_SOURCES = ('mtf:', 'scag:') as const

const COPY = {
  en: {
    eyebrow: 'M01-M · Ancestry Current State',
    title: 'Ancestry State',
    mode: 'Current ancestry mode',
    saveMode: 'Save mode',
    longRestTiming: 'This mode may be changed after a long rest. Rest automation is not implemented yet, so the timing remains player/DM enforced.',
    manualTiming: 'This is live Current State and does not create a new Build Version.',
    casting: 'Ancestry casting facts',
    castAt: 'Cast at level {level}',
    noSlot: 'Does not use a spell slot',
    waived: 'Components waived: {components}',
  },
  'zh-TW': {
    eyebrow: 'M01-M · 祖源即時狀態',
    title: '祖源狀態',
    mode: '目前祖源模式',
    saveMode: '儲存模式',
    longRestTiming: '此模式可在長休後變更。目前尚未實作正式休息交易，因此變更時點仍由玩家／DM自行確認。',
    manualTiming: '這是即時狀態，不會因此建立新的角色配置版本。',
    casting: '祖源施法資訊',
    castAt: '以 {level} 環施展',
    noSlot: '不消耗法術位',
    waived: '免除成分：{components}',
  },
} as const

type PanelLocale = keyof typeof COPY

const MODE_LABELS_ZH: Record<string, string> = {
  'eladrin-season': '季節形態',
}

const OPTION_LABELS_ZH: Record<string, string> = {
  autumn: '秋季',
  winter: '冬季',
  spring: '春季',
  summer: '夏季',
}

function isM01MSource(reference: string): boolean {
  return M01M_SOURCES.some((prefix) => reference.startsWith(prefix))
}

function modeLabel(locale: PanelLocale, key: string): string {
  if (locale === 'zh-TW') return MODE_LABELS_ZH[key] ?? key
  return key.replaceAll('-', ' ')
}

function optionLabel(locale: PanelLocale, value: string): string {
  if (locale === 'zh-TW') return OPTION_LABELS_ZH[value] ?? value
  return value.replaceAll('-', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function interpolate(template: string, params: Record<string, string | number>): string {
  return Object.entries(params).reduce(
    (result, [key, value]) => result.replaceAll(`{${key}}`, String(value)),
    template,
  )
}

function M01MAncestryPanel({
  sheet,
  busy,
  errorMessage,
  onPatch,
}: {
  sheet: CharacterSheetDTO
  busy: boolean
  errorMessage?: string | null
  onPatch: (featureModes: Record<string, string>) => Promise<void>
}) {
  const definitions = (sheet.feature_mode_definitions ?? []).filter((definition) =>
    isM01MSource(definition.source_feature_ref),
  )
  const ancestrySpells = sheet.spells.filter(
    (spell) =>
      isM01MSource(spell.source_key) &&
      (spell.cast_at_level != null || spell.waive_components?.length || spell.uses_spell_slot === false),
  )
  const references = [
    ...definitions.map((definition) => definition.source_feature_ref),
    ...ancestrySpells.flatMap((spell) => [spell.spell_key, spell.source_key]),
  ]
  const { locale, nameFor } = useContentPresentations(references)
  const copy = COPY[locale]

  if (!definitions.length && !ancestrySpells.length) return null

  return (
    <section className="artificer-route-panel" aria-label={copy.title}>
      <div className="artificer-panel-heading">
        <div>
          <p className="eyebrow">{copy.eyebrow}</p>
          <h2>{copy.title}</h2>
        </div>
      </div>

      {errorMessage ? <div className="error-banner" role="alert">{errorMessage}</div> : null}

      {definitions.map((definition) => {
        const selected =
          sheet.feature_modes?.[definition.key] ?? definition.default
        const timingCopy =
          definition.change_timing === 'manual_after_long_rest'
            ? copy.longRestTiming
            : copy.manualTiming
        return (
          <section className="artificer-subsection" key={definition.key}>
            <h3>{modeLabel(locale, definition.key)}</h3>
            <div className="artificer-inline-form">
              <label>
                <span>{copy.mode}</span>
                <select
                  value={selected}
                  disabled={busy}
                  data-testid={`feature-mode-${definition.key}`}
                  onChange={(event) =>
                    void onPatch({
                      ...(sheet.feature_modes ?? {}),
                      [definition.key]: event.target.value,
                    })
                  }
                >
                  {definition.options.map((option) => (
                    <option key={option} value={option}>
                      {optionLabel(locale, option)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <p className="artificer-note">{timingCopy}</p>
          </section>
        )
      })}

      {ancestrySpells.length ? (
        <section className="artificer-subsection">
          <h3>{copy.casting}</h3>
          <div className="artificer-resource-list">
            {ancestrySpells.map((spell) => {
              const facts: string[] = []
              if (spell.cast_at_level != null) {
                facts.push(interpolate(copy.castAt, { level: spell.cast_at_level }))
              }
              if (spell.uses_spell_slot === false) facts.push(copy.noSlot)
              if (spell.waive_components?.length) {
                facts.push(
                  interpolate(copy.waived, {
                    components: spell.waive_components.join(', '),
                  }),
                )
              }
              return (
                <div key={spell.entry_id}>
                  <span>{nameFor(spell.spell_key, spell.name)}</span>
                  <strong>{facts.join(' · ')}</strong>
                </div>
              )
            })}
          </div>
        </section>
      ) : null}
    </section>
  )
}

export function CharacterSheetRoutePage({ characterId }: { characterId: string }) {
  const queryClient = useQueryClient()
  const sheetQuery = useQuery({
    queryKey: ['character-sheet', characterId],
    queryFn: () => getCharacterSheet(characterId),
  })
  const mutation = useMutation({
    mutationFn: (featureModes: Record<string, string>) =>
      patchCharacterState(characterId, { feature_modes: featureModes }),
    onSuccess: (next) =>
      queryClient.setQueryData(['character-sheet', characterId], next),
  })

  return (
    <>
      <BaseCharacterSheetRoutePage characterId={characterId} />
      {sheetQuery.data ? (
        <M01MAncestryPanel
          sheet={sheetQuery.data}
          busy={mutation.isPending}
          errorMessage={mutation.error instanceof Error ? mutation.error.message : null}
          onPatch={async (featureModes) => {
            await mutation.mutateAsync(featureModes)
          }}
        />
      ) : null}
    </>
  )
}
