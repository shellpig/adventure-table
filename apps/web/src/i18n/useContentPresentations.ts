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
const LEADING_RULE_PREFIX_RE = /^(\d+\s*×\s*)/
const TRAILING_RULE_SUFFIX_RE = /(\s(?:[+−-]\d+|×\d+))$/

function compactSourceLabel(source: string): string {
  const trimmed = source.trim()
  if (/^System Reference Document 5\.1$/i.test(trimmed)) return 'SRD 5.1'
  if (/^Player['’]?s Handbook(?:\s*\(?(?:2014)\)?)?$/i.test(trimmed)) return 'PHB 2014'
  if (/^Sword Coast Adventurer['’]?s Guide$/i.test(trimmed)) return 'SCAG'
  if (/^Ghosts of Saltmarsh$/i.test(trimmed)) return 'GoS'
  return trimmed
}

/**
 * Replace only the canonical primary name while retaining mechanics-sensitive
 * count/bonus notation and source disambiguation.
 *
 * Examples:
 * - `STR +2` -> `力量 +2`
 * - `2 × Javelin · System Reference Document 5.1`
 *   -> `2 × 標槍 · SRD 5.1`
 * - `Fire Bolt · System Reference Document 5.1`
 *   -> `火焰箭 · SRD 5.1`
 *
 * Source names are compacted to the locale-neutral abbreviations explicitly
 * allowed by the M02 pure-language contract, so zh-TW does not reintroduce a
 * long English source label merely for duplicate disambiguation.
 */
export function localizedContentLabel(localizedName: string, fallback: string): string {
  const separatorIndex = fallback.indexOf(SOURCE_SEPARATOR)
  const fallbackPrimary = separatorIndex >= 0 ? fallback.slice(0, separatorIndex) : fallback
  const secondary = separatorIndex >= 0 ? fallback.slice(separatorIndex + SOURCE_SEPARATOR.length) : ''

  const prefix = fallbackPrimary.match(LEADING_RULE_PREFIX_RE)?.[1] ?? ''
  const withoutPrefix = prefix ? fallbackPrimary.slice(prefix.length) : fallbackPrimary
  const suffix = withoutPrefix.match(TRAILING_RULE_SUFFIX_RE)?.[1] ?? ''
  const needsPrefix = prefix && !localizedName.trim().startsWith(prefix.trim())
  const needsSuffix = suffix && !localizedName.trim().endsWith(suffix.trim())
  const primary = `${needsPrefix ? prefix : ''}${localizedName}${needsSuffix ? suffix : ''}`

  return secondary
    ? `${primary}${SOURCE_SEPARATOR}${compactSourceLabel(secondary)}`
    : primary
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
