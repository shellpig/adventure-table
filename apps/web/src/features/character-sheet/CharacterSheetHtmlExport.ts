import type { CharacterSheetDTO } from '../../api/character'
import baseStyles from '../../styles.css?inline'
import type { Locale } from '../../i18n/locale'
import { characterSheetExportCopy } from '../../i18n/m01nCharacterSheetExportCopy'
import exportStyles from './characterSheetExport.css?inline'

export type CharacterSheetExportScope = 'build' | 'snapshot'
export type CharacterSheetExportTab = 'attributes' | 'spells' | 'inventory'
export type CharacterSheetTabRenderer = (tab: CharacterSheetExportTab) => string

export type CharacterSheetExportProjection = {
  scope: CharacterSheetExportScope
  currentHp: number | null
  temporaryHp: number | null
  conditionCount: number
  hitDice: Array<{ die: string; total: number; available: number | null }>
  spellSlots: Array<{ level: string; total: number; remaining: number | null }>
  resources: Array<{ key: string; total: number; remaining: number | null }>
  spellcasting: Array<{ sourceKey: string; limit: number | null; preparedCount: number | null }>
  preparedSpellEntryIds: string[] | null
  inventoryCount: number
}

export type CharacterSheetExportResult = {
  html: string
  filename: string
}

export type CharacterSheetIndexPair<T> = {
  key: string
  row: HTMLElement
  item: T
}

export function projectCharacterSheetForExport(
  sheet: CharacterSheetDTO,
  scope: CharacterSheetExportScope,
): CharacterSheetExportProjection {
  const snapshot = scope === 'snapshot'
  return {
    scope,
    currentHp: snapshot ? sheet.current_hp : null,
    temporaryHp: snapshot ? sheet.temporary_hp : null,
    conditionCount: snapshot ? sheet.conditions.length : 0,
    hitDice: sheet.hit_dice.map((entry) => ({
      die: entry.die,
      total: entry.total,
      available: snapshot ? entry.available : null,
    })),
    spellSlots: Object.entries(sheet.spell_slots)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([level, counter]) => ({
        level,
        total: counter.used + counter.remaining,
        remaining: snapshot ? counter.remaining : null,
      })),
    resources: Object.entries(sheet.resources).map(([key, counter]) => ({
      key,
      total: counter.used + counter.remaining,
      remaining: snapshot ? counter.remaining : null,
    })),
    spellcasting: sheet.spellcasting.map((source) => ({
      sourceKey: source.source_key,
      limit: source.prepared_limit ?? null,
      preparedCount: snapshot ? source.prepared_count : null,
    })),
    preparedSpellEntryIds: snapshot
      ? sheet.spells.filter((spell) => spell.prepared).map((spell) => spell.entry_id)
      : null,
    inventoryCount: snapshot ? sheet.inventory.length : 0,
  }
}

export function sanitizeFilenameSegment(value: string): string {
  const normalized = value
    .normalize('NFKC')
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, '-')
    .replace(/\s+/g, ' ')
    .replace(/[. ]+$/g, '')
    .trim()
  return normalized || 'character'
}

export function buildCharacterSheetExportFilename(
  sheet: Pick<CharacterSheetDTO, 'name' | 'version_no'>,
  scope: CharacterSheetExportScope,
): string {
  return `${sanitizeFilenameSegment(sheet.name)}-v${sheet.version_no}-${scope}.html`
}

export function formatConditionForExport(label: string, note?: string | null): string {
  const trimmedLabel = label.replace(/\s*×\s*$/, '').trim()
  const trimmedNote = note?.trim()
  return trimmedNote ? `${trimmedLabel} — ${trimmedNote}` : trimmedLabel
}

