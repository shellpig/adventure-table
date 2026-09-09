import { createContext } from 'react'

import type { PendingActionView, RollRequestView } from '../../api/p3c'
import type { SessionResume } from '../../api/sessions'

export type SessionP3CResumeTruth = {
  rollRequests: RollRequestView[]
  pendingActions: PendingActionView[]
}

export const EMPTY_SESSION_P3C_RESUME: SessionP3CResumeTruth = {
  rollRequests: [],
  pendingActions: [],
}

export function p3cResumeTruthForSession(
  resume: SessionResume,
  sessionId: string,
): SessionP3CResumeTruth {
  if (resume.active_session?.id !== sessionId) return EMPTY_SESSION_P3C_RESUME
  return {
    rollRequests: resume.roll_requests ?? [],
    pendingActions: resume.pending_actions ?? [],
  }
}

export const SessionP3CResumeContext = createContext<SessionP3CResumeTruth>(
  EMPTY_SESSION_P3C_RESUME,
)
