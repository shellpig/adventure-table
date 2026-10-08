import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  archiveCustomMonster,
  copyCustomMonster,
  createCustomMonster,
  createCustomMonsterFromContent,
  createCustomMonsterFromInstance,
  deleteCustomMonster,
  getMonsterLibraryEntry,
  listMonsterLibrary,
  listSessionMonsterLibrary,
  MonsterLibraryApiError,
  patchCustomMonster,
} from './monsterLibrary'

describe('monsterLibrary API client', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('lists monsters with formatted query parameters', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify([{ ref: 'srd5.1:monster:goblin', name: 'Goblin' }]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const list = await listMonsterLibrary('room-1', 'token-123', {
      query: 'gob',
      include_archived: true,
      limit: 10,
      offset: 5,
      source: 'custom',
    })

    expect(list).toEqual([{ ref: 'srd5.1:monster:goblin', name: 'Goblin' }])
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rooms/room-1/monster-library?query=gob&include_archived=true&limit=10&offset=5&source=custom',
      expect.objectContaining({
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer token-123',
        },
      }),
    )
  })

  it('lists monsters with sort and filter parameters', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await listMonsterLibrary('room-1', 'token-123', {
      sort: 'max_hp',
      order: 'desc',
      size: 'Large',
      type: 'dragon',
      cr_min: 10,
      cr_max: 15,
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rooms/room-1/monster-library?sort=max_hp&order=desc&size=Large&type=dragon&cr_min=10&cr_max=15',
      expect.objectContaining({
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer token-123',
        },
      }),
    )
  })

  it('sends cr_eq on its own for exact challenge rating matches', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await listMonsterLibrary('room-1', 'token-123', { cr_eq: 0.125 })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rooms/room-1/monster-library?cr_eq=0.125',
      expect.objectContaining({
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer token-123',
        },
      }),
    )
  })

  it('omits sort, order, and filters when they are at their defaults', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await listMonsterLibrary('room-1', 'token-123', {
      query: 'gob',
      include_archived: true,
      limit: 10,
      offset: 5,
      source: 'custom',
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rooms/room-1/monster-library?query=gob&include_archived=true&limit=10&offset=5&source=custom',
      expect.anything(),
    )
  })

  it('builds identical query strings for the room and session library readers', async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify([]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    const options = {
      query: 'drake',
      include_archived: true,
      limit: 10,
      offset: 5,
      source: 'custom',
      sort: 'challenge_rating',
      order: 'desc',
      size: 'Large',
      type: 'dragon',
      cr_min: 10,
      cr_max: 15,
    } as const
    fetchMock.mockClear()
    await listMonsterLibrary('room-1', 'token-123', options)
    await listSessionMonsterLibrary('room-1', 'camp-1', 'sess-1', 'token-123', options)

    const roomUrl = String(fetchMock.mock.calls[0][0])
    const sessionUrl = String(fetchMock.mock.calls[1][0])
    expect(sessionUrl).toContain('/campaigns/camp-1/sessions/sess-1/libraries/monster-library?')
    expect(sessionUrl.split('?')[1]).toBe(roomUrl.split('?')[1])
  })

  it('encodes ref segment when getting entry', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ref: 'srd5.1:monster:goblin', name: 'Goblin', rules: {} }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const res = await getMonsterLibraryEntry('room-1', 'srd5.1:monster:goblin', 'token-123')
    expect(res.name).toBe('Goblin')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rooms/room-1/monster-library/srd5.1%3Amonster%3Agoblin',
      expect.anything(),
    )
  })

  it('encodes custom ref segment when getting entry', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ref: 'custom:uuid-1', name: 'Custom Orc', rules: {} }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const res = await getMonsterLibraryEntry('room-1', 'custom:uuid-1', 'token-123')
    expect(res.name).toBe('Custom Orc')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rooms/room-1/monster-library/custom%3Auuid-1',
      expect.anything(),
    )
  })

  it('creates custom monster with POST /custom', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ref: 'custom:uuid-1', name: 'New Monster', rules: {} }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const payload = {
      name: 'New Monster',
      armor_class: 12,
      max_hp: 20,
    }
    const res = await createCustomMonster('room-1', 'token-123', payload)
    expect(res.ref).toBe('custom:uuid-1')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rooms/room-1/monster-library/custom',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    )
  })

  it('creates custom monster from content with POST /custom/from-content', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ref: 'custom:uuid-2', name: 'Copied Goblin', rules: {} }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const res = await createCustomMonsterFromContent('room-1', 'token-123', {
      content_key: 'srd5.1:monster:goblin',
      name: 'Copied Goblin',
    })
    expect(res.ref).toBe('custom:uuid-2')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rooms/room-1/monster-library/custom/from-content',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ content_key: 'srd5.1:monster:goblin', name: 'Copied Goblin' }),
      }),
    )
  })

  it('creates custom monster from instance with POST /custom/from-instance', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ref: 'custom:uuid-3', name: 'Saved Inst', rules: {} }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const res = await createCustomMonsterFromInstance('room-1', 'token-123', {
      instance_id: 'inst-1',
      name: 'Saved Inst',
    })
    expect(res.ref).toBe('custom:uuid-3')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rooms/room-1/monster-library/custom/from-instance',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ instance_id: 'inst-1', name: 'Saved Inst' }),
      }),
    )
  })

  it('copies custom monster with POST /custom/{id}/copy', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ref: 'custom:uuid-4', name: 'Copied Template', rules: {} }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const res = await copyCustomMonster('room-1', 'uuid-old', 'token-123', {
      expected_revision: 2,
      name: 'Copied Template',
    })
    expect(res.ref).toBe('custom:uuid-4')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rooms/room-1/monster-library/custom/uuid-old/copy',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ expected_revision: 2, name: 'Copied Template' }),
      }),
    )
  })

  it('patches custom monster with PATCH /custom/{id}', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ref: 'custom:uuid-1', name: 'Patched', revision: 3, rules: {} }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const res = await patchCustomMonster('room-1', 'uuid-1', 'token-123', {
      expected_revision: 2,
      armor_class: 15,
    })
    expect(res.revision).toBe(3)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rooms/room-1/monster-library/custom/uuid-1',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ expected_revision: 2, armor_class: 15 }),
      }),
    )
  })

  it('archives custom monster with POST /custom/{id}/archive', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ref: 'custom:uuid-1', archived_at: '2026-10-03T12:00:00Z', rules: {} }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const res = await archiveCustomMonster('room-1', 'uuid-1', 'token-123', {
      expected_revision: 3,
    })
    expect(res.archived_at).toBe('2026-10-03T12:00:00Z')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rooms/room-1/monster-library/custom/uuid-1/archive',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ expected_revision: 3 }),
      }),
    )
  })

  it('deletes custom monster with DELETE /custom/{id}?expected_revision={rev}', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))

    await deleteCustomMonster('room-1', 'uuid-1', 'token-123', 4)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rooms/room-1/monster-library/custom/uuid-1?expected_revision=4',
      expect.objectContaining({
        method: 'DELETE',
      }),
    )
  })

  it('throws MonsterLibraryApiError on error responses with code and message', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: {
            code: 'monster_template_revision_conflict',
            message: 'Revision conflict',
          },
        }),
        { status: 409, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    await expect(
      patchCustomMonster('room-1', 'uuid-1', 'token-123', { expected_revision: 1 }),
    ).rejects.toThrow(MonsterLibraryApiError)
  })
})