export function pairCharacterSheetIndexRows<T>(
  root: ParentNode,
  selector: string,
  items: readonly T[],
  keyFor: (item: T) => string,
): CharacterSheetIndexPair<T>[] {
  const itemByKey = new Map<string, T>()
  for (const item of items) {
    const key = keyFor(item).trim()
    if (!key) throw new Error(`Character Sheet export index item for ${selector} has an empty key`)
    if (itemByKey.has(key)) {
      throw new Error(`Character Sheet export index item for ${selector} has duplicate key: ${key}`)
    }
    itemByKey.set(key, item)
  }

  const seenRowKeys = new Set<string>()
  const pairs = Array.from(root.querySelectorAll<HTMLElement>(selector)).map((row) => {
    const key = row.dataset.sheetIndexKey?.trim()
    if (!key) {
      throw new Error(`Character Sheet export row for ${selector} is missing data-sheet-index-key`)
    }
    if (seenRowKeys.has(key)) {
      throw new Error(`Character Sheet export row for ${selector} has duplicate key: ${key}`)
    }
    seenRowKeys.add(key)

    const item = itemByKey.get(key)
    if (!item) {
      throw new Error(`Character Sheet export row for ${selector} has unknown key: ${key}`)
    }
    return { key, row, item }
  })

  for (const key of itemByKey.keys()) {
    if (!seenRowKeys.has(key)) {
      throw new Error(`Character Sheet export row for ${selector} is missing key: ${key}`)
    }
  }
  return pairs
}

export function buildCharacterSheetHtmlDocument({
  bodyMarkup,
  locale,
  title,
}: {
  bodyMarkup: string
  locale: Locale
  title: string
}): string {
  const html = `<!doctype html>\n<html lang="${escapeHtml(locale)}">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>${escapeHtml(title)}</title>\n<style>${baseStyles}\n${exportStyles}</style>\n</head>\n<body>${bodyMarkup}</body>\n</html>`
  assertSafeCharacterSheetHtml(html)
  return html
}

