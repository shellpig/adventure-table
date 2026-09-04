import { createLocalizedCharacterImportRequestError } from '../../i18n/characterImportMessages'

type APIErrorPayload = {
  error?: {
    code?: string
    message?: string
    params?: Record<string, unknown>
  }
}

export type CharacterImportLandingMode = 'character' | 'draft' | 'draft_with_history_loss'

export type CharacterImportUnresolvedRef = {
  stable_key: string
  pack: string
  kind: string
  origin: 'build' | 'state'
  version_no?: number | null
}

export type CharacterImportResult = {
  dry_run: boolean
  committed: boolean
  landing_mode: CharacterImportLandingMode
  resolved_ref_count: number
  unresolved_ref_count: number
  unresolved_refs: CharacterImportUnresolvedRef[]
  duplicate_hint?: {
    count: number
    latest_imported_at?: string | null
  } | null
  character_preview: {
    name: string
    level: number
    class_summary: string
  }
  character_id?: string | null
  draft_id?: string | null
  character_path?: string | null
  draft_path?: string | null
}

/** Parse RFC 6266 / RFC 5987 `Content-Disposition`, preferring the UTF-8 form. */
export function filenameFromDisposition(value: string | null): string {
  if (!value) return 'character.json'
  const encoded = value.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  if (encoded) {
    try {
      return decodeURIComponent(encoded)
    } catch {
      return encoded
    }
  }
  return value.match(/filename="?([^";]+)"?/i)?.[1] ?? 'character.json'
}

async function parseRequestError(response: Response): Promise<Error> {
  let code: string | undefined
  let message = `Request failed (${response.status})`
  try {
    const payload = (await response.json()) as APIErrorPayload
    code = payload.error?.code
    message = payload.error?.message ?? message
  } catch {
    // Keep the HTTP fallback when the body is not JSON.
  }
  return createLocalizedCharacterImportRequestError(code, response.status, message)
}

export async function downloadCharacterExport(characterId: string): Promise<void> {
  const response = await fetch(`/api/characters/${encodeURIComponent(characterId)}/export`)
  if (!response.ok) throw await parseRequestError(response)

  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filenameFromDisposition(response.headers.get('Content-Disposition'))
  anchor.style.display = 'none'
  document.body.append(anchor)
  try {
    anchor.click()
  } finally {
    anchor.remove()
    URL.revokeObjectURL(objectUrl)
  }
}

async function characterImportRequest(
  documentText: string,
  dryRun: boolean,
): Promise<CharacterImportResult> {
  const response = await fetch(`/api/characters/import${dryRun ? '?dry_run=true' : ''}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: documentText,
  })
  if (!response.ok) throw await parseRequestError(response)
  return (await response.json()) as CharacterImportResult
}

export function previewCharacterImport(documentText: string): Promise<CharacterImportResult> {
  return characterImportRequest(documentText, true)
}

export function commitCharacterImport(documentText: string): Promise<CharacterImportResult> {
  return characterImportRequest(documentText, false)
}
