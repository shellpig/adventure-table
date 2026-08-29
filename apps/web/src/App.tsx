import { CharacterSheetPage } from './features/character-sheet/CharacterSheetPage'

export const P0_FIXTURE_ID = '00000000-0000-4000-8000-0000000000e0'

export function characterIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/characters\/([0-9a-fA-F-]{36})\/?$/)
  return match?.[1] ?? null
}

export default function App() {
  const pathname = typeof window === 'undefined' ? '/' : window.location.pathname
  const characterId = characterIdFromPath(pathname)

  if (characterId) {
    return <CharacterSheetPage characterId={characterId} />
  }

  return (
    <main className="landing-page">
      <section className="landing-card">
        <p className="eyebrow">P0-E · Character Sheet & State UI</p>
        <div className="landing-mark" aria-hidden="true">AT</div>
        <h1>Adventure Table</h1>
        <p>桌上跑團優先的 D&amp;D 5e 2014 角色卡。</p>
        <a className="button primary landing-action" href={`/characters/${P0_FIXTURE_ID}`}>
          開啟 P0 Fighter / Wizard 角色卡 →
        </a>
      </section>
    </main>
  )
}