export function assertSafeCharacterSheetHtml(html: string): void {
  const forbidden: Array<[RegExp, string]> = [
    [/<script\b/i, 'script'],
    [/https?:\/\//i, 'external URL'],
    [/\bsrc\s*=/i, 'src attribute'],
    [/\bhref\s*=/i, 'href attribute'],
    [/\bfetch\s*\(/i, 'fetch call'],
    [/<button\b/i, 'button control'],
    [/<input\b/i, 'input control'],
    [/<select\b/i, 'select control'],
    [/<textarea\b/i, 'textarea control'],
    [/<form\b/i, 'form control'],
    [/<details\b/i, 'collapsible details'],
    [/role="tablist"/i, 'tab navigation'],
  ]
  const violation = forbidden.find(([pattern]) => pattern.test(html))
  if (violation) throw new Error(`Character Sheet HTML export is not self-contained/read-only: ${violation[1]}`)
}

export function createCharacterSheetHtmlExport({
  sheet,
  scope,
  locale,
  renderTab,
  now = new Date(),
}: {
  sheet: CharacterSheetDTO
  scope: CharacterSheetExportScope
  locale: Locale
  renderTab: CharacterSheetTabRenderer
  now?: Date
}): CharacterSheetExportResult {
  if (typeof document === 'undefined') {
    throw new Error('Character Sheet HTML export requires a browser document')
  }

  const copy = characterSheetExportCopy(locale)
  const projection = projectCharacterSheetForExport(sheet, scope)
  const attributesMain = parseRenderedMain(renderTab('attributes'))
  const shell = requiredElement<HTMLElement>(attributesMain, '.sheet-shell')
  const footer = requiredElement<HTMLElement>(shell, '.sheet-footer')

  const spellsMain = parseRenderedMain(renderTab('spells'))
  footer.before(requiredElement<HTMLElement>(spellsMain, '.sheet-content').cloneNode(true))

  if (scope === 'snapshot') {
    const inventoryMain = parseRenderedMain(renderTab('inventory'))
    footer.before(requiredElement<HTMLElement>(inventoryMain, '.sheet-content').cloneNode(true))
  }

  attributesMain.classList.add('export-character-page')
  attributesMain.querySelectorAll('.ambient').forEach((node) => node.remove())
  shell.querySelector('.sheet-tabs')?.remove()
  shell.querySelector('.builder-back')?.remove()
  shell.querySelector('.character-hero__actions')?.remove()
  shell.querySelector('.error-banner')?.remove()

  insertExportDocumentMeta(shell, sheet, scope, locale, now)
  preserveConditionLabels(shell, sheet)
  preserveInventoryQuantities(shell, copy.quantity)
  removeInteractiveChrome(shell)
  flattenRoleplayDetails(shell)

  if (scope === 'build') {
    applyBuildOnlyProjection(shell, sheet, projection, locale)
  }

  shell.querySelector('.sheet-footer strong')?.remove()

  // Final defense: an export should never ship a live control even if a future
  // sheet change introduces one outside the selectors above.
  shell.querySelectorAll('button,input,select,textarea,form').forEach((node) => node.remove())

  const title = `${sheet.name} — ${scope === 'build' ? copy.buildScope : copy.snapshotScope}`
  const html = buildCharacterSheetHtmlDocument({
    bodyMarkup: attributesMain.outerHTML,
    locale,
    title,
  })
  return {
    html,
    filename: buildCharacterSheetExportFilename(sheet, scope),
  }
}

export function downloadCharacterSheetHtml({ html, filename }: CharacterSheetExportResult): void {
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
}

function parseRenderedMain(markup: string): HTMLElement {
  const host = document.createElement('div')
  host.innerHTML = markup
  return requiredElement<HTMLElement>(host, 'main.character-page')
}

function requiredElement<T extends Element>(root: ParentNode, selector: string): T {
  const element = root.querySelector(selector)
  if (!element) throw new Error(`Character Sheet export render is missing ${selector}`)
  return element as T
}

function insertExportDocumentMeta(
  shell: HTMLElement,
  sheet: CharacterSheetDTO,
  scope: CharacterSheetExportScope,
  locale: Locale,
  now: Date,
): void {
  const copy = characterSheetExportCopy(locale)
  const meta = document.createElement('section')
  meta.className = 'export-document-meta'

  const kicker = document.createElement('p')
  kicker.className = 'eyebrow'
  kicker.textContent = copy.documentTitle
  meta.append(kicker)

  const heading = document.createElement('h2')
  heading.textContent = scope === 'build' ? copy.buildScope : copy.snapshotScope
  meta.append(heading)

  const details = document.createElement('div')
  details.className = 'export-document-meta__details'
  const version = document.createElement('span')
  version.textContent = `${copy.buildVersion}: ${sheet.version_no}`
  details.append(version)
  if (scope === 'snapshot') {
    const timestamp = document.createElement('span')
    timestamp.textContent = `${copy.exportedAt}: ${new Intl.DateTimeFormat(locale, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(now)}`
    details.append(timestamp)
  }
  meta.append(details)
  shell.prepend(meta)
}

function preserveConditionLabels(root: HTMLElement, sheet: CharacterSheetDTO): void {
  pairCharacterSheetIndexRows(
    root,
    'button.condition-chip',
    sheet.conditions,
    (condition) => condition.condition_ref,
  ).forEach(({ row: button, item: condition }) => {
    const span = document.createElement('span')
    span.className = button.className
    span.textContent = formatConditionForExport(button.textContent ?? '', condition.note)
    button.replaceWith(span)
  })
}

function preserveInventoryQuantities(root: HTMLElement, quantityLabel: string): void {
  root.querySelectorAll('.inventory-card').forEach((card) => {
    const quantity = card.querySelector<HTMLElement>('.quantity-stepper strong')?.textContent?.trim()
    const inventoryMain = card.querySelector<HTMLElement>('.inventory-main')
    if (!quantity || !inventoryMain) return
    const summary = document.createElement('div')
    summary.className = 'export-quantity'
    const label = document.createElement('span')
    label.textContent = quantityLabel
    const value = document.createElement('strong')
    value.textContent = quantity
    summary.append(label, value)
    inventoryMain.append(summary)
  })
}

function removeInteractiveChrome(root: HTMLElement): void {
  root.querySelector('.character-hero .hero-editors')?.remove()
  root.querySelectorAll('.inline-search,.text-field,.add-inventory-panel,.inventory-actions,.stepper,.slot-actions,.mini-actions,.prepared-control').forEach((node) => node.remove())

  // The attributes page's Conditions panel is an editor. Snapshot conditions
  // remain visible in the hero strip after condition buttons are converted to spans.
  root.querySelectorAll('[role="combobox"]').forEach((combobox) => {
    combobox.closest('article.panel')?.remove()
  })
}

function flattenRoleplayDetails(root: HTMLElement): void {
  root.querySelectorAll<HTMLDetailsElement>('details').forEach((details) => {
    const section = document.createElement('section')
    section.className = details.className

    const summary = details.querySelector('summary')
    const primarySummary = summary?.firstElementChild
    if (primarySummary) {
      const heading = document.createElement('div')
      heading.className = 'export-roleplay-heading'
      heading.append(primarySummary.cloneNode(true))
      section.append(heading)
    }

    const grid = details.querySelector('.roleplay-grid')
    if (grid) section.append(grid.cloneNode(true))
    details.replaceWith(section)
  })
}

function applyBuildOnlyProjection(
  root: HTMLElement,
  sheet: CharacterSheetDTO,
  projection: CharacterSheetExportProjection,
  locale: Locale,
): void {
  const copy = characterSheetExportCopy(locale)
  const hpValue = root.querySelector<HTMLElement>('[data-testid="header-hp"]')
  const hpCard = hpValue?.closest<HTMLElement>('.hero-stat')
  if (hpValue && hpCard) {
    const label = hpCard.querySelector<HTMLElement>('span')
    if (label) label.textContent = copy.maxHp
    hpValue.textContent = String(sheet.max_hp)
    hpCard.querySelector('small')?.remove()
  }
  root.querySelector('[data-testid="header-temp-hp"]')?.closest('.hero-stat')?.remove()
  root.querySelector('.hero-live-row')?.remove()

  for (const entry of projection.hitDice) {
    const value = root.querySelector<HTMLElement>(`[data-testid="hit-die-${cssEscape(entry.die)}"]`)
    if (value) value.textContent = String(entry.total)
  }
  const firstDie = root.querySelector('.die-card')
  const hitDiceTitle = firstDie?.closest('article.panel')?.querySelector<HTMLElement>('.panel-title span')
  if (hitDiceTitle) hitDiceTitle.textContent = copy.total

  const preparedSources = sheet.spellcasting.filter((source) => source.prepared_limit != null)
  pairCharacterSheetIndexRows(
    root,
    '.prepared-limit',
    preparedSources,
    (source) => source.source_key,
  ).forEach(({ row: node, item: source }) => {
    const label = node.querySelector<HTMLElement>('small')
    const value = node.querySelector<HTMLElement>('b')
    if (label) label.textContent = copy.preparedLimit
    if (value) value.textContent = String(source.prepared_limit)
  })
  root.querySelectorAll('.prepared-limit-hint').forEach((node) => node.remove())

  const slotPairs = pairCharacterSheetIndexRows(
    root,
    '.slot-card',
    projection.spellSlots,
    (entry) => entry.level,
  )
  slotPairs.forEach(({ row: card, item: entry }) => {
    const value = card.querySelector<HTMLElement>('strong')
    const caption = card.querySelector<HTMLElement>('small')
    if (value) value.textContent = String(entry.total)
    if (caption) caption.textContent = copy.total
  })
  const spellSlotSubtitle = slotPairs[0]?.row
    .closest('article.panel')
    ?.querySelector<HTMLElement>('.panel-title span')
  if (spellSlotSubtitle) spellSlotSubtitle.textContent = copy.capacity

  pairCharacterSheetIndexRows(
    root,
    '.resource-list > div',
    projection.resources,
    (entry) => entry.key,
  ).forEach(({ row, item: entry }) => {
    const value = row.querySelector<HTMLElement>('strong')
    if (value) value.textContent = String(entry.total)
    const caption = document.createElement('small')
    caption.className = 'export-capacity-label'
    caption.textContent = copy.capacity
    row.append(caption)
  })

  root.querySelectorAll('.spell-card').forEach((card) => card.classList.remove('is-prepared'))
  root.querySelectorAll('.prepared-badge').forEach((node) => node.remove())

  const note = document.createElement('p')
  note.className = 'export-ac-note'
  note.textContent = copy.acNote
  root.querySelector('.character-hero')?.append(note)
}

function cssEscape(value: string): string {
  if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') return CSS.escape(value)
  return value.replace(/(["\\])/g, '\\$1')
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}
