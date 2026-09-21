import React from 'react'

import type { RoomCharacterSummary } from '../../api/campaigns'
import type {
  RuntimeEntryKind,
  RuntimeItemHolderKind,
  RuntimeVisibility,
  RuntimeWorldEntryDmView,
} from '../../api/campaignRuntime'
import {
  entryKindLabel,
  itemHolderKindLabel,
  visibilityLabel,
  type CampaignRuntimeCopy,
} from './campaignRuntimeCopy'
import {
  EDITABLE_RUNTIME_ENTRY_KINDS,
  isEditableRuntimeEntryKind,
  onFormKindChange,
  onFormVisibilityChange,
  type EditableRuntimeEntryKind,
  type RuntimeEntryFormState,
} from './campaignRuntimeForm'
import './rooms.css'

export type RuntimeEntryCardActions = {
  disabled: boolean
  onEdit?: (entry: RuntimeWorldEntryDmView) => void
  onArchive: (entry: RuntimeWorldEntryDmView) => void
}

export type RuntimeEntryCardViewProps = {
  entry: RuntimeWorldEntryDmView
  entries: RuntimeWorldEntryDmView[]
  characters: RoomCharacterSummary[]
  actions: RuntimeEntryCardActions | null
  copy: CampaignRuntimeCopy
}

export function RuntimeEntryCardView({
  entry,
  entries,
  characters,
  actions,
  copy,
}: RuntimeEntryCardViewProps) {
  return (
    <article className="adventure-entry runtime-entry-card" key={entry.id}>
      <div className="adventure-entry__content">
        <div className="adventure-entry__meta">
          <span className="adventure-entry__kind">{entryKindLabel(entry.kind, copy)}</span>
          <span className="adventure-entry__visibility">{visibilityLabel(entry.visibility, copy)}</span>
          {entry.needs_review ? (
            <span className="runtime-entry__badge">{copy.needsReviewBadge}</span>
          ) : null}
          <span className="runtime-entry__revision">
            {copy.revisionLabel} {entry.revision}
          </span>
        </div>
        {entry.title ? <h3 className="adventure-entry__title">{entry.title}</h3> : null}
        {entry.body ? <p className="adventure-entry__body">{entry.body}</p> : null}
        {entry.visibility === 'character' ? (
          <div className="runtime-entry__recipients">
            <strong>{copy.recipientsLabel}: </strong>
            <span>
              {entry.character_recipient_ids.length > 0
                ? entry.character_recipient_ids
                    .map((id) => characters.find((c) => c.id === id)?.name ?? id)
                    .join(', ')
                : copy.recipientsNone}
            </span>
          </div>
        ) : null}

        {entry.kind === 'npc' && entry.state.kind === 'npc' ? (
          <>
            {entry.state.monster_instance_id ? (
              <p className="runtime-entry__typed-field">
                <strong>{copy.monsterInstanceIdLabel}: </strong>
                <code>{entry.state.monster_instance_id}</code>
              </p>
            ) : null}
            {entry.state.monster_template_ref ? (
              <p className="runtime-entry__typed-field">
                <strong>{copy.monsterTemplateRefLabel}: </strong>
                <span>{entry.state.monster_template_ref}</span>
              </p>
            ) : null}
          </>
        ) : null}

        {entry.kind === 'item' && entry.state.kind === 'item' && entry.state.holder_ref ? (
          (() => {
            const holder = entry.state.holder_ref
            let targetDisplay: string | null = null
            if (holder.kind === 'scene' || holder.kind === 'npc') {
              if (holder.target_id) {
                const targetEntry = entries.find((e) => e.id === holder.target_id)
                targetDisplay = targetEntry?.title || holder.target_id
              }
            } else if (holder.kind === 'character') {
              if (holder.target_id) {
                const targetChar = characters.find((c) => c.id === holder.target_id)
                targetDisplay = targetChar?.name || holder.target_id
              }
            }
            return (
              <p className="runtime-entry__typed-field">
                <strong>{copy.itemHolderKindLabel}: </strong>
                <span>{itemHolderKindLabel(holder.kind, copy)}</span>
                {targetDisplay ? <span> ({targetDisplay})</span> : null}
              </p>
            )
          })()
        ) : null}

        {entry.kind === 'other' &&
        entry.state.kind === 'other' &&
        entry.state.data &&
        Object.keys(entry.state.data).length > 0 ? (
          <div className="runtime-entry__typed-field">
            <strong>{copy.otherDataLabel}: </strong>
            <pre className="runtime-entry__json">
              <code>{JSON.stringify(entry.state.data, null, 2)}</code>
            </pre>
          </div>
        ) : null}

        {entry.dm_notes ? (
          <p className="runtime-entry__dm-notes">
            <strong>{copy.dmNotesLabel}: </strong>
            <span>{entry.dm_notes}</span>
          </p>
        ) : null}
        {entry.source_adventure_entry_id ? (
          <p className="runtime-entry__provenance">
            <strong>{copy.readOnlyProvenance}: </strong>
            <code>{entry.source_adventure_entry_id}</code>
          </p>
        ) : null}
        {entry.provenance_json ? (
          <pre className="runtime-entry__json">
            <code>{JSON.stringify(entry.provenance_json, null, 2)}</code>
          </pre>
        ) : null}
      </div>
      {actions ? (
        (() => {
          const onEdit = entry.kind !== 'hazard' ? actions.onEdit : undefined
          const onArchive = actions.onArchive
          return (
            <div className="adventure-entry__actions">
              {onEdit ? (
                <button
                  className="button secondary"
                  type="button"
                  onClick={() => onEdit(entry)}
                  disabled={actions.disabled}
                >
                  {copy.editEntryButton}
                </button>
              ) : null}
              <button
                className="button danger"
                type="button"
                onClick={() => onArchive(entry)}
                disabled={actions.disabled || Boolean(entry.archived_at)}
              >
                {copy.archiveEntryButton}
              </button>
            </div>
          )
        })()
      ) : null}
    </article>
  )
}

