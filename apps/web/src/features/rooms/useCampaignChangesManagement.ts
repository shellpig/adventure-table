import React, { useState } from 'react'

import type { RoomCharacterSummary } from '../../api/campaigns'
import {
  createOverride,
  createRuntimeEntry,
  updateOverride,
  updateRuntimeContext,
  updateRuntimeEntry,
  type CampaignAdventureEntryOverlayView,
  type CampaignRuntimeContext,
  type RuntimeWorldEntryDmView,
} from '../../api/campaignRuntime'
import type { CampaignRuntimeCopy } from './campaignRuntimeCopy'
import {
  buildCreateEntryRequest,
  buildUpdateEntryRequest,
  createInitialEntryFormState,
  entryToFormState,
  executeRuntimeMutation,
  generateRuntimeIdempotencyKey,
  handleArchiveRuntimeEntry,
  type RuntimeEntryFormState,
} from './campaignRuntimeForm'
import {
  buildCreateOverrideRequest,
  buildUpdateContextRequest,
  buildUpdateOverrideRequest,
  contextToFormState,
  handleClearContext,
  handleClearOverride,
  overlayToOverrideFormState,
  type ContextFormState,
  type OverrideFormState,
} from './campaignRuntimeOverrideForm'

export type CampaignChangesManagement = {
  characters: RoomCharacterSummary[]
  formState: RuntimeEntryFormState | null
  pending: boolean
  formError: string | null
  mutationError: string | null
  committedWarning: string | null
  onOpenCreate: () => void
  onOpenEdit: (entry: RuntimeWorldEntryDmView) => void
  onCancelForm: () => void
  onChangeForm: (updater: (prev: RuntimeEntryFormState) => RuntimeEntryFormState) => void
  onSubmitForm: (e: React.FormEvent) => void
  onArchiveEntry: (entry: RuntimeWorldEntryDmView) => void

  overrideFormState: OverrideFormState | null
  overrideFormError: string | null
  onOpenCreateOverride: (overlay: CampaignAdventureEntryOverlayView) => void
  onOpenEditOverride: (overlay: CampaignAdventureEntryOverlayView) => void
  onCancelOverrideForm: () => void
  onChangeOverrideForm: (updater: (prev: OverrideFormState) => OverrideFormState) => void
  onSubmitOverrideForm: (e: React.FormEvent) => void
  onClearOverride: (overlay: CampaignAdventureEntryOverlayView) => void

  contextFormState: ContextFormState | null
  contextFormError: string | null
  onOpenEditContext: () => void
  onCancelEditContext: () => void
  onChangeContextForm: (updater: (prev: ContextFormState) => ContextFormState) => void
  onSubmitContextForm: (e: React.FormEvent) => void
  onClearContext: () => void
}

export type UseCampaignChangesManagementOptions = {
  roomId: string
  campaignId: string
  token: string
  copy: CampaignRuntimeCopy
  context: CampaignRuntimeContext | null
  characters: RoomCharacterSummary[]
  onReload: () => Promise<void>
}

