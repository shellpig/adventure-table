import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import {
  getContentPresentations,
  presentationField,
  type ContentPresentation,
} from '../api/contentPresentation'
import { useLocale } from './LocaleProvider'

export type ContentNameResolver = (reference: string | null | undefined, fallback?: string) => string

const SOURCE_SEPARATOR = ' · '
const TRAILING_RULE_SUFFIX_RE = /(\s(?:[+−-]\d+|×\d+))$/

/**
 * Replace only the canonical primary name while retaining presentation context
 * that is not part of the localized entity name itself.
 *
 * Examples:
 * - `STR +2` -> `力量 +2`
 * - `Fire Bolt · System Reference Document 5.1`
 *   -> `火焰箭 · System Reference Document 5.1`
 *
 * This keeps counted-reference mechanics and source disambiguation visible
 * instead of accidentally dropping them when a localized name is resolved.
 */
export function localizedContentLabel(localizedName: string, fallback: string): string {
  const separatorIndex = fallback.indexOf(SOURCE_SEPARATOR)
  const fallbackPrimary = separatorIndex >= 0 ? fallback.slice(0, separatorIndex) : fallback
  const secondary = separatorIndex >= 0 ? fallback.slice(separatorIndex + SOURCE_SEPARATOR.length) : ''
  const suffix = fallbackPrimary.match(TRAILING_RULE_SUFFIX_RE)?.[1] ?? ''
  const needsSuffix = suffix && !localizedName.trim().endsWith(suffix.trim())
  const primary = `${localizedName}${needsSuffix ? suffix : ''}`
  return secondary ? `${primary}${SOURCE_SEPARATOR}${secondary}` : primary
}

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
    if (typeof field?.value === 'string' && field.value.trim()) {
      return localizedContentLabel(field.value, fallback)
    }
    return fallback || reference
  }

  return {
    locale,
    presentations,
    nameFor,
    isLoading: query.isLoading,
    error: query.error,
  }
}
