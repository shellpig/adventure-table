import { readFileSync } from 'node:fs'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import {
  AdventureApiError,
  type AdventureEntry,
} from '../../api/adventures'
import { RoomAssetApiError } from '../../api/roomAssets'
import { LocaleProvider } from '../../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type LocaleStorage } from '../../i18n/locale'
import {
  AdventureEntryList,
  EntryAssetUploadForm,
  entryCreateFromForm,
  entryFormFromEntry,
  entryPatchFromForm,
  moveEntry,
  sectionOptions,
  type EntryFormState,
} from './AdventureEditorPage'
import {
  AdventureEntryPayloadFields,
  ENTRY_KIND_FIELDS,
  entryFieldsFromPayload,
  entryPayloadFromForm,
} from './AdventureEntryPayloadFields'
import { adventureErrorMessage, adventuresCopy } from './adventuresCopy'

vi.mock('../../api/roomAssets', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/roomAssets')>()
  return {
    ...actual,
    getRoomAssetContent: vi.fn().mockReturnValue(new Promise(() => {})),
  }
})

function testStorage(locale: 'en' | 'zh-TW'): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? locale : null),
    setItem: () => undefined,
  }
}

describe('AdventureEditorPage pure helpers and models', () => {
  it('covers all 12 kinds and matches the expected field list', () => {
    expect(ENTRY_KIND_FIELDS).toEqual({
      section: [],
      scene: ['read_aloud', 'dm_summary'],
      npc: ['role', 'disposition'],
      item: ['rarity', 'value_gp', 'is_magic'],
      monster_ref: ['monster_template_ref', 'count', 'notes'],
      quest: ['objective', 'reward'],
      secret: ['reveal_condition'],
      dm_note: [],
      suggested_check: ['ability', 'skill', 'dc', 'on_success', 'on_failure'],
      map: ['caption'],
      lore: ['topic'],
      other: [],
    })
  })

  it('builds typed payloads and omits empty/whitespace-only strings', () => {
    // scene with empty dm_summary omits it and keeps kind
    const scenePayload = entryPayloadFromForm({
      kind: 'scene',
      fields: { read_aloud: 'You enter a dark cave.', dm_summary: '   ' },
    })
    expect(scenePayload).toEqual({
      kind: 'scene',
      read_aloud: 'You enter a dark cave.',
    })

    // item converts value_gp to number and is_magic to boolean
    const itemPayload = entryPayloadFromForm({
      kind: 'item',
      fields: { rarity: 'rare', value_gp: ' 500 ', is_magic: 'true' },
    })
    expect(itemPayload).toEqual({
      kind: 'item',
      rarity: 'rare',
      value_gp: 500,
      is_magic: true,
    })

    // monster_ref converts count
    const monsterPayload = entryPayloadFromForm({
      kind: 'monster_ref',
      fields: { monster_template_ref: 'goblin', count: ' 3 ', notes: '   ' },
    })
    expect(monsterPayload).toEqual({
      kind: 'monster_ref',
      monster_template_ref: 'goblin',
      count: 3,
    })

    // suggested_check converts dc and passes ability
    const checkPayload = entryPayloadFromForm({
      kind: 'suggested_check',
      fields: { ability: 'wis', dc: ' 15 ', skill: 'Perception' },
    })
    expect(checkPayload).toEqual({
      kind: 'suggested_check',
      ability: 'wis',
      dc: 15,
      skill: 'Perception',
    })

    // section produces { kind: 'section' } only
    const sectionPayload = entryPayloadFromForm({
      kind: 'section',
      fields: {},
    })
    expect(sectionPayload).toEqual({ kind: 'section' })
  })

  it('defaults suggested_check ability to str and dc to NaN when empty, and npc disposition to unknown', () => {
    const checkPayload = entryPayloadFromForm({
      kind: 'suggested_check',
      fields: {},
    })
    expect(checkPayload.kind).toBe('suggested_check')
    if (checkPayload.kind === 'suggested_check') {
      expect(checkPayload.ability).toBe('str')
      expect(Number.isNaN(checkPayload.dc)).toBe(true)
    }

    const npcPayload = entryPayloadFromForm({
      kind: 'npc',
      fields: {},
    })
    expect(npcPayload.kind).toBe('npc')
    if (npcPayload.kind === 'npc') {
      expect(npcPayload.disposition).toBe('unknown')
    }
  })

  it('round-trips suggested_check and quest entries', () => {
    const checkEntry: AdventureEntry = {
      id: 'entry-1',
      adventure_id: 'adv-1',
      parent_entry_id: null,
      kind: 'suggested_check',
      title: 'Check Lock',
      body: 'Look closely',
      visibility: 'public',
      sort_order: 1,
      assets: [],
      data: {
        kind: 'suggested_check',
        ability: 'dex',
        dc: 14,
        skill: 'Thieves Tools',
      },
      created_at: '2026-09-20T00:00:00Z',
      updated_at: '2026-09-20T00:00:00Z',
    }
    const checkForm = entryFormFromEntry(checkEntry)
    expect(checkForm.fields.ability).toBe('dex')
    expect(checkForm.fields.dc).toBe('14')
    expect(checkForm.fields.skill).toBe('Thieves Tools')

    const questEntry: AdventureEntry = {
      id: 'entry-2',
      adventure_id: 'adv-1',
      parent_entry_id: null,
      kind: 'quest',
      title: 'Find the relic',
      body: null,
      visibility: 'public',
      sort_order: 2,
      assets: [],
      data: {
        kind: 'quest',
        objective: 'Find the lost orb',
        reward: null,
      },
      created_at: '2026-09-20T00:00:00Z',
      updated_at: '2026-09-20T00:00:00Z',
    }
    const questForm = entryFormFromEntry(questEntry)
    expect(questForm.fields.objective).toBe('Find the lost orb')
    expect(questForm.fields.reward).toBe('')
  })

  it('normalizes empty strings to null and carries kind in data', () => {
    const form: EntryFormState = {
      kind: 'scene',
      title: '   ',
      body: '',
      visibility: 'public',
      parentEntryId: '   ',
      fields: { read_aloud: 'Echoing darkness.' },
    }
    const create = entryCreateFromForm(form)
    expect(create.title).toBeNull()
    expect(create.body).toBeNull()
    expect(create.parent_entry_id).toBeNull()
    expect(create.data).toEqual({ kind: 'scene', read_aloud: 'Echoing darkness.' })

    const patch = entryPatchFromForm(form)
    expect(patch.title).toBeNull()
    expect(patch.body).toBeNull()
    expect(patch.parent_entry_id).toBeNull()
    expect(patch.data).toEqual({ kind: 'scene', read_aloud: 'Echoing darkness.' })
  })

  it('handles moving entries up/down with boundaries and unknown id', () => {
    const entries = [
      { id: '1' },
      { id: '2' },
      { id: '3' },
    ] as AdventureEntry[]

    expect(moveEntry(entries, '2', -1)).toEqual(['2', '1', '3'])
    expect(moveEntry(entries, '2', 1)).toEqual(['1', '3', '2'])
    expect(moveEntry(entries, '1', -1)).toBeNull()
    expect(moveEntry(entries, '3', 1)).toBeNull()
    expect(moveEntry(entries, 'unknown', -1)).toBeNull()
  })

  it('filters only sections and excludes current editing id', () => {
    const entries = [
      { id: 'sec-1', kind: 'section' },
      { id: 'sec-2', kind: 'section' },
      { id: 'scene-1', kind: 'scene' },
    ] as AdventureEntry[]

    expect(sectionOptions(entries, null)).toEqual([
      { id: 'sec-1', kind: 'section' },
      { id: 'sec-2', kind: 'section' },
    ])
    expect(sectionOptions(entries, 'sec-1')).toEqual([
      { id: 'sec-2', kind: 'section' },
    ])
  })

  it('renders extracted AdventureEntryPayloadFields and verifies entryFieldsFromPayload round-trip', () => {
    const copy = adventuresCopy('en')
    const html = renderToStaticMarkup(
      <AdventureEntryPayloadFields
        copy={copy}
        fields={{ ability: 'wis', dc: '15', skill: 'Perception' }}
        kind="suggested_check"
        onChange={vi.fn()}
      />,
    )
    expect(html).toContain('Perception')
    expect(html).toContain('15')
    expect(html).toContain(copy.abilityWis)

    const payload = entryPayloadFromForm({
      kind: 'suggested_check',
      fields: { ability: 'wis', dc: '15', skill: 'Perception' },
    })
    const extractedFields = entryFieldsFromPayload(payload)
    expect(extractedFields).toEqual({
      ability: 'wis',
      dc: '15',
      skill: 'Perception',
      on_success: '',
      on_failure: '',
    })

    const rebuiltPayload = entryPayloadFromForm({
      kind: 'suggested_check',
      fields: extractedFields,
    })
    expect(rebuiltPayload).toEqual(payload)
  })
})

