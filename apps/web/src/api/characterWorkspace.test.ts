import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  characterWorkspaceApiPath,
  characterWorkspaceFetch,
  characterWorkspaceFrontendPath,
  configureCharacterWorkspaceApi,
} from './characterWorkspace'

const ROOM_ID = '22222222-2222-4222-8222-222222222222'

afterEach(() => {
  configureCharacterWorkspaceApi(null)
  vi.unstubAllGlobals()
})

describe('Character Workspace API context', () => {
  it('keeps Standalone Character and Builder paths global', () => {
    configureCharacterWorkspaceApi(null)
    expect(characterWorkspaceApiPath('/api/characters')).toBe('/api/characters')
    expect(characterWorkspaceApiPath('/api/character-builder/drafts')).toBe('/api/character-builder/drafts')
    expect(characterWorkspaceFrontendPath('/characters/abc')).toBe('/characters/abc')
  })

  it('binds API and navigation paths to the explicit Room context', () => {
    configureCharacterWorkspaceApi({ roomId: ROOM_ID, accessToken: 'room-token' })
    expect(characterWorkspaceApiPath('/api/characters?archived=true')).toBe(
      `/api/rooms/${ROOM_ID}/characters?archived=true`,
    )
    expect(characterWorkspaceApiPath('/api/character-builder/drafts/abc')).toBe(
      `/api/rooms/${ROOM_ID}/character-builder/drafts/abc`,
    )
    expect(characterWorkspaceApiPath('/api/rules/content/spells')).toBe('/api/rules/content/spells')
    expect(characterWorkspaceFrontendPath('/characters/abc/versions')).toBe(
      `/rooms/${ROOM_ID}/characters/abc/versions`,
    )
    expect(characterWorkspaceFrontendPath('/character-builder/draft-id')).toBe(
      `/rooms/${ROOM_ID}/character-builder/draft-id`,
    )
  })

  it('adds the Room token only to Character Workspace requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    configureCharacterWorkspaceApi({ roomId: ROOM_ID, accessToken: 'room-token' })

    await characterWorkspaceFetch('/api/characters/abc/sheet')
    const [target, init] = fetchMock.mock.calls[0]
    expect(target).toBe(`/api/rooms/${ROOM_ID}/characters/abc/sheet`)
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer room-token')

    await characterWorkspaceFetch('/api/rules/content/spells')
    const [globalTarget, globalInit] = fetchMock.mock.calls[1]
    expect(globalTarget).toBe('/api/rules/content/spells')
    expect(globalInit).toBeUndefined()
  })
})
