import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  addJsonSource,
  addSourceFromAsset,
  AdventureImportApiError,
  type AdventureImportDraft,
  cancelAdventureImport,
  createAdventureImport,
  getAdventureImport,
  getAdventureImportDraft,
  listAdventureImports,
  listAdventureImportSources,
  readSourceChunk,
  updateAdventureImportDraft,
  type UpdateImportDraftInput,
  uploadRawSource,
} from './adventureImports'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const IMPORT_ID = '20000000-0000-4000-8000-000000000001'
const SOURCE_ID = '30000000-0000-4000-8000-000000000001'
const ASSET_ID = '40000000-0000-4000-8000-000000000001'
const TOKEN = 'room-token'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('P6-E Adventure Imports API client', () => {
  it('createAdventureImport POSTs to /api/rooms/{room}/adventure-imports with JSON and Bearer header', async () => {
    const mockImport = { id: IMPORT_ID, room_id: ROOM_ID, name: 'Tomb of Horrors', status: 'source', revision: 0 }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => mockImport,
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await createAdventureImport(ROOM_ID, TOKEN, { name: 'Tomb of Horrors' })

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/adventure-imports`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          Authorization: `Bearer ${TOKEN}`,
        }),
        body: JSON.stringify({ name: 'Tomb of Horrors' }),
      }),
    )
    expect(result).toEqual(mockImport)
  })

  it('listAdventureImports and getAdventureImport perform GET requests with Bearer header', async () => {
    const mockList = [{ id: IMPORT_ID, name: 'Tomb of Horrors' }]
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockList,
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockList[0],
      })
    vi.stubGlobal('fetch', fetchMock)

    const listRes = await listAdventureImports(ROOM_ID, TOKEN)
    expect(listRes).toEqual(mockList)
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      `/api/rooms/${ROOM_ID}/adventure-imports`,
      expect.objectContaining({ headers: { Authorization: `Bearer ${TOKEN}` } }),
    )

    const getRes = await getAdventureImport(ROOM_ID, IMPORT_ID, TOKEN)
    expect(getRes).toEqual(mockList[0])
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `/api/rooms/${ROOM_ID}/adventure-imports/${IMPORT_ID}`,
      expect.objectContaining({ headers: { Authorization: `Bearer ${TOKEN}` } }),
    )
  })

  it('cancelAdventureImport POSTs to /{import_id}/cancel with expected_revision in body', async () => {
    const mockCancelled = { id: IMPORT_ID, status: 'cancelled', revision: 1 }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockCancelled,
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await cancelAdventureImport(ROOM_ID, IMPORT_ID, TOKEN, { expected_revision: 0 })

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/adventure-imports/${IMPORT_ID}/cancel`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          Authorization: `Bearer ${TOKEN}`,
        }),
        body: JSON.stringify({ expected_revision: 0 }),
      }),
    )
    expect(result).toEqual(mockCancelled)
  })

  it.each([
    {
      label: 'paste',
      input: { source_kind: 'paste' as const, text: 'Hello adventure' },
    },
    {
      label: 'url',
      input: { source_kind: 'url' as const, url: 'https://example.com/mod' },
    },
  ])('addJsonSource POSTs $label source to /{import_id}/sources with JSON body', async ({ input }) => {
    const mockSource = { id: SOURCE_ID, import_id: IMPORT_ID, source_kind: input.source_kind }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockSource,
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await addJsonSource(ROOM_ID, IMPORT_ID, TOKEN, input)

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/adventure-imports/${IMPORT_ID}/sources`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          Authorization: `Bearer ${TOKEN}`,
        }),
        body: JSON.stringify(input),
      }),
    )
    expect(result).toEqual(mockSource)
  })

  it('uploadRawSource sends Blob body, Content-Type from Blob, query params, Bearer header, and NO application/json header', async () => {
    const mockSource = { id: SOURCE_ID, import_id: IMPORT_ID, source_kind: 'pdf' }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockSource,
    })
    vi.stubGlobal('fetch', fetchMock)

    const blob = new Blob(['%PDF-1.4 fake pdf'], { type: 'application/pdf' })
    const result = await uploadRawSource(ROOM_ID, IMPORT_ID, TOKEN, {
      source_kind: 'pdf',
      filename: 'adventure.pdf',
      file: blob,
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain(`/api/rooms/${ROOM_ID}/adventure-imports/${IMPORT_ID}/sources?`)
    const parsedUrl = new URL(url as string, 'http://localhost')
    expect(parsedUrl.searchParams.get('source_kind')).toBe('pdf')
    expect(parsedUrl.searchParams.get('filename')).toBe('adventure.pdf')

    expect(init.method).toBe('POST')
    expect(init.body).toBe(blob)
    expect(init.headers).toEqual({
      Authorization: `Bearer ${TOKEN}`,
      'Content-Type': 'application/pdf',
    })
    expect(init.headers).not.toHaveProperty('Content-Type', 'application/json')
    expect(result).toEqual(mockSource)
  })

  it('listAdventureImportSources and addSourceFromAsset perform expected requests', async () => {
    const mockSources = [{ id: SOURCE_ID, source_kind: 'txt' }]
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockSources,
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockSources[0],
      })
    vi.stubGlobal('fetch', fetchMock)

    const listRes = await listAdventureImportSources(ROOM_ID, IMPORT_ID, TOKEN)
    expect(listRes).toEqual(mockSources)
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      `/api/rooms/${ROOM_ID}/adventure-imports/${IMPORT_ID}/sources`,
      expect.objectContaining({ headers: { Authorization: `Bearer ${TOKEN}` } }),
    )

    const addRes = await addSourceFromAsset(ROOM_ID, IMPORT_ID, TOKEN, { asset_id: ASSET_ID })
    expect(addRes).toEqual(mockSources[0])
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `/api/rooms/${ROOM_ID}/adventure-imports/${IMPORT_ID}/sources/from-asset`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          Authorization: `Bearer ${TOKEN}`,
        }),
        body: JSON.stringify({ asset_id: ASSET_ID }),
      }),
    )
  })

  it.each([
    {
      label: 'with offset and limit',
      params: { offset: 100, limit: 50 },
      expectedQuery: 'offset=100&limit=50',
    },
    {
      label: 'with default offset and omitted limit',
      params: undefined,
      expectedQuery: 'offset=0',
    },
  ])('readSourceChunk constructs query $label', async ({ params, expectedQuery }) => {
    const mockChunk = { source_id: SOURCE_ID, offset: 0, text: 'chunk text', total_length: 100, next_offset: null }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockChunk,
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await readSourceChunk(ROOM_ID, IMPORT_ID, SOURCE_ID, TOKEN, params)

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/adventure-imports/${IMPORT_ID}/sources/${SOURCE_ID}/chunk?${expectedQuery}`,
      expect.objectContaining({ headers: { Authorization: `Bearer ${TOKEN}` } }),
    )
    expect(result).toEqual(mockChunk)
  })

  it('getAdventureImportDraft and updateAdventureImportDraft perform expected requests and verify types', async () => {
    // Compile-time fixture demonstrating exact response shape with all required default-bearing fields
    const fullResponse: AdventureImportDraft = {
      import_id: IMPORT_ID,
      draft: {
        schema_version: 1,
        entries: [
          {
            entry_id: 'e1',
            entry_kind: 'scene',
            payload: { kind: 'scene', dm_summary: 'Summary' },
            parent_entry_id: null,
            provenance: 'source_document',
            source_ref: { source_id: SOURCE_ID, locator: 'page:1' },
            note: null,
          },
        ],
        questions: [
          {
            question_id: 'q1',
            message: 'Question?',
            entry_id: null,
            answer: null,
          },
        ],
      },
      warnings: [
        {
          warning_id: 'w1',
          level: 'warning',
          code: 'warn_code',
          message: 'Warning msg',
          entry_id: null,
          source_id: null,
        },
      ],
      revision: 0,
      updated_at: '2026-09-22T00:00:00Z',
    }

    // Compile-time assignment demonstrating input shape allows omitting optional fields
    const minimalInput: UpdateImportDraftInput = {
      draft: {
        entries: [
          {
            entry_id: 'e1',
            entry_kind: 'scene',
            payload: { kind: 'scene' },
          },
        ],
      },
      expected_revision: 0,
    }

    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => fullResponse,
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ ...fullResponse, revision: 1 }),
      })
    vi.stubGlobal('fetch', fetchMock)

    const getRes = await getAdventureImportDraft(ROOM_ID, IMPORT_ID, TOKEN)
    expect(getRes).toEqual(fullResponse)
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      `/api/rooms/${ROOM_ID}/adventure-imports/${IMPORT_ID}/draft`,
      expect.objectContaining({ headers: { Authorization: `Bearer ${TOKEN}` } }),
    )

    const updateRes = await updateAdventureImportDraft(ROOM_ID, IMPORT_ID, TOKEN, minimalInput)
    expect(updateRes.revision).toBe(1)
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `/api/rooms/${ROOM_ID}/adventure-imports/${IMPORT_ID}/draft`,
      expect.objectContaining({
        method: 'PUT',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          Authorization: `Bearer ${TOKEN}`,
        }),
        body: JSON.stringify(minimalInput),
      }),
    )
  })

  it.each([
    { status: 400, code: 'adventure_import_invalid', message: 'Invalid payload' },
    { status: 403, code: 'adventure_import_authority_required', message: 'DM required' },
    { status: 404, code: 'adventure_import_not_found', message: 'Import not found' },
    { status: 409, code: 'adventure_import_revision_conflict', message: 'Revision conflict' },
    { status: 413, code: 'asset_too_large', message: 'Too large' },
  ])('maps HTTP $status to AdventureImportApiError with code $code', async ({ status, code, message }) => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status,
      json: async () => ({
        error: { code, message },
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(getAdventureImport(ROOM_ID, IMPORT_ID, TOKEN)).rejects.toThrow(AdventureImportApiError)

    try {
      await getAdventureImport(ROOM_ID, IMPORT_ID, TOKEN)
    } catch (err) {
      expect(err).toBeInstanceOf(AdventureImportApiError)
      const apiErr = err as AdventureImportApiError
      expect(apiErr.status).toBe(status)
      expect(apiErr.code).toBe(code)
      expect(apiErr.message).toBe(message)
    }
  })
})
