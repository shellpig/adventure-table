import { readFileSync } from 'node:fs'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { AdventureApiError, type AdventureDefinition, type AttachedAdventure } from '../../api/adventures'
import { LocaleProvider } from '../../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type LocaleStorage } from '../../i18n/locale'
import { adventureErrorMessage, adventuresCopy } from './adventuresCopy'
import { adventureStatusLabel } from './RoomAdventuresPage'
import { attachableAdventures, AttachedAdventureList } from './CampaignAdventuresSection'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'

function testStorage(locale: 'en' | 'zh-TW'): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? locale : null),
    setItem: () => undefined,
  }
}

describe('attachableAdventures', () => {
  it('keeps only finalized, excludes already-attached ids, and preserves server order', () => {
    const all: AdventureDefinition[] = [
      {
        id: 'adv-draft',
        room_id: ROOM_ID,
        name: 'Draft Adventure',
        summary: null,
        ruleset: 'dnd5e-2014',
        status: 'draft',
        created_at: '2026-09-20T00:00:00Z',
        updated_at: '2026-09-20T00:00:00Z',
      },
      {
        id: 'adv-fin-1',
        room_id: ROOM_ID,
        name: 'Finalized One',
        summary: 'First finalized',
        ruleset: 'dnd5e-2014',
        status: 'finalized',
        created_at: '2026-09-20T01:00:00Z',
        updated_at: '2026-09-20T01:00:00Z',
      },
      {
        id: 'adv-fin-attached',
        room_id: ROOM_ID,
        name: 'Finalized Attached',
        summary: null,
        ruleset: 'dnd5e-2014',
        status: 'finalized',
        created_at: '2026-09-20T02:00:00Z',
        updated_at: '2026-09-20T02:00:00Z',
      },
      {
        id: 'adv-archived',
        room_id: ROOM_ID,
        name: 'Archived Adventure',
        summary: null,
        ruleset: 'dnd5e-2014',
        status: 'archived',
        created_at: '2026-09-20T03:00:00Z',
        updated_at: '2026-09-20T03:00:00Z',
      },
      {
        id: 'adv-fin-2',
        room_id: ROOM_ID,
        name: 'Finalized Two',
        summary: 'Second finalized',
        ruleset: 'dnd5e-2014',
        status: 'finalized',
        created_at: '2026-09-20T04:00:00Z',
        updated_at: '2026-09-20T04:00:00Z',
      },
    ]

    const attached: AttachedAdventure[] = [
      {
        campaign_id: CAMPAIGN_ID,
        adventure_id: 'adv-fin-attached',
        sort_order: 1,
        attached_at: '2026-09-20T05:00:00Z',
        name: 'Finalized Attached',
        summary: null,
        status: 'finalized',
      },
    ]

    const attachable = attachableAdventures(all, attached)
    expect(attachable.map((item) => item.id)).toEqual(['adv-fin-1', 'adv-fin-2'])
  })
})

describe('adventureStatusLabel', () => {
  it('returns the three labels in both locales', () => {
    const en = adventuresCopy('en')
    const zhTw = adventuresCopy('zh-TW')

    expect(adventureStatusLabel('draft', en)).toBe('Draft')
    expect(adventureStatusLabel('finalized', en)).toBe('Finalized')
    expect(adventureStatusLabel('archived', en)).toBe('Archived')

    expect(adventureStatusLabel('draft', zhTw)).toBe('草稿')
    expect(adventureStatusLabel('finalized', zhTw)).toBe('已定稿')
    expect(adventureStatusLabel('archived', zhTw)).toBe('已封存')
  })
})

