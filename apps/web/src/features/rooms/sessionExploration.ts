import type {
  ExplorationInputKind,
  ExplorationInputRequest,
  StageState,
  TableEvent,
} from '../../api/sessions'

export type ComposerParseResult =
  | { type: 'request'; request: ExplorationInputRequest }
  | { type: 'blocked_check' }
  | { type: 'invalid'; reason: 'empty' | 'missing_subject' }

const slashPattern = /^\/(action|search|whisper|ooc|check)(?:\s+|$)/i

function needsSubject(kind: ExplorationInputKind): boolean {
  return kind === 'dialogue' || kind === 'action'
}

export function parseExplorationComposer(
  raw: string,
  defaultKind: ExplorationInputKind,
  subjectSeatId: string | null,
): ComposerParseResult {
  const trimmed = raw.trim()
  if (!trimmed) return { type: 'invalid', reason: 'empty' }

  const match = trimmed.match(slashPattern)
  let kind = defaultKind
  let sourceCommand: 'search' | null = null
  let text = trimmed
  if (match) {
    const command = match[1].toLowerCase()
    text = trimmed.slice(match[0].length).trim()
    if (command === 'check') return { type: 'blocked_check' }
    if (!text) return { type: 'invalid', reason: 'empty' }
    if (command === 'action' || command === 'search') {
      kind = 'action'
      sourceCommand = command === 'search' ? 'search' : null
    } else if (command === 'whisper') {
      kind = 'whisper_dm'
    } else if (command === 'ooc') {
      kind = 'ooc'
    }
  }

  if (needsSubject(kind) && !subjectSeatId) {
    return { type: 'invalid', reason: 'missing_subject' }
  }

  return {
    type: 'request',
    request: {
      kind,
      text,
      subject_seat_id: needsSubject(kind) ? subjectSeatId : null,
      source_command: sourceCommand,
    },
  }
}

export function applyStageEvent(stage: StageState | null, event: TableEvent): StageState | null {
  if (event.kind !== 'stage.updated') return stage
  const revision = event.payload.stage_revision
  if (typeof revision !== 'number' || revision < 0) return stage
  if (stage && revision < stage.revision) return stage

  const imageId = event.payload.image_id
  const mediaType = event.payload.image_media_type
  const filename = event.payload.image_filename
  const text = event.payload.text
  return {
    session_id: event.session_id,
    revision,
    text: typeof text === 'string' ? text : null,
    image_id: typeof imageId === 'string' ? imageId : null,
    image_media_type: typeof mediaType === 'string' ? mediaType : null,
    image_filename: typeof filename === 'string' ? filename : null,
  }
}

export function applyStageEvents(stage: StageState | null, events: TableEvent[]): StageState | null {
  return events.reduce<StageState | null>((current, event) => applyStageEvent(current, event), stage)
}

export function isExplorationEvent(event: TableEvent): boolean {
  return event.kind.startsWith('exploration.')
}

export function explorationEventText(event: TableEvent): string {
  return typeof event.payload.text === 'string' ? event.payload.text : ''
}
