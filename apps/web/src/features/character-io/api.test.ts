import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  commitCharacterImport,
  filenameFromDisposition,
  previewCharacterImport,
} from './api'

const importResult = {
  dry_run: true,
  landing_mode: 'character' as const,
  resolved_ref_count: 3,
  unresolved_ref_count: 0,
  unresolved_refs: [],
  duplicate_hint: null,
  character_preview: {
    name: 'Portable Hero',
    level: 1,
    class_summary: 'Fighter 1',
  },
  character_id: null,
  draft_id: null,
  character_path: null,
  draft_path: null,
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('M03-B export filename parsing', () => {
  it('prefers the RFC 5987 UTF-8 form over the ASCII fallback', () => {
    expect(
      filenameFromDisposition(
        `attachment; filename="character-v1-test.json"; filename*=UTF-8''%E6%B8%AC%E8%A9%A6%20%E8%A7%92%E8%89%B2-v1-test.json`,
      ),
    ).toBe('測試 角色-v1-test.json')
  })

  it('falls back to the quoted ASCII filename when no UTF-8 form is sent', () => {
    expect(filenameFromDisposition('attachment; filename="Fighter-v1-20260904T000000Z.json"')).toBe(
      'Fighter-v1-20260904T000000Z.json',
    )
  })

  it('keeps the raw value when the UTF-8 form is not decodable', () => {
    expect(filenameFromDisposition("attachment; filename*=UTF-8''%E4%B8")).toBe('%E4%B8')
  })

  it('uses a safe default when the header is absent or unparseable', () => {
    expect(filenameFromDisposition(null)).toBe('character.json')
    expect(filenameFromDisposition('attachment')).toBe('character.json')
  })
})

describe('M03-C character import API', () => {
  it('sends the original JSON body to dry-run without rebuilding it in the client', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(importResult), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const documentText = '{"envelope":{"opaque":"spacing preserved"},"payload":{}}'

    await previewCharacterImport(documentText)

    expect(fetchMock).toHaveBeenCalledWith('/api/characters/import?dry_run=true', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: documentText,
    })
  })

  it('uses the same raw JSON body for commit', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ...importResult, dry_run: false }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const documentText = '{"envelope":{},"payload":{}}'

    await commitCharacterImport(documentText)

    expect(fetchMock).toHaveBeenCalledWith('/api/characters/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: documentText,
    })
  })
})
