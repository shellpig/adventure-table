import {
  type BuilderDraftPayload,
  type BuilderSpellChoiceInput,
  type BuilderSpellcastingProfileSummary,
  type BuilderSpellOptionSummary,
  type BuilderView,
} from '../../api/characterBuilder'
import { SearchableSelect } from '../../components/SearchableSelect'
import './spellcasting.css'


type Props = {
  view: BuilderView
  disabled: boolean
  onSave: (payload: BuilderDraftPayload) => void
}

type SpellBucket = keyof Required<BuilderSpellChoiceInput>

const ACCESS_LABELS = {
  known: 'Known spells',
  prepared: 'Prepared caster',
  spellbook: 'Spellbook',
} as const

const ABILITY_LABELS: Record<string, string> = {
  intelligence: 'INT',
  wisdom: 'WIS',
  charisma: 'CHA',
}

function spellLabel(spell: BuilderSpellOptionSummary) {
  return spell.level === 0 ? `${spell.name} · Cantrip` : `${spell.name} · Level ${spell.level}`
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
}) {
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
      label: spellLabel(spell),
      disabled: selected.includes(spell.spell_key),
      disabledReason: selected.includes(spell.spell_key) ? 'Already selected' : undefined,
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
          {selected.length} / {target}{exact ? '' : ' max'}
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
                <span>{spell?.name ?? 'Unknown spell'}</span>
                <small>{spell?.level === 0 ? 'Cantrip' : `Lv ${spell?.level ?? '?'}`}</small>
                <b aria-hidden="true">×</b>
              </button>
            )
          })}
        </div>
      ) : (
        <p className="spell-empty">No selections yet.</p>
      )}

      <SearchableSelect
        label={`Add ${label.toLowerCase()}`}
        value=""
        disabled={disabled || !canAdd}
        options={options}
        placeholder={canAdd ? 'Search spell name or open list' : 'Selection limit reached'}
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
}: {
  view: BuilderView
  profile: BuilderSpellcastingProfileSummary
  disabled: boolean
  onSave: (payload: BuilderDraftPayload) => void
}) {
  return (
    <section className="spell-profile" data-testid={`spell-profile-${profile.profile_id}`}>
      <div className="spell-profile__title">
        <div>
          <p className="eyebrow">{ACCESS_LABELS[profile.access_model]}</p>
          <h3>{profile.source_name} {profile.class_level}</h3>
        </div>
        <div className="spell-profile__badges">
          <span>{ABILITY_LABELS[profile.ability] ?? profile.ability.toUpperCase()}</span>
          <span>Max spell Lv {profile.max_spell_level}</span>
          <span>{profile.resource_pool_type === 'pact_magic' ? 'Pact Magic' : 'Shared slots'}</span>
        </div>
      </div>

      <div className="spell-profile__grid">
        {profile.cantrip_count > 0 ? (
          <SpellBucketEditor
            view={view}
            profile={profile}
            bucket="cantrip_keys"
            label="Cantrips"
            help="Permanent class access. Cantrips do not consume spell slots."
            target={profile.cantrip_count}
            exact
            disabled={disabled}
            onSave={onSave}
          />
        ) : null}

        {profile.known_spell_count > 0 ? (
          <SpellBucketEditor
            view={view}
            profile={profile}
            bucket="known_spell_keys"
            label="Known spells"
            help="Stored in Build with this class source; the server validates count and acquisition order."
            target={profile.known_spell_count}
            exact
            disabled={disabled}
            onSave={onSave}
          />
        ) : null}

        {profile.spellbook_count > 0 ? (
          <SpellBucketEditor
            view={view}
            profile={profile}
            bucket="spellbook_spell_keys"
            label="Spellbook"
            help="Long-term Wizard access. This is deliberately separate from the daily prepared list."
            target={profile.spellbook_count}
            exact
            disabled={disabled}
            onSave={onSave}
          />
        ) : null}

        {profile.prepared_limit != null ? (
          <SpellBucketEditor
            view={view}
            profile={profile}
            bucket="prepared_spell_keys"
            label="Initial prepared spells"
            help={
              profile.access_model === 'spellbook'
                ? 'Live-state seed. Every prepared spell must already exist in this Wizard spellbook.'
                : 'Live-state seed from the class spell list. You may prepare fewer than the maximum.'
            }
            target={profile.prepared_limit}
            exact={false}
            disabled={disabled}
            onSave={onSave}
          />
        ) : null}
      </div>
    </section>
  )
}

export function SpellcastingStep({ view, disabled, onSave }: Props) {
  const profiles = view.resolved_summary.spellcasting_profiles ?? []
  const pools = view.resolved_summary.spell_resource_pools ?? []

  return (
    <div className="builder-step spellcasting-step">
      <div className="builder-step__heading">
        <p className="eyebrow">STEP 05</p>
        <h2>Spellcasting & resources</h2>
        <p>
          Spell access stays attached to its source. Known spells and Wizard spellbook entries live in
          Build; the initial prepared list is live state. Multiclass spell slots are shared only where
          the 2014 rules say they are, while Warlock Pact Magic stays in its own pool.
        </p>
      </div>

      {pools.length ? (
        <div className="spell-pools" aria-label="Spell resource capacities">
          {pools.map((pool) => (
            <section key={pool.pool_id} className="spell-pool">
              <div>
                <span>{pool.pool_type === 'pact_magic' ? 'Pact Magic' : 'Combined spell slots'}</span>
                <strong>
                  {pool.source_profile_id?.split(':').at(-1)?.replaceAll('-', ' ') ??
                    (pool.pool_id.endsWith(':combined') ? 'Multiclass' : 'Normal')}
                </strong>
              </div>
              <div className="spell-pool__slots">
                {pool.slots.map((slot) => (
                  <span key={slot.level}>Lv {slot.level} <b>×{slot.count}</b></span>
                ))}
              </div>
            </section>
          ))}
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
            />
          ))}
        </div>
      ) : (
        <div className="spell-no-source">
          <strong>No spellcasting source in this progression.</strong>
          <p>This step has nothing to select for the current classes.</p>
        </div>
      )}

      <aside className="spellcasting-note">
        <strong>Source identity is preserved.</strong>
        <p>
          If the same spell comes from two classes, subclasses or features, the server keeps separate
          access entries instead of collapsing them by spell name. Always-prepared / granted spells are
          likewise Build access and do not consume your daily preparation allowance.
        </p>
      </aside>
    </div>
  )
}
