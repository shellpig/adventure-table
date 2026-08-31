import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'

import {
  getContentPresentations,
  presentationField,
  type ContentPresentation,
} from '../api/contentPresentation'
import { useLocale } from './LocaleProvider'

export type ContentNameResolver = (reference: string | null | undefined, fallback?: string) => string
/**
 * Resolve a field other than `name` on a content entry. Grants that live as an
 * inline field of their source entry - a background's own feature, say - have
 * no StableKey of their own, so their presentation identity is the source
 * entry plus the field path holding the name.
 */
export type ContentFieldResolver = (
  reference: string | null | undefined,
  fieldPath: string | null | undefined,
  fallback?: string,
) => string

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

/**
 * Split references into one request per distinct field set.
 *
 * A field path only exists on the kinds that declare it, and the batch
 * endpoint rejects the whole request when any reference lacks a requested
 * field. Asking every reference for `data.feature.name` would therefore lose
 * the names of every grant, not just the one that needed the extra field.
 */
export function groupPresentationRequests(
  references: readonly string[],
  extraFields: Readonly<Record<string, string[]>>,
): { fields: string[]; references: string[] }[] {
  const bySignature = new Map<string, { fields: string[]; references: string[] }>()
  for (const reference of Array.from(new Set(references.filter(Boolean))).sort()) {
    const fields = Array.from(new Set(['name', ...(extraFields[reference] ?? [])])).sort()
    const signature = fields.join(' ')
    const group = bySignature.get(signature)
    if (group) {
      group.references.push(reference)
    } else {
      bySignature.set(signature, { fields, references: [reference] })
    }
  }
  return Array.from(bySignature.values())
}

export function useContentPresentations(
  references: string[],
  extraFields: Record<string, string[]> = {},
) {
  const { locale } = useLocale()
  const requestKey = JSON.stringify(groupPresentationRequests(references, extraFields))
  const requests = useMemo(
    () => JSON.parse(requestKey) as { fields: string[]; references: string[] }[],
    [requestKey],
  )
  const results = useQueries({
    queries: requests.map((request) => ({
      queryKey: ['content-presentations', locale, request.references, request.fields],
      queryFn: () => getContentPresentations(request.references, locale, request.fields),
      enabled: request.references.length > 0,
    })),
  })
  // Built per render rather than memoised: the number of groups varies with the
  // reference set, so there is no dependency array of stable length to key on,
  // and a wrong key here would serve stale names after a locale switch.
  const presentations = new Map<string, ContentPresentation>(
    results.flatMap((result) =>
      (result.data?.presentations ?? []).map(
        (presentation) => [presentation.key, presentation] as const,
      ),
    ),
  )
  const fieldFor: ContentFieldResolver = (reference, fieldPath, fallback = '') => {
    if (!reference || !fieldPath) return fallback
    const field = presentationField(presentations.get(reference), fieldPath)
    if (typeof field?.value === 'string' && field.value.trim()) {
      return localizedContentLabel(field.value, fallback)
    }
    return fallback || reference
  }

  const nameFor: ContentNameResolver = (reference, fallback = '') =>
    fieldFor(reference, 'name', fallback)

  return {
    locale,
    presentations,
    nameFor,
    fieldFor,
    isLoading: results.some((result) => result.isLoading),
    error: results.find((result) => result.error)?.error ?? null,
  }
}
