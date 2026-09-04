import { createLocalizedRequestError } from '../../i18n/systemMessages'

type APIErrorPayload = {
  error?: {
    code?: string
    message?: string
  }
}

function filenameFromDisposition(value: string | null): string {
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

export async function downloadCharacterExport(characterId: string): Promise<void> {
  const response = await fetch(`/api/characters/${encodeURIComponent(characterId)}/export`)
  if (!response.ok) {
    let code: string | undefined
    let message = `Request failed (${response.status})`
    try {
      const payload = (await response.json()) as APIErrorPayload
      code = payload.error?.code
      message = payload.error?.message ?? message
    } catch {
      // Keep the HTTP fallback when the body is not JSON.
    }
    throw createLocalizedRequestError(code, response.status, message)
  }

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