describe('AdventureEntryList rendering and copy parity', () => {
  const sampleEntries: AdventureEntry[] = [
    {
      id: 'sec-1',
      adventure_id: 'adv-1',
      parent_entry_id: null,
      kind: 'section',
      title: 'Chapter 1: The Descent',
      body: null,
      visibility: 'public',
      sort_order: 1,
      assets: [],
      data: { kind: 'section' },
      created_at: '2026-09-20T00:00:00Z',
      updated_at: '2026-09-20T00:00:00Z',
    },
    {
      id: 'scene-1',
      adventure_id: 'adv-1',
      parent_entry_id: 'sec-1',
      kind: 'scene',
      title: 'Dungeon Entrance',
      body: 'Cold air rushes past.',
      visibility: 'public',
      sort_order: 2,
      assets: [],
      data: { kind: 'scene' },
      created_at: '2026-09-20T00:00:00Z',
      updated_at: '2026-09-20T00:00:00Z',
    },
    {
      id: 'note-1',
      adventure_id: 'adv-1',
      parent_entry_id: null,
      kind: 'dm_note',
      title: null,
      body: 'Secret trap behind bookshelf.',
      visibility: 'dm_only',
      sort_order: 3,
      assets: [],
      data: { kind: 'dm_note' },
      created_at: '2026-09-20T00:00:00Z',
      updated_at: '2026-09-20T00:00:00Z',
    },
  ]

  it('renders entry list with kind labels, child indentation, untitled fallback, and no buttons when readOnly', () => {
    const enCopy = adventuresCopy('en')
    const enHtml = renderToStaticMarkup(
      <LocaleProvider storage={testStorage('en')} documentTarget={null}>
        <AdventureEntryList
          copy={enCopy}
          entries={sampleEntries}
          pending={false}
          readOnly={false}
          roomId="room-1"
          token="token-1"
          onAssetError={vi.fn()}
          onDelete={vi.fn()}
          onEdit={vi.fn()}
          onLinkAsset={vi.fn()}
          onMove={vi.fn()}
          onUnlinkAsset={vi.fn()}
        />
      </LocaleProvider>,
    )

    expect(enHtml).toContain(enCopy.kindSection)
    expect(enHtml).toContain(enCopy.kindScene)
    expect(enHtml).toContain(enCopy.kindDmNote)
    expect(enHtml).toContain('adventure-entry--child')
    expect(enHtml).not.toContain('?')
    expect(enHtml).toContain(enCopy.editEntry)
    expect(enHtml).toContain(enCopy.deleteEntry)
    expect(enHtml).toContain(enCopy.moveUp)
    expect(enHtml).toContain(enCopy.moveDown)

    const readOnlyHtml = renderToStaticMarkup(
      <LocaleProvider storage={testStorage('en')} documentTarget={null}>
        <AdventureEntryList
          copy={enCopy}
          entries={sampleEntries}
          pending={false}
          readOnly={true}
          roomId="room-1"
          token="token-1"
          onAssetError={vi.fn()}
          onDelete={vi.fn()}
          onEdit={vi.fn()}
          onLinkAsset={vi.fn()}
          onMove={vi.fn()}
          onUnlinkAsset={vi.fn()}
        />
      </LocaleProvider>,
    )
    expect(readOnlyHtml).not.toContain('<button')

    const zhCopy = adventuresCopy('zh-TW')
    const zhHtml = renderToStaticMarkup(
      <LocaleProvider storage={testStorage('zh-TW')} documentTarget={null}>
        <AdventureEntryList
          copy={zhCopy}
          entries={sampleEntries}
          pending={false}
          readOnly={false}
          roomId="room-1"
          token="token-1"
          onAssetError={vi.fn()}
          onDelete={vi.fn()}
          onEdit={vi.fn()}
          onLinkAsset={vi.fn()}
          onMove={vi.fn()}
          onUnlinkAsset={vi.fn()}
        />
      </LocaleProvider>,
    )
    expect(zhHtml).toContain(zhCopy.kindSection)
    expect(zhHtml).toContain(zhCopy.kindScene)
    expect(zhHtml).toContain(zhCopy.kindDmNote)
    expect(zhHtml).not.toContain('?')
    expect(zhHtml).toContain(zhCopy.editEntry)
    expect(zhHtml).toContain(zhCopy.deleteEntry)
  })

  it('renders entry with image and attachment assets correctly and respects readOnly', () => {
    const enCopy = adventuresCopy('en')
    const entryWithAssets: AdventureEntry = {
      id: 'entry-assets-1',
      adventure_id: 'adv-1',
      parent_entry_id: null,
      kind: 'scene',
      title: 'Cave of Echoes',
      body: 'Drip drop.',
      visibility: 'public',
      sort_order: 1,
      assets: [
        {
          asset: {
            id: 'asset-img-1',
            room_id: 'room-1',
            kind: 'image',
            original_filename: 'cave-map.png',
            mime_type: 'image/png',
            size_bytes: 1024,
            sha256: 'sha-img-1',
            visibility: 'dm_only',
            created_at: '2026-09-20T00:00:00Z',
          },
          role: 'image',
          sort_order: 1,
        },
        {
          asset: {
            id: 'asset-att-1',
            room_id: 'room-1',
            kind: 'source_document',
            original_filename: 'handout.pdf',
            mime_type: 'application/pdf',
            size_bytes: 2048,
            sha256: 'sha-att-1',
            visibility: 'room',
            created_at: '2026-09-20T00:00:00Z',
          },
          role: 'attachment',
          sort_order: 2,
        },
      ],
      data: { kind: 'scene' },
      created_at: '2026-09-20T00:00:00Z',
      updated_at: '2026-09-20T00:00:00Z',
    }

    const editableHtml = renderToStaticMarkup(
      <LocaleProvider storage={testStorage('en')} documentTarget={null}>
        <AdventureEntryList
          copy={enCopy}
          entries={[entryWithAssets]}
          pending={false}
          readOnly={false}
          roomId="room-1"
          token="token-1"
          onAssetError={vi.fn()}
          onDelete={vi.fn()}
          onEdit={vi.fn()}
          onLinkAsset={vi.fn()}
          onMove={vi.fn()}
          onUnlinkAsset={vi.fn()}
        />
      </LocaleProvider>,
    )
    expect(editableHtml).toContain('handout.pdf')
    expect(editableHtml).toContain(enCopy.roleImage)
    expect(editableHtml).toContain(enCopy.assetDmOnly)
    expect(editableHtml).toContain(enCopy.unlinkAsset)

    const readOnlyHtml = renderToStaticMarkup(
      <LocaleProvider storage={testStorage('en')} documentTarget={null}>
        <AdventureEntryList
          copy={enCopy}
          entries={[entryWithAssets]}
          pending={false}
          readOnly={true}
          roomId="room-1"
          token="token-1"
          onAssetError={vi.fn()}
          onDelete={vi.fn()}
          onEdit={vi.fn()}
          onLinkAsset={vi.fn()}
          onMove={vi.fn()}
          onUnlinkAsset={vi.fn()}
        />
      </LocaleProvider>,
    )
    expect(readOnlyHtml).toContain('handout.pdf')
    expect(readOnlyHtml).toContain(enCopy.roleImage)
    expect(readOnlyHtml).toContain(enCopy.assetDmOnly)
    expect(readOnlyHtml).not.toContain('<button')
  })

  it('renders EntryAssetUploadForm with image accept, role labels, visibility labels, and dm_only default', () => {
    const copy = adventuresCopy('en')
    const html = renderToStaticMarkup(
      <EntryAssetUploadForm
        copy={copy}
        onSubmit={vi.fn()}
      />,
    )
    expect(html).toContain('accept="image/png,image/jpeg,image/webp"')
    expect(html).toContain(copy.roleImage)
    expect(html).toContain(copy.roleMap)
    expect(html).toContain(copy.assetVisibilityRoom)
    expect(html).toContain(copy.assetVisibilityDmOnly)
    expect(html).toMatch(/value="dm_only" selected|selected="" value="dm_only"|<option selected="" value="dm_only"|<option value="dm_only" selected=""/)
  })

  it('maintains copy parity and maps new error codes', () => {
    const en = adventuresCopy('en')
    const zhTw = adventuresCopy('zh-TW')

    expect(Object.keys(en).sort()).toEqual(Object.keys(zhTw).sort())
    expect('editorPlaceholder' in en).toBe(false)
    expect('editorPlaceholder' in zhTw).toBe(false)

    for (const locale of ['en', 'zh-TW'] as const) {
      const copy = adventuresCopy(locale)
      const payloadErr = new AdventureApiError(400, 'adventure_entry_payload_invalid', 'Invalid')
      expect(adventureErrorMessage(payloadErr, copy)).toBe(copy.errAdventureEntryPayloadInvalid)

      const parentErr = new AdventureApiError(400, 'adventure_entry_parent_invalid', 'Invalid parent')
      expect(adventureErrorMessage(parentErr, copy)).toBe(copy.errAdventureEntryParentInvalid)

      const notFoundErr = new AdventureApiError(404, 'adventure_entry_not_found', 'Not found')
      expect(adventureErrorMessage(notFoundErr, copy)).toBe(copy.errAdventureEntryNotFound)

      const roomAssetNotFoundErr = new RoomAssetApiError(404, 'room_asset_not_found', 'Not found')
      expect(adventureErrorMessage(roomAssetNotFoundErr, copy)).toBe(copy.errRoomAssetNotFound)

      const assetEmptyErr = new RoomAssetApiError(400, 'asset_empty', 'Empty')
      expect(adventureErrorMessage(assetEmptyErr, copy)).toBe(copy.errAssetEmpty)
    }
  })

  it('verifies confirmation and effect deps in AdventureEditorPage source and authority guard in RoomAdventuresPage', () => {
    const editorSource = readFileSync(
      new URL('./AdventureEditorPage.tsx', import.meta.url),
      'utf8',
    )
    expect(editorSource).toContain('window.confirm(copy.entryDeleteConfirm)')
    expect(editorSource).toContain('window.confirm(copy.archiveConfirm)')
    expect(editorSource).toContain('}, [roomId, adventureId, token])')
    expect(editorSource).not.toContain('as unknown as')
    expect(editorSource).toContain('<label className="room-field">')
    expect(editorSource).not.toContain('<div className="room-field">')

    const uploadIdx = editorSource.indexOf('uploadRoomAsset(')
    const linkIdx = editorSource.indexOf('linkAdventureEntryAsset(')
    expect(uploadIdx).toBeGreaterThan(-1)
    expect(linkIdx).toBeGreaterThan(-1)
    expect(uploadIdx).toBeLessThan(linkIdx)
    expect(editorSource).toContain('.then((asset)')
    expect(editorSource).toContain('window.confirm(copy.unlinkConfirm)')

    const thumbSource = readFileSync(
      new URL('./AssetThumbnail.tsx', import.meta.url),
      'utf8',
    )
    expect(thumbSource).toContain('URL.createObjectURL')
    expect(thumbSource).toContain('URL.revokeObjectURL')
    expect(thumbSource).not.toContain('src={roomAssetContentUrl')

    const pageSource = readFileSync(
      new URL('./RoomAdventuresPage.tsx', import.meta.url),
      'utf8',
    )
    const noAuthorityIdx = pageSource.indexOf('noAuthority')
    const editorComponentIdx = pageSource.indexOf('<AdventureEditorPage')
    expect(noAuthorityIdx).toBeGreaterThan(-1)
    expect(editorComponentIdx).toBeGreaterThan(-1)
    expect(noAuthorityIdx).toBeLessThan(editorComponentIdx)
  })
})