describe('AttachedAdventureList rendering', () => {
  const sampleAttached: AttachedAdventure[] = [
    {
      campaign_id: CAMPAIGN_ID,
      adventure_id: '11111111-1111-4111-8111-111111111111',
      sort_order: 1,
      attached_at: '2026-09-20T01:00:00Z',
      name: 'Sunless Citadel',
      summary: 'A goblin-infested fortress.',
      status: 'finalized',
    },
    {
      campaign_id: CAMPAIGN_ID,
      adventure_id: '22222222-2222-4222-8222-222222222222',
      sort_order: 2,
      attached_at: '2026-09-20T02:00:00Z',
      name: 'Forge of Fury',
      summary: null,
      status: 'finalized',
    },
  ]

  it('renders names, status label, open links, and Detach button in English and empty list shows attachedEmpty', () => {
    const copyEn = adventuresCopy('en')
    const htmlEn = renderToStaticMarkup(
      <LocaleProvider documentTarget={null} storage={testStorage('en')}>
        <AttachedAdventureList
          attached={sampleAttached}
          copy={copyEn}
          roomId={ROOM_ID}
          onDetach={vi.fn()}
        />
      </LocaleProvider>,
    )

    expect(htmlEn).toContain('Sunless Citadel')
    expect(htmlEn).toContain('Forge of Fury')
    expect(htmlEn).toContain(`${copyEn.statusLabel}: Finalized`)
    expect(htmlEn).toContain(`/rooms/${ROOM_ID}/adventures/11111111-1111-4111-8111-111111111111`)
    expect(htmlEn).toContain(`/rooms/${ROOM_ID}/adventures/22222222-2222-4222-8222-222222222222`)
    expect(htmlEn).toContain(`>${copyEn.detach}<`)

    const emptyHtmlEn = renderToStaticMarkup(
      <LocaleProvider documentTarget={null} storage={testStorage('en')}>
        <AttachedAdventureList
          attached={[]}
          copy={copyEn}
          roomId={ROOM_ID}
          onDetach={vi.fn()}
        />
      </LocaleProvider>,
    )
    expect(emptyHtmlEn).toContain(copyEn.attachedEmpty)
  })

  it('renders status label, Detach button, and empty state in zh-TW', () => {
    const copyZh = adventuresCopy('zh-TW')
    const htmlZh = renderToStaticMarkup(
      <LocaleProvider documentTarget={null} storage={testStorage('zh-TW')}>
        <AttachedAdventureList
          attached={sampleAttached}
          copy={copyZh}
          roomId={ROOM_ID}
          onDetach={vi.fn()}
        />
      </LocaleProvider>,
    )

    expect(htmlZh).toContain('Sunless Citadel')
    expect(htmlZh).toContain('Forge of Fury')
    expect(htmlZh).toContain(`${copyZh.statusLabel}: 已定稿`)
    expect(htmlZh).toContain(`>${copyZh.detach}<`)

    const emptyHtmlZh = renderToStaticMarkup(
      <LocaleProvider documentTarget={null} storage={testStorage('zh-TW')}>
        <AttachedAdventureList
          attached={[]}
          copy={copyZh}
          roomId={ROOM_ID}
          onDetach={vi.fn()}
        />
      </LocaleProvider>,
    )
    expect(emptyHtmlZh).toContain(copyZh.attachedEmpty)
  })
})

describe('Attached Adventures copy and error mapping', () => {
  it('maintains key parity for newly added keys between en and zh-TW', () => {
    const en = adventuresCopy('en')
    const zhTw = adventuresCopy('zh-TW')

    const newKeys = [
      'attachedTitle',
      'attachedIntro',
      'attachedEmpty',
      'attachPicker',
      'attachAction',
      'detach',
      'detachConfirm',
      'noAttachable',
      'goToAdventures',
      'errCampaignAdventureLinkNotFound',
      'errCampaignNotFound',
    ] as const

    for (const key of newKeys) {
      expect(en[key]).toBeTruthy()
      expect(zhTw[key]).toBeTruthy()
      expect(en[key]).not.toContain('P6')
      expect(zhTw[key]).not.toContain('P6')
    }
  })

  it('maps campaign_adventure_link_not_found and campaign_not_found in both locales', () => {
    for (const locale of ['en', 'zh-TW'] as const) {
      const copy = adventuresCopy(locale)

      const linkNotFound = new AdventureApiError(404, 'campaign_adventure_link_not_found', 'Not linked')
      expect(adventureErrorMessage(linkNotFound, copy)).toBe(copy.errCampaignAdventureLinkNotFound)

      const campaignNotFound = new AdventureApiError(404, 'campaign_not_found', 'Campaign not found')
      expect(adventureErrorMessage(campaignNotFound, copy)).toBe(copy.errCampaignNotFound)
    }
  })
})

describe('CampaignAdventuresSection and RoomCampaignPage source assertions', () => {
  it('confirms detach and binds effect deps exactly to [roomId, campaignId, token]', () => {
    const source = readFileSync(new URL('./CampaignAdventuresSection.tsx', import.meta.url), 'utf8')

    expect(source).toContain('window.confirm(copy.detachConfirm)')
    expect(source).toContain('[roomId, campaignId, token]')
  })

  it('renders CampaignAdventuresSection only inside canManageRoster guard after the roster block', () => {
    const source = readFileSync(new URL('./RoomCampaignPage.tsx', import.meta.url), 'utf8')

    expect(source).toContain(
      '{canManageRoster ? <CampaignAdventuresSection roomId={roomId} campaignId={campaign.id} token={token} /> : null}',
    )

    const rosterIndex = source.indexOf('roster-list')
    const sectionIndex = source.indexOf('<CampaignAdventuresSection')
    expect(rosterIndex).toBeGreaterThan(0)
    expect(sectionIndex).toBeGreaterThan(rosterIndex)
  })
})
