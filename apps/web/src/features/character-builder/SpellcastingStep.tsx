import {
  type BuilderDraftPayload,
  type BuilderSpellChoiceInput,
  type BuilderSpellcastingProfileSummary,
  type BuilderSpellOptionSummary,
  type BuilderView,
} from '../../api/characterBuilder'
import { optionDisplay, SearchableSelect } from '../../components/SearchableSelect'
import type { UiCopyKey } from '../../i18n/uiCopy'
import { type ContentNameResolver, useContentPresentations } from '../../i18n/useContentPresentations'
import { useUiCopy, type UiTranslator } from '../../i18n/useUiCopy'
import './spellcasting.css'

type Props = {
  view: BuilderView
  disabled: boolean
  onSave: (payload: BuilderDraftPayload) => void
}

type SpellBucket = keyof Required<BuilderSpellChoiceInput>

const ACCESS_KEYS: Record<BuilderSpellcastingProfileSummary['access_model'], UiCopyKey> = {
  known: 'spells.access.known',
  prepared: 'spells.access.prepared',
  spellbook: 'spells.access.spellbook',
}

const ABILITY_LABELS: Record<string, string> = {
  intelligence: 'INT',
  wisdom: 'WIS',
  charisma: 'CHA',
}

function spellLabel(
  spell: BuilderSpellOptionSummary,
  t: UiTranslator,
  nameFor: ContentNameResolver,
) {
  const name = optionDisplay(nameFor(spell.spell_key, spell.name)).primary
  return spell.level === 0
    ? `${name} · ${t('spells.cantrip')}`
    : `${name} · ${t('spells.level', { level: spell.level })}`
}

function profileSelection(view: BuilderView, profileId: string): Required<BuilderSpellChoiceInput> {
  const raw = view.draft.draft_payload.spell_choices?.[profileId]
  return {
    cantrip_keys: raw?.cantrip_keys ?? [],
    known_spell_keys: raw?.known_spell_keys ?? [],
    spellbook_spell_keys: raw?.spellbook_spell_keys ?? [],
    prepared_spell_keys: raw?.prepared_spell_keys ?? [],
  }
}

function SpellBucketEditor({
  view,
  profile,
  bucket,
  label,
  help,
  target,
  exact,
  disabled,
  onSave,
  nameFor,
}: {
  view: BuilderView
  profile: BuilderSpellcastingProfileSummary
  bucket: SpellBucket
  label: string
  help: string
  target: number
  exact: boolean
  disabled: boolean
  onSave: (payload: BuilderDraftPayload) => void
  nameFor: ContentNameResolver
}) {
  const { t } = useUiCopy()
  const current = profileSelection(view, profile.profile_id)
  const selected = current[bucket]
  const isCantrip = bucket === 'cantrip_keys'
  const isWizardPrepared = bucket === 'prepared_spell_keys' && profile.access_model === 'spellbook'
  const options = profile.available_spells
    .filter((spell) => (isCantrip ? spell.level === 0 : spell.level > 0))
    .filter(
      (spell) => !isWizardPrepared || current.spellbook_spell_keys.includes(spell.spell_key),
    )
    .map((spell) => ({
      value: spell.spell_key,
      label: spellLabel(spell, t, nameFor),
      disabled: selected.includes(spell.spell_key),
      disabledReason: selected.includes(spell.spell_key) ? t('shared.alreadySelected') : undefined,
    }))
  const canAdd = selected.length < target

  const save = (next: string[]) => {
    onSave({
      spell_choices: {
        ...(view.draft.draft_payload.spell_choices ?? {}),
        [profile.profile_id]: {
          ...current,
          [bucket]: next,
        },
      },
    })
  }

  return (
    <div className="spell-bucket" data-testid={`spell-bucket-${profile.profile_id}-${bucket}`}>
      <div className="spell-bucket__heading">
        <div>
          <strong>{label}</strong>
          <small>{help}</small>
        </div>
        <span className={exact && selected.length !== target ? 'spell-count is-incomplete' : 'spell-count'}>
          {selected.length} / {target}{exact ? '' : t('spells.max')}
        </span>
      </div>

      {selected.length ? (
        <div className="spell-chips">
          {selected.map((spellKey) => {
            const spell = profile.available_spells.find((item) => item.spell_key === spellKey)
            return (
              <button
                type="button"
                key={spellKey}
                disabled={disabled}
                onClick={() => save(selected.filter((item) => item !== spellKey))}
              >
                <span>
                  {spell
                    ? optionDisplay(nameFor(spell.spell_key, spell.name)).primary
                    : nameFor(spellKey, t('shared.unknownSpell'))}
                </span>
                <small>{spell?.level === 0 ? t('spells.cantrip') : t('spells.slotLevel', { level: spell?.level ?? '?' })}</small>
                <b aria-hidden="true">×</b>
              </button>
            )
          })}
        </div>
      ) : (
        <p className="spell-empty">{t('spells.noSelections')}</p>
      )}

      <SearchableSelect
        label={t('spells.add', { label: label.toLocaleLowerCase() })}
        value=""
        disabled={disabled || !canAdd}
        options={options}
        placeholder={canAdd ? t('spells.search') : t('spells.limitReached')}
        onChange={(value) => {
          if (value && !selected.includes(value)) save([...selected, value])
        }}
      />
    </div>
  )
}

