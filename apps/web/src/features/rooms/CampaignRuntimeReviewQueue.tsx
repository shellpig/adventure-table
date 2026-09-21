import React from 'react'

import type {
  CampaignAdventureEntryOverlayView,
  RuntimeWorldEntryDmView,
} from '../../api/campaignRuntime'
import {
  adventureEntryKindLabel,
  entryKindLabel,
  type CampaignRuntimeCopy,
} from './campaignRuntimeCopy'
import type { ReviewQueueItem } from './campaignRuntimeOverrideForm'
import './rooms.css'

export type CampaignRuntimeReviewQueueActions = {
  disabled: boolean
  onOpenEditRuntime: (entry: RuntimeWorldEntryDmView) => void
  onOpenEditOverride: (overlay: CampaignAdventureEntryOverlayView) => void
}

export type CampaignRuntimeReviewQueueProps = {
  items: ReviewQueueItem[]
  actions: CampaignRuntimeReviewQueueActions | null
  copy: CampaignRuntimeCopy
}

export function CampaignRuntimeReviewQueue({
  items,
  actions,
  copy,
}: CampaignRuntimeReviewQueueProps) {
  return (
    <section className="runtime-review-queue">
      <div className="runtime-review-queue__header">
        <h2>{copy.reviewQueueHeading}</h2>
        <span className="runtime-review-queue__count">
          {copy.reviewQueueCountLabel}: {items.length}
        </span>
      </div>
      <p className="runtime-review-queue__hint">{copy.reviewQueueHint}</p>
      {items.length === 0 ? (
        <p className="runtime-review-queue__empty">{copy.reviewQueueEmpty}</p>
      ) : (
        <ul className="runtime-review-queue__list">
          {items.map((item) => {
            if (item.type === 'runtime') {
              const displayTitle = item.entry.title || item.entry.id
              return (
                <li key={`runtime-${item.entry.id}`} className="runtime-review-queue__item">
                  <div className="runtime-review-queue__item-info">
                    <span className="runtime-entry__badge">{copy.needsReviewBadge}</span>
                    <span className="adventure-entry__kind">
                      {entryKindLabel(item.entry.kind, copy)}
                    </span>
                    <span className="runtime-review-queue__source-type">
                      {copy.reviewSourceTypeRuntime}
                    </span>
                    <strong className="runtime-review-queue__title">{displayTitle}</strong>
                  </div>
                  {actions ? (
                    <button
                      className="button secondary"
                      type="button"
                      disabled={actions.disabled}
                      onClick={() => actions.onOpenEditRuntime(item.entry)}
                    >
                      {copy.reviewButton}
                    </button>
                  ) : null}
                </li>
              )
            }
            const displayTitle = item.overlay.title || item.overlay.id
            return (
              <li key={`override-${item.overlay.id}`} className="runtime-review-queue__item">
                <div className="runtime-review-queue__item-info">
                  <span className="runtime-entry__badge">{copy.needsReviewBadge}</span>
                  <span className="adventure-entry__kind">
                    {adventureEntryKindLabel(item.overlay.kind, copy)}
                  </span>
                  <span className="runtime-review-queue__source-type">
                    {copy.reviewSourceTypeOverride} ({item.adventureName})
                  </span>
                  <strong className="runtime-review-queue__title">{displayTitle}</strong>
                </div>
                {actions ? (
                  <button
                    className="button secondary"
                    type="button"
                    disabled={actions.disabled}
                    onClick={() => actions.onOpenEditOverride(item.overlay)}
                  >
                    {copy.reviewButton}
                  </button>
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