export type RuntimeEntryFormViewProps = {
  form: RuntimeEntryFormState
  onChange: (updater: (prev: RuntimeEntryFormState) => RuntimeEntryFormState) => void
  onSubmit: (e: React.FormEvent) => void
  onCancel: () => void
  entries: RuntimeWorldEntryDmView[]
  characters: RoomCharacterSummary[]
  pending: boolean
  formError: string | null
  copy: CampaignRuntimeCopy
  kindOptions: readonly EditableRuntimeEntryKind[]
}

export function RuntimeEntryFormView({
  form,
  onChange,
  onSubmit,
  onCancel,
  entries,
  characters,
  pending,
  formError,
  copy,
  kindOptions,
}: RuntimeEntryFormViewProps) {
  return (
    <form className="room-form landing-card room-workspace-card" onSubmit={onSubmit}>
      <h3>{form.mode === 'create' ? copy.formTitleCreate : copy.formTitleEdit}</h3>
      {formError ? <p className="form-error">{formError}</p> : null}

      {form.mode === 'create' ? (
        <label className="room-field">
          <span>{copy.kindLabel}</span>
          <select
            value={form.kind}
            disabled={pending}
            onChange={(e) => {
              const val = e.target.value
              if (isEditableRuntimeEntryKind(val) && kindOptions.includes(val)) {
                onChange((prev) => onFormKindChange(prev, val))
              }
            }}
          >
            {kindOptions.map((k) => (
              <option key={k} value={k}>
                {entryKindLabel(k, copy)}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <div className="room-field">
          <span>{copy.kindLabel}</span>
          <strong>{entryKindLabel(form.kind, copy)}</strong>
        </div>
      )}

      <label className="room-field">
        <span>{copy.titleLabel}</span>
        <input
          type="text"
          value={form.title}
          maxLength={200}
          disabled={pending}
          onChange={(e) => onChange((prev) => ({ ...prev, title: e.target.value }))}
        />
      </label>

      <label className="room-field">
        <span>{copy.bodyLabel}</span>
        <textarea
          value={form.body}
          disabled={pending}
          onChange={(e) => onChange((prev) => ({ ...prev, body: e.target.value }))}
        />
      </label>

      <label className="room-field">
        <span>{copy.visibilityLabel}</span>
        <select
          value={form.visibility}
          disabled={pending}
          onChange={(e) =>
            onChange((prev) => onFormVisibilityChange(prev, e.target.value as RuntimeVisibility))
          }
        >
          <option value="public">{copy.visibilityPublic}</option>
          <option value="dm_only">{copy.visibilityDmOnly}</option>
          <option value="character">{copy.visibilityCharacter}</option>
        </select>
      </label>

      {form.visibility === 'character' ? (
        <div className="room-field">
          <span>{copy.recipientsLabel}</span>
          {characters.length === 0 ? (
            <p className="room-empty-text">{copy.noCharactersAvailable}</p>
          ) : (
            <div className="character-recipient-list">
              {characters.map((char) => {
                const isChecked = form.characterRecipientIds.includes(char.id)
                return (
                  <label key={char.id} className="room-field room-field--inline">
                    <input
                      type="checkbox"
                      checked={isChecked}
                      disabled={pending}
                      onChange={(e) => {
                        const checked = e.target.checked
                        onChange((prev) => ({
                          ...prev,
                          characterRecipientIds: checked
                            ? [...prev.characterRecipientIds, char.id]
                            : prev.characterRecipientIds.filter((id) => id !== char.id),
                        }))
                      }}
                    />
                    <span>{char.name}</span>
                  </label>
                )
              })}
            </div>
          )}
        </div>
      ) : null}

      {form.kind === 'npc' ? (
        <>
          <label className="room-field">
            <span>{copy.monsterInstanceIdLabel}</span>
            <input
              type="text"
              value={form.npcMonsterInstanceId}
              disabled={pending}
              onChange={(e) =>
                onChange((prev) => ({ ...prev, npcMonsterInstanceId: e.target.value }))
              }
            />
          </label>
          <label className="room-field">
            <span>{copy.monsterTemplateRefLabel}</span>
            <input
              type="text"
              value={form.npcMonsterTemplateRef}
              disabled={pending}
              onChange={(e) =>
                onChange((prev) => ({ ...prev, npcMonsterTemplateRef: e.target.value }))
              }
            />
          </label>
        </>
      ) : null}

      {form.kind === 'item' ? (
        <>
          <label className="room-field">
            <span>{copy.itemHolderKindLabel}</span>
            <select
              value={form.itemHolderKind}
              disabled={pending}
              onChange={(e) => {
                const nextKind = e.target.value as '' | RuntimeItemHolderKind
                onChange((prev) => ({
                  ...prev,
                  itemHolderKind: nextKind,
                  itemHolderTargetId: '',
                }))
              }}
            >
              <option value="">{itemHolderKindLabel('', copy)}</option>
              <option value="scene">{itemHolderKindLabel('scene', copy)}</option>
              <option value="npc">{itemHolderKindLabel('npc', copy)}</option>
              <option value="character">{itemHolderKindLabel('character', copy)}</option>
              <option value="party">{itemHolderKindLabel('party', copy)}</option>
              <option value="unknown">{itemHolderKindLabel('unknown', copy)}</option>
            </select>
          </label>
          {form.itemHolderKind === 'scene' || form.itemHolderKind === 'npc' ? (
            <label className="room-field">
              <span>{copy.itemHolderTargetLabel}</span>
              {(() => {
                const available = entries.filter(
                  (e) => e.kind === form.itemHolderKind && !e.archived_at,
                )
                if (available.length === 0) {
                  return (
                    <select disabled value="">
                      <option value="">{copy.noTargetOptions}</option>
                    </select>
                  )
                }
                return (
                  <select
                    value={form.itemHolderTargetId}
                    disabled={pending}
                    onChange={(e) =>
                      onChange((prev) => ({ ...prev, itemHolderTargetId: e.target.value }))
                    }
                  >
                    <option value="">--</option>
                    {available.map((e) => (
                      <option key={e.id} value={e.id}>
                        {e.title || e.id}
                      </option>
                    ))}
                  </select>
                )
              })()}
            </label>
          ) : null}
          {form.itemHolderKind === 'character' ? (
            <label className="room-field">
              <span>{copy.itemHolderTargetLabel}</span>
              {characters.length === 0 ? (
                <select disabled value="">
                  <option value="">{copy.noTargetOptions}</option>
                </select>
              ) : (
                <select
                  value={form.itemHolderTargetId}
                  disabled={pending}
                  onChange={(e) =>
                    onChange((prev) => ({ ...prev, itemHolderTargetId: e.target.value }))
                  }
                >
                  <option value="">--</option>
                  {characters.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              )}
            </label>
          ) : null}
        </>
      ) : null}

      {form.kind === 'other' ? (
        <label className="room-field">
          <span>{copy.otherDataLabel}</span>
          <textarea
            value={form.otherDataJson}
            disabled={pending}
            onChange={(e) => onChange((prev) => ({ ...prev, otherDataJson: e.target.value }))}
          />
        </label>
      ) : null}

      <label className="room-field">
        <span>{copy.dmNotesLabel}</span>
        <textarea
          value={form.dmNotes}
          disabled={pending}
          onChange={(e) => onChange((prev) => ({ ...prev, dmNotes: e.target.value }))}
        />
      </label>

      <label className="room-field room-field--inline">
        <input
          type="checkbox"
          checked={form.needsReview}
          disabled={pending}
          onChange={(e) => onChange((prev) => ({ ...prev, needsReview: e.target.checked }))}
        />
        <span>{copy.needsReviewLabel}</span>
      </label>

      {form.mode === 'edit' && form.sourceAdventureEntryId ? (
        <div className="room-field">
          <span>{copy.sourceAdventureEntryLabel}</span>
          <code>{form.sourceAdventureEntryId}</code>
        </div>
      ) : null}

      <label className="room-field">
        <span>{copy.provenanceJsonLabel}</span>
        <textarea
          value={form.provenanceJson}
          disabled={pending}
          onChange={(e) => onChange((prev) => ({ ...prev, provenanceJson: e.target.value }))}
        />
      </label>

      <div className="adventure-card__actions">
        <button className="button primary" disabled={pending} type="submit">
          {pending
            ? copy.submitting
            : form.mode === 'create'
              ? copy.submitCreate
              : copy.submitUpdate}
        </button>
        <button className="button secondary" disabled={pending} onClick={onCancel} type="button">
          {copy.cancelButton}
        </button>
      </div>
    </form>
  )
}
