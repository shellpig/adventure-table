import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import {
  getContentPresentations,
  presentationField,
  type ContentPresentation,
} from '../api/contentPresentation'
import { useLocale } from './LocaleProvider'

export type ContentNameResolver = (reference: string | null | undefined, fallback?: string) => string

export function useContentPresentations(references: string[]) {
  const { locale } = useLocale()
  const referenceKey = references.filter(Boolean).sort().join('\u0000')
  const stableReferences = useMemo(
    () => Array.from(new Set(referenceKey ? referenceKey.split('\u0000') : [])),
    [referenceKey],
  )
  const query = useQuery({
    queryKey: ['content-presentations', locale, stableReferences],
    queryFn: () => getContentPresentations(stableReferences, locale),
    enabled: stableReferences.length > 0,
  })
  const presentations = useMemo(
    () =>
      new Map<string, ContentPresentation>(
        (query.data?.presentations ?? []).map((presentation) => [presentation.key, presentation]),
      ),
    [query.data],
  )
  const nameFor: ContentNameResolver = (reference, fallback = '') => {
    if (!reference) return fallback
    const field = presentationField(presentations.get(reference), 'name')
    return typeof field?.value === 'string' && field.value.trim() ? field.value : fallback || reference
  }

  return {
    locale,
    presentations,
    nameFor,
    isLoading: query.isLoading,
    error: query.error,
  }
}