export function useCampaignChangesManagement({
  roomId,
  campaignId,
  token,
  copy,
  context,
  characters,
  onReload,
}: UseCampaignChangesManagementOptions): CampaignChangesManagement {
  const [formState, setFormState] = useState<RuntimeEntryFormState | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const [overrideFormState, setOverrideFormState] = useState<OverrideFormState | null>(null)
  const [overrideFormError, setOverrideFormError] = useState<string | null>(null)

  const [contextFormState, setContextFormState] = useState<ContextFormState | null>(null)
  const [contextFormError, setContextFormError] = useState<string | null>(null)

  const [pending, setPending] = useState(false)
  const [mutationError, setMutationError] = useState<string | null>(null)
  const [committedWarning, setCommittedWarning] = useState<string | null>(null)

  // Runtime Entry handlers
  const handleOpenCreate = () => {
    setFormState(createInitialEntryFormState('scene'))
    setOverrideFormState(null)
    setContextFormState(null)
    setFormError(null)
    setMutationError(null)
    setCommittedWarning(null)
  }

  const handleOpenEdit = (entry: RuntimeWorldEntryDmView) => {
    const nextState = entryToFormState(entry)
    if (!nextState) return
    setFormState(nextState)
    setOverrideFormState(null)
    setContextFormState(null)
    setFormError(null)
    setMutationError(null)
    setCommittedWarning(null)
  }

  const handleCancelForm = () => {
    setFormState(null)
    setFormError(null)
  }

  const handleChangeForm = (
    updater: (prev: RuntimeEntryFormState) => RuntimeEntryFormState,
  ) => {
    setFormState((prev) => (prev ? updater(prev) : prev))
  }

  const handleSubmitForm = (e: React.FormEvent) => {
    e.preventDefault()
    if (!formState) return

    if (formState.mode === 'create') {
      const idempotencyKey = generateRuntimeIdempotencyKey('runtime-entry-create')
      const built = buildCreateEntryRequest(formState, idempotencyKey)
      if (!built.ok) {
        setFormError(copy[built.errorKey])
        return
      }
      setPending(true)
      setFormError(null)
      setMutationError(null)
      setCommittedWarning(null)
      void executeRuntimeMutation({
        action: () => createRuntimeEntry(roomId, campaignId, token, built.value),
        onReload,
        onSuccess: () => {
          setFormState(null)
          setPending(false)
        },
        onError: (err) => {
          setFormError(err)
          setPending(false)
        },
        onCommittedReloadError: () => {
          setFormState(null)
          setPending(false)
          setFormError(null)
          setMutationError(null)
          setCommittedWarning(copy.committedReloadWarning)
        },
        copy,
      })
    } else {
      const idempotencyKey = generateRuntimeIdempotencyKey('runtime-entry-update')
      const built = buildUpdateEntryRequest(formState, idempotencyKey)
      if (!built.ok) {
        setFormError(copy[built.errorKey])
        return
      }
      setPending(true)
      setFormError(null)
      setMutationError(null)
      setCommittedWarning(null)
      void executeRuntimeMutation({
        action: () =>
          updateRuntimeEntry(roomId, campaignId, formState.entryId, token, built.value),
        onReload,
        onSuccess: () => {
          setFormState(null)
          setPending(false)
        },
        onError: (err) => {
          setFormError(err)
          setPending(false)
        },
        onCommittedReloadError: () => {
          setFormState(null)
          setPending(false)
          setFormError(null)
          setMutationError(null)
          setCommittedWarning(copy.committedReloadWarning)
        },
        copy,
      })
    }
  }

  const handleArchive = (entry: RuntimeWorldEntryDmView) => {
    const idempotencyKey = generateRuntimeIdempotencyKey('runtime-entry-archive')
    void handleArchiveRuntimeEntry({
      roomId,
      campaignId,
      entryId: entry.id,
      revision: entry.revision,
      token,
      idempotencyKey,
      onStart: () => {
        setPending(true)
        setMutationError(null)
        setCommittedWarning(null)
      },
      onCancel: () => {
        setPending(false)
      },
      onReload,
      onSuccess: () => {
        setPending(false)
      },
      onError: (err) => {
        setMutationError(err)
        setPending(false)
      },
      onCommittedReloadError: () => {
        setPending(false)
        setMutationError(null)
        setCommittedWarning(copy.committedReloadWarning)
      },
      copy,
    })
  }

  // Override handlers
  const handleOpenCreateOverride = (overlay: CampaignAdventureEntryOverlayView) => {
    setOverrideFormState(overlayToOverrideFormState(overlay))
    setFormState(null)
    setContextFormState(null)
    setOverrideFormError(null)
    setMutationError(null)
    setCommittedWarning(null)
  }

  const handleOpenEditOverride = (overlay: CampaignAdventureEntryOverlayView) => {
    setOverrideFormState(overlayToOverrideFormState(overlay))
    setFormState(null)
    setContextFormState(null)
    setOverrideFormError(null)
    setMutationError(null)
    setCommittedWarning(null)
  }

  const handleCancelOverrideForm = () => {
    setOverrideFormState(null)
    setOverrideFormError(null)
  }

  const handleChangeOverrideForm = (
    updater: (prev: OverrideFormState) => OverrideFormState,
  ) => {
    setOverrideFormState((prev) => (prev ? updater(prev) : prev))
  }

  const handleSubmitOverrideForm = (e: React.FormEvent) => {
    e.preventDefault()
    if (!overrideFormState) return

    if (overrideFormState.mode === 'create') {
      const idempotencyKey = generateRuntimeIdempotencyKey('runtime-override-create')
      const built = buildCreateOverrideRequest(overrideFormState, idempotencyKey)
      if (!built.ok) {
        setOverrideFormError(copy[built.errorKey])
        return
      }
      setPending(true)
      setOverrideFormError(null)
      setMutationError(null)
      setCommittedWarning(null)
      void executeRuntimeMutation({
        action: () => createOverride(roomId, campaignId, token, built.value),
        onReload,
        onSuccess: () => {
          setOverrideFormState(null)
          setPending(false)
        },
        onConflict: (err) => {
          setOverrideFormState(null)
          setOverrideFormError(null)
          setMutationError(err)
          setPending(false)
        },
        onError: (err) => {
          setOverrideFormError(err)
          setPending(false)
        },
        onCommittedReloadError: () => {
          setOverrideFormState(null)
          setPending(false)
          setOverrideFormError(null)
          setMutationError(null)
          setCommittedWarning(copy.committedReloadWarning)
        },
        copy,
      })
    } else {
      const idempotencyKey = generateRuntimeIdempotencyKey('runtime-override-update')
      const built = buildUpdateOverrideRequest(overrideFormState, idempotencyKey)
      if (!built.ok) {
        setOverrideFormError(copy[built.errorKey])
        return
      }
      setPending(true)
      setOverrideFormError(null)
      setMutationError(null)
      setCommittedWarning(null)
      void executeRuntimeMutation({
        action: () =>
          updateOverride(
            roomId,
            campaignId,
            overrideFormState.adventureEntryId,
            token,
            built.value,
          ),
        onReload,
        onSuccess: () => {
          setOverrideFormState(null)
          setPending(false)
        },
        onConflict: (err) => {
          setOverrideFormState(null)
          setOverrideFormError(null)
          setMutationError(err)
          setPending(false)
        },
        onError: (err) => {
          setOverrideFormError(err)
          setPending(false)
        },
        onCommittedReloadError: () => {
          setOverrideFormState(null)
          setPending(false)
          setOverrideFormError(null)
          setMutationError(null)
          setCommittedWarning(copy.committedReloadWarning)
        },
        copy,
      })
    }
  }

  const handleClearOverrideAction = (overlay: CampaignAdventureEntryOverlayView) => {
    if (!overlay.override) return
    const idempotencyKey = generateRuntimeIdempotencyKey('runtime-override-clear')
    void handleClearOverride({
      roomId,
      campaignId,
      adventureEntryId: overlay.id,
      expectedOverrideId: overlay.override.id,
      expectedRevision: overlay.override.revision,
      token,
      idempotencyKey,
      onStart: () => {
        setPending(true)
        setMutationError(null)
        setCommittedWarning(null)
      },
      onCancel: () => {
        setPending(false)
      },
      onReload,
      onSuccess: () => {
        setPending(false)
      },
      onError: (err) => {
        setMutationError(err)
        setPending(false)
      },
      onCommittedReloadError: () => {
        setPending(false)
        setMutationError(null)
        setCommittedWarning(copy.committedReloadWarning)
      },
      copy,
    })
  }

  // Context handlers
  const handleOpenEditContext = () => {
    setContextFormState(contextToFormState(context))
    setFormState(null)
    setOverrideFormState(null)
    setContextFormError(null)
    setMutationError(null)
    setCommittedWarning(null)
  }

  const handleCancelEditContext = () => {
    setContextFormState(null)
    setContextFormError(null)
  }

  const handleChangeContextForm = (
    updater: (prev: ContextFormState) => ContextFormState,
  ) => {
    setContextFormState((prev) => (prev ? updater(prev) : prev))
  }

  const handleSubmitContextForm = (e: React.FormEvent) => {
    e.preventDefault()
    if (!contextFormState) return

    const idempotencyKey = generateRuntimeIdempotencyKey('runtime-context-update')
    const request = buildUpdateContextRequest(contextFormState, idempotencyKey)

    setPending(true)
    setContextFormError(null)
    setMutationError(null)
    setCommittedWarning(null)

    void executeRuntimeMutation({
      action: () => updateRuntimeContext(roomId, campaignId, token, request),
      onReload,
      onSuccess: () => {
        setContextFormState(null)
        setPending(false)
      },
      onConflict: (err) => {
        setContextFormState(null)
        setContextFormError(null)
        setMutationError(err)
        setPending(false)
      },
      onError: (err) => {
        setContextFormError(err)
        setPending(false)
      },
      onCommittedReloadError: () => {
        setContextFormState(null)
        setPending(false)
        setContextFormError(null)
        setMutationError(null)
        setCommittedWarning(copy.committedReloadWarning)
      },
      copy,
    })
  }

  const handleClearContextAction = () => {
    const revision = context?.revision ?? 0
    const idempotencyKey = generateRuntimeIdempotencyKey('runtime-context-clear')
    void handleClearContext({
      roomId,
      campaignId,
      expectedRevision: revision,
      token,
      idempotencyKey,
      onStart: () => {
        setPending(true)
        setMutationError(null)
        setCommittedWarning(null)
      },
      onCancel: () => {
        setPending(false)
      },
      onReload,
      onSuccess: () => {
        setPending(false)
        setContextFormState(null)
      },
      onError: (err) => {
        setMutationError(err)
        setPending(false)
      },
      onCommittedReloadError: () => {
        setPending(false)
        setContextFormState(null)
        setMutationError(null)
        setCommittedWarning(copy.committedReloadWarning)
      },
      copy,
    })
  }

  return {
    characters,
    formState,
    pending,
    formError,
    mutationError,
    committedWarning,
    onOpenCreate: handleOpenCreate,
    onOpenEdit: handleOpenEdit,
    onCancelForm: handleCancelForm,
    onChangeForm: handleChangeForm,
    onSubmitForm: handleSubmitForm,
    onArchiveEntry: handleArchive,

    overrideFormState,
    overrideFormError,
    onOpenCreateOverride: handleOpenCreateOverride,
    onOpenEditOverride: handleOpenEditOverride,
    onCancelOverrideForm: handleCancelOverrideForm,
    onChangeOverrideForm: handleChangeOverrideForm,
    onSubmitOverrideForm: handleSubmitOverrideForm,
    onClearOverride: handleClearOverrideAction,

    contextFormState,
    contextFormError,
    onOpenEditContext: handleOpenEditContext,
    onCancelEditContext: handleCancelEditContext,
    onChangeContextForm: handleChangeContextForm,
    onSubmitContextForm: handleSubmitContextForm,
    onClearContext: handleClearContextAction,
  }
}
