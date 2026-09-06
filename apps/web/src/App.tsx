import { useEffect } from 'react'

import { CharacterVersionHistoryPage } from './features/character-builder/CharacterVersionHistoryPage'
import { CharacterWorkshopPage } from './features/character-builder/CharacterWorkshopPage'
import { CapabilityDisabledPage } from './features/capabilities/CapabilityDisabledPage'
import { useCapabilities } from './features/capabilities/CapabilityProvider'
import { capabilityCopy } from './features/capabilities/copy'
import { protectedCapabilityForPath } from './features/capabilities/routes'
import { CharacterBuilderRoutePage } from './features/m01m/M01MBuilderRoutePanel'
import { CharacterSheetRoutePage } from './features/m01m/M01MAncestryRoutePanel'
import { RoomCharacterWorkspacePage } from './features/rooms/RoomCharacterWorkspacePage'
import { RoomLandingPage } from './features/rooms/RoomLandingPage'
import { roomIdFromPath, RoomWorkspacePage } from './features/rooms/RoomWorkspacePage'
import { legacyWebRoomRedirectPath } from './features/rooms/roomCharacterRouting'
import { useLocale } from './i18n/LocaleProvider'
import { useUiCopy } from './i18n/useUiCopy'

export const P0_FIXTURE_ID = '00000000-0000-4000-8000-0000000000e0'
const UUID_PATTERN = '[0-9a-fA-F-]{36}'

export function characterIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/characters\/([0-9a-fA-F-]{36})\/?$/)
  return match?.[1] ?? null
}

export function characterVersionsFromPath(
  pathname: string,
): { characterId: string; versionNo: number | null } | null {
  const match = pathname.match(
    /^\/characters\/([0-9a-fA-F-]{36})\/versions(?:\/(\d+))?\/?$/,
  )
  if (!match) return null
  return {
    characterId: match[1],
    versionNo: match[2] ? Number(match[2]) : null,
  }
}

export function builderDraftIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/character-builder\/([0-9a-fA-F-]{36})\/?$/)
  return match?.[1] ?? null
}

export type RoomCharacterRoute =
  | { kind: 'workshop'; roomId: string }
  | { kind: 'character'; roomId: string; characterId: string }
  | { kind: 'versions'; roomId: string; characterId: string; versionNo: number | null }
  | { kind: 'builder'; roomId: string; draftId: string }

export function roomCharacterRouteFromPath(pathname: string): RoomCharacterRoute | null {
  const workshop = pathname.match(new RegExp(`^/rooms/(${UUID_PATTERN})/characters/?$`))
  if (workshop) return { kind: 'workshop', roomId: workshop[1] }

  const versions = pathname.match(
    new RegExp(`^/rooms/(${UUID_PATTERN})/characters/(${UUID_PATTERN})/versions(?:/(\\d+))?/?$`),
  )
  if (versions) {
    return {
      kind: 'versions',
      roomId: versions[1],
      characterId: versions[2],
      versionNo: versions[3] ? Number(versions[3]) : null,
    }
  }

  const character = pathname.match(
    new RegExp(`^/rooms/(${UUID_PATTERN})/characters/(${UUID_PATTERN})/?$`),
  )
  if (character) {
    return { kind: 'character', roomId: character[1], characterId: character[2] }
  }

  const builder = pathname.match(
    new RegExp(`^/rooms/(${UUID_PATTERN})/character-builder/(${UUID_PATTERN})/?$`),
  )
  if (builder) return { kind: 'builder', roomId: builder[1], draftId: builder[2] }
  return null
}

function LegacyWebCharacterRedirect({ pathname }: { pathname: string }) {
  useEffect(() => {
    window.location.replace(legacyWebRoomRedirectPath(pathname))
  }, [pathname])
  return null
}

function isGlobalCharacterPath(pathname: string): boolean {
  return (
    pathname === '/characters' ||
    pathname.startsWith('/characters/') ||
    pathname.startsWith('/character-builder/')
  )
}

export default function App() {
  const { t } = useUiCopy()
  const { locale } = useLocale()
  const capabilityPresentation = capabilityCopy(locale)
  const { snapshot, isEnabled } = useCapabilities()
  const pathname = typeof window === 'undefined' ? '/' : window.location.pathname
  const protectedCapability = protectedCapabilityForPath(pathname)
  const roomCharacterRoute = roomCharacterRouteFromPath(pathname)
  const roomId = roomIdFromPath(pathname)

  if (protectedCapability && !isEnabled(protectedCapability)) {
    return <CapabilityDisabledPage />
  }
  if (roomCharacterRoute) {
    if (roomCharacterRoute.kind === 'workshop') {
      return <RoomCharacterWorkspacePage roomId={roomCharacterRoute.roomId} />
    }
    if (roomCharacterRoute.kind === 'versions') {
      return (
        <CharacterVersionHistoryPage
          characterId={roomCharacterRoute.characterId}
          versionNo={roomCharacterRoute.versionNo}
        />
      )
    }
    if (roomCharacterRoute.kind === 'character') {
      return <CharacterSheetRoutePage characterId={roomCharacterRoute.characterId} />
    }
    return <CharacterBuilderRoutePage draftId={roomCharacterRoute.draftId} />
  }
  if (roomId) return <RoomWorkspacePage roomId={roomId} />

  if (isEnabled('room') && isGlobalCharacterPath(pathname)) {
    return <LegacyWebCharacterRedirect pathname={pathname} />
  }

  const versions = characterVersionsFromPath(pathname)
  const characterId = characterIdFromPath(pathname)
  const draftId = builderDraftIdFromPath(pathname)
  if (versions) {
    return (
      <CharacterVersionHistoryPage
        characterId={versions.characterId}
        versionNo={versions.versionNo}
      />
    )
  }
  if (characterId) return <CharacterSheetRoutePage characterId={characterId} />
  if (draftId) return <CharacterBuilderRoutePage draftId={draftId} />
  if (pathname === '/characters' || pathname === '/characters/') return <CharacterWorkshopPage />
  if (pathname === '/' && isEnabled('room')) return <RoomLandingPage />

  return (
    <main className="landing-page">
      <section className="landing-card">
        <p className="eyebrow">{t('landing.eyebrow')}</p>
        <div className="landing-mark" aria-hidden="true">AT</div>
        <h1>Adventure Table</h1>
        <p>{t('landing.description')}</p>
        {snapshot.database_path ? (
          <div className="landing-data-path">
            <strong>{capabilityPresentation.dataPathLabel}</strong>
            <code>{snapshot.database_path}</code>
            <small>{capabilityPresentation.dataPathHint}</small>
          </div>
        ) : null}
        <a className="button primary landing-action" href="/characters">
          {t('landing.workshop')}
        </a>
      </section>
    </main>
  )
}
