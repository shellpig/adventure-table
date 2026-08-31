import type { Locale } from '../i18n/locale'
import { createLocalizedRequestError } from '../i18n/systemMessages'

export type LocalizedPresentationField = {
  field_path: string
  value: unknown
  source: string
  fallback_used: boolean
  missing_required: boolean
}

export type ContentPresentation = {
  key: string
  locale: Locale
  fields: LocalizedPresentationField[]
  roleplay_suggestions: {
    suggestion_id: string
    field: string
    position: number
    text: string
    missing_required: boolean
  }[]
  optional_roleplay_tables: {
    table_id: string
    label: string
    suggestions: {
      suggestion_id: string
      field: string
      position: number
      text: string
      missing_required: boolean
    }[]
  }[]
}

type ContentPresentationBatch = {
  locale: Locale
  presentations: ContentPresentation[]
}

export async function getContentPresentations(
  references: string[],
  locale: Locale,
  fields: string[] = ['name'],
): Promise<ContentPresentationBatch> {
  const response = await fetch(
    `/api/rules/presentation/batch?locale=${encodeURIComponent(locale)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ references, fields }),
    },
  )
  if (!response.ok) {
    let code: string | undefined
    let message = `Presentation request failed (${response.status})`
    try {
      const payload = (await response.json()) as { error?: { code?: string; message?: string } }
      code = payload.error?.code
      message = payload.error?.message ?? message
    } catch {
      // Keep the HTTP fallback when the response is not JSON.
    }
    throw createLocalizedRequestError(code, response.status, message)
  }
  return (await response.json()) as ContentPresentationBatch
}

export function presentationField(
  presentation: ContentPresentation | undefined,
  fieldPath: string,
): LocalizedPresentationField | undefined {
  return presentation?.fields.find((field) => field.field_path === fieldPath)
}
