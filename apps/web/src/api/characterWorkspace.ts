export type CharacterWorkspaceApiContext = {
  roomId: string
  accessToken?: string | null
}

let activeRoomContext: CharacterWorkspaceApiContext | null = null

export function configureCharacterWorkspaceApi(
  context: CharacterWorkspaceApiContext | null,
): void {
  activeRoomContext = context
}

export function characterWorkspaceApiPath(path: string): string {
  if (!activeRoomContext) return path
  if (
    path === '/api/characters' ||
    path.startsWith('/api/characters/') ||
    path.startsWith('/api/characters?')
  ) {
    return `/api/rooms/${activeRoomContext.roomId}${path.slice('/api'.length)}`
  }
  if (
    path === '/api/character-builder' ||
    path.startsWith('/api/character-builder/') ||
    path.startsWith('/api/character-builder?')
  ) {
    return `/api/rooms/${activeRoomContext.roomId}${path.slice('/api'.length)}`
  }
  return path
}

export function characterWorkspaceFrontendPath(path: string): string {
  if (!activeRoomContext) return path
  if (path === '/characters' || path.startsWith('/characters/')) {
    return `/rooms/${activeRoomContext.roomId}${path}`
  }
  if (path === '/character-builder' || path.startsWith('/character-builder/')) {
    return `/rooms/${activeRoomContext.roomId}${path}`
  }
  return path
}

export function characterWorkspaceFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  if (typeof input !== 'string') return globalThis.fetch(input, init)
  const target = characterWorkspaceApiPath(input)
  if (!activeRoomContext || target === input) return globalThis.fetch(input, init)

  const headers = new Headers(init?.headers)
  if (activeRoomContext.accessToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${activeRoomContext.accessToken}`)
  }
  return globalThis.fetch(target, { ...init, headers })
}
