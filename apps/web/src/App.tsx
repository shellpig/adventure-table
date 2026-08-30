import { CharacterBuilderPage } from './features/character-builder/CharacterBuilderPage'
import { CharacterVersionHistoryPage } from './features/character-builder/CharacterVersionHistoryPage'
import { CharacterWorkshopPage } from './features/character-builder/CharacterWorkshopPage'
import { CharacterSheetPage } from './features/character-sheet/CharacterSheetPage'

export const P0_FIXTURE_ID = '00000000-0000-4000-8000-0000000000e0'

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

export default function App() {
  const pathname = typeof window === 'undefined' ? '/' : window.location.pathname
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
  if (characterId) return <CharacterSheetPage characterId={characterId} />
  if (draftId) return <CharacterBuilderPage draftId={draftId} />
  if (pathname === '/characters' || pathname === '/characters/') return <CharacterWorkshopPage />

  return (
    <main className="landing-page">
      <section className="landing-card">
        <p className="eyebrow">P1-G · Character Versions</p>
        <div className="landing-mark" aria-hidden="true">AT</div>
        <h1>Adventure Table</h1>
        <p>桌上跑團優先的 D&amp;D 5e 2014 角色工具。</p>
        <a className="button primary landing-action" href="/characters">
          開啟 Character Workshop →
        </a>
        <a className="button secondary landing-action" href={`/characters/${P0_FIXTURE_ID}`}>
          開啟 P0 Fighter / Wizard 角色卡
        </a>
      </section>
    </main>
  )
}