function SpellcastingProfile({
  view,
  profile,
  disabled,
  onSave,
  nameFor,
}: {
  view: BuilderView
  profile: BuilderSpellcastingProfileSummary
  disabled: boolean
  onSave: (payload: BuilderDraftPayload) => void
  nameFor: ContentNameResolver
}) {
  const { t } = useUiCopy()
  return (
    <section className="spell-profile" data-testid={`spell-profile-${profile.profile_id}`}>
      <div className="spell-profile__title">
        <div>
          <p className="eyebrow">{t(ACCESS_KEYS[profile.access_model])}</p>
          <h3>{nameFor(profile.source_key, profile.source_name)} {profile.class_level}</h3>
        </div>
        <div className="spell-profile__badges">
          <span>{ABILITY_LABELS[profile.ability] ?? profile.ability.toUpperCase()}</span>
          <span>{t('spells.maxSpellLevel', { level: profile.max_spell_level })}</span>
          <span>{profile.resource_pool_type === 'pact_magic' ? t('spells.pactMagic') : t('spells.sharedSlots')}</span>
        </div>
      </div>

      <div className="spell-profile__grid">
        {profile.cantrip_count > 0 ? (
          <SpellBucketEditor
            view={view}
            profile={profile}
            bucket="cantrip_keys"
            label={t('spells.cantrips')}
            help={t('spells.cantripsHelp')}
            target={profile.cantrip_count}
            exact
            disabled={disabled}
            onSave={onSave}
            nameFor={nameFor}
          />
        ) : null}

        {profile.known_spell_count > 0 ? (
          <SpellBucketEditor
            view={view}
            profile={profile}
            bucket="known_spell_keys"
            label={t('spells.known')}
            help={t('spells.knownHelp')}
            target={profile.known_spell_count}
            exact
            disabled={disabled}
            onSave={onSave}
            nameFor={nameFor}
          />
        ) : null}

        {profile.spellbook_count > 0 ? (
          <SpellBucketEditor
            view={view}
            profile={profile}
            bucket="spellbook_spell_keys"
            label={t('spells.spellbook')}
            help={t('spells.spellbookHelp')}
            target={profile.spellbook_count}
            exact
            disabled={disabled}
            onSave={onSave}
            nameFor={nameFor}
          />
        ) : null}

        {profile.prepared_limit != null ? (
          <SpellBucketEditor
            view={view}
            profile={profile}
            bucket="prepared_spell_keys"
            label={t('spells.prepared')}
            help={
              profile.access_model === 'spellbook'
                ? t('spells.preparedWizardHelp')
                : t('spells.preparedHelp')
            }
            target={profile.prepared_limit}
            exact={false}
            disabled={disabled}
            onSave={onSave}
            nameFor={nameFor}
          />
        ) : null}
      </div>
    </section>
  )
}

export function SpellcastingStep({ view, disabled, onSave }: Props) {
  const { t } = useUiCopy()
  const profiles = view.resolved_summary.spellcasting_profiles ?? []
  const pools = view.resolved_summary.spell_resource_pools ?? []
  const contentReferences = profiles.flatMap((profile) => [
    profile.source_key,
    profile.class_ref,
    ...profile.available_spells.map((spell) => spell.spell_key),
  ])
  const { nameFor } = useContentPresentations(contentReferences)

  return (
    <div className="builder-step spellcasting-step">
      <div className="builder-step__heading">
        <p className="eyebrow">{t('spells.step')}</p>
        <h2>{t('spells.title')}</h2>
        <p>{t('spells.description')}</p>
      </div>

      {pools.length ? (
        <div className="spell-pools" aria-label={t('spells.resourcesAria')}>
          {pools.map((pool) => {
            const sourceProfile = profiles.find((profile) => profile.profile_id === pool.source_profile_id)
            return (
              <section key={pool.pool_id} className="spell-pool">
                <div>
                  <span>{pool.pool_type === 'pact_magic' ? t('spells.pactMagic') : t('spells.combinedSlots')}</span>
                  <strong>
                    {sourceProfile
                      ? nameFor(sourceProfile.source_key, sourceProfile.source_name)
                      : pool.pool_id.endsWith(':combined')
                        ? t('spells.multiclass')
                        : t('spells.normal')}
                  </strong>
                </div>
                <div className="spell-pool__slots">
                  {pool.slots.map((slot) => (
                    <span key={slot.level}>{t('spells.slotLevel', { level: slot.level })} <b>×{slot.count}</b></span>
                  ))}
                </div>
              </section>
            )
          })}
        </div>
      ) : null}

      {profiles.length ? (
        <div className="spell-profiles">
          {profiles.map((profile) => (
            <SpellcastingProfile
              key={profile.profile_id}
              view={view}
              profile={profile}
              disabled={disabled}
              onSave={onSave}
              nameFor={nameFor}
            />
          ))}
        </div>
      ) : (
        <div className="spell-no-source">
          <strong>{t('spells.noSource')}</strong>
          <p>{t('spells.noSourceHint')}</p>
        </div>
      )}

      <aside className="spellcasting-note">
        <strong>{t('spells.identityTitle')}</strong>
        <p>{t('spells.identityHint')}</p>
      </aside>
    </div>
  )
}
