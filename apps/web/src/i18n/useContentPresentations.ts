import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'

import {
  getContentPresentations,
  presentationField,
  type ContentPresentation,
} from '../api/contentPresentation'
import { useLocale } from './LocaleProvider'
import { SUPPORTED_LOCALES, type Locale } from './locale'

export type ContentNameResolver = (reference: string | null | undefined, fallback?: string) => string
export type ContentSearchAliasResolver = (
  reference: string | null | undefined,
  fallback?: string,
) => string[]
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
    queries: SUPPORTED_LOCALES.flatMap((requestLocale) =>
      requests.map((request) => ({
        queryKey: ['content-presentations', requestLocale, request.references, request.fields],
        queryFn: () => getContentPresentations(request.references, requestLocale, request.fields),
        enabled: request.references.length > 0,
        meta: { locale: requestLocale },
      })),
    ),
  })

  const presentationsByLocale = new Map<Locale, Map<string, ContentPresentation>>()
  for (const requestLocale of SUPPORTED_LOCALES) {
    presentationsByLocale.set(requestLocale, new Map())
  }
  results.forEach((result, index) => {
    const requestLocale = SUPPORTED_LOCALES[Math.floor(index / Math.max(requests.length, 1))]
    if (!requestLocale) return
    const target = presentationsByLocale.get(requestLocale)
    for (const presentation of result.data?.presentations ?? []) {
      target?.set(presentation.key, presentation)
    }
  })

  const presentations = presentationsByLocale.get(locale) ?? new Map<string, ContentPresentation>()
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

  const searchAliasesFor: ContentSearchAliasResolver = (reference, fallback = '') => {
    if (!reference) return fallback ? [fallback] : []
    const aliases = new Set<string>()
    if (fallback.trim()) aliases.add(fallback.trim())
    for (const requestLocale of SUPPORTED_LOCALES) {
      const field = presentationField(
        presentationsByLocale.get(requestLocale)?.get(reference),
        'name',
      )
      if (typeof field?.value === 'string' && field.value.trim()) aliases.add(field.value.trim())
    }
    aliases.delete(nameFor(reference, fallback))
    return [...aliases]
  }

  return {
    locale,
    presentations,
    presentationsByLocale,
    nameFor,
    fieldFor,
    searchAliasesFor,
    isLoading: results.some((result) => result.isLoading),
    error: results.find((result) => result.error)?.error ?? null,
  }
}
