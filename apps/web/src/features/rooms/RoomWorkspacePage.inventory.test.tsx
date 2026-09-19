import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type { Campaign } from '../../api/campaigns'
import type { CharacterListItem } from '../../api/characterBuilder'
import { LocaleProvider } from '../../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type LocaleStorage } from '../../i18n/locale'
import { roomCopy } from './copy'
import {
  buildDeleteInventory,
  DeleteRoomSection,
  type DeleteRoomSectionProps,
  fetchDeleteRoomInventory,
} from './RoomWorkspacePage'

vi.mock('../../api/campaigns', () => ({
  listCampaigns: vi.fn(),
}))

vi.mock('../../api/roomCharacters', () => ({
  listRoomCharacters: vi.fn(),
  listRoomDraftCount: vi.fn(),
}))

import { listCampaigns } from '../../api/campaigns'
import { listRoomCharacters, listRoomDraftCount } from '../../api/roomCharacters'

function testStorage(locale: 'en' | 'zh-TW'): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? locale : null),
    setItem: () => undefined,
  }
}

const mockCampaigns: Campaign[] = [
  {
    id: 'camp-1',
    room_id: 'room-1',
    name: 'Lost Mine of Phandelver',
    ruleset: 'dnd5e-2014',
    status: 'active',
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
  },
  {
    id: 'camp-2',
    room_id: 'room-1',
    name: 'Waterdeep: Dragon Heist',
    ruleset: 'dnd5e-2014',
    status: 'draft',
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:00:00Z',
  },
]

const mockActiveCharacters: CharacterListItem[] = [
  {
    id: 'char-1',
    name: 'Mira',
    level: 1,
    class_summary: 'Wizard 1',
    classes: [],
    version_no: 1,
  },
]

const mockArchivedCharacters: CharacterListItem[] = [
  {
    id: 'char-2',
    name: 'Brog',
    level: 2,
    class_summary: 'Barbarian 2',
    classes: [],
    version_no: 1,
  },
]

function renderDeleteSection(
  props: Partial<DeleteRoomSectionProps> = {},
  locale: 'en' | 'zh-TW' = 'en',
): string {
  const copy = roomCopy(locale)
  const defaultProps: DeleteRoomSectionProps = {
    roomId: 'room-1',
    roomName: 'Sunday Table',
    isOwner: true,
    deleteOpen: true,
    onOpenDelete: vi.fn(),
    onCancelDelete: vi.fn(),
    onConfirmDelete: vi.fn(),
    deleteConfirmation: '',
    onConfirmationChange: vi.fn(),
    deletePending: false,
    deleteError: null,
    inventory: null,
    inventoryLoading: false,
    inventoryError: false,
    copy,
    locale,
    ...props,
  }
  return renderToStaticMarkup(
    <LocaleProvider storage={testStorage(locale)} documentTarget={null}>
      <DeleteRoomSection {...defaultProps} />
    </LocaleProvider>,
  )
}

describe('Delete Room inventory logic and rendering', () => {
  describe('buildDeleteInventory', () => {
    it('assembles campaigns, active characters, archived characters, and draft counts', () => {
      const result = buildDeleteInventory(
        mockCampaigns,
        mockActiveCharacters,
        mockArchivedCharacters,
        3,
      )

      expect(result).toEqual({
        campaignCount: 2,
        characterCount: 2,
        draftCount: 3,
        campaigns: ['Lost Mine of Phandelver', 'Waterdeep: Dragon Heist'],
        characters: [
          { name: 'Mira', class_summary: 'Wizard 1', archived: false },
          { name: 'Brog', class_summary: 'Barbarian 2', archived: true },
        ],
      })
    })
  })

  describe('fetchDeleteRoomInventory', () => {
    it('loads campaigns, active and archived characters, and draft count in parallel', async () => {
      vi.mocked(listCampaigns).mockResolvedValue(mockCampaigns)
      vi.mocked(listRoomCharacters).mockImplementation(async (_roomId, _token, options) => {
        return options?.archived ? mockArchivedCharacters : mockActiveCharacters
      })
      vi.mocked(listRoomDraftCount).mockResolvedValue(3)

      const inventory = await fetchDeleteRoomInventory('room-1', 'token-1')

      expect(listCampaigns).toHaveBeenCalledWith('room-1', 'token-1')
      expect(listRoomCharacters).toHaveBeenCalledWith('room-1', 'token-1')
      expect(listRoomCharacters).toHaveBeenCalledWith('room-1', 'token-1', { archived: true })
      expect(listRoomDraftCount).toHaveBeenCalledWith('room-1', 'token-1')

      expect(inventory.campaignCount).toBe(2)
      expect(inventory.characterCount).toBe(2)
      expect(inventory.draftCount).toBe(3)
    })

    it('propagates failure when any listing request fails', async () => {
      vi.mocked(listCampaigns).mockRejectedValue(new Error('network error'))
      vi.mocked(listRoomCharacters).mockResolvedValue([])
      vi.mocked(listRoomDraftCount).mockResolvedValue(0)

      await expect(fetchDeleteRoomInventory('room-1', 'token-1')).rejects.toThrow('network error')
    })
  })

  describe('render tests', () => {
    it('(1) opened panel with 2 campaigns, 1 active + 1 archived character, 3 drafts renders summary and both name lists with archived suffix', () => {
      const inventory = buildDeleteInventory(
        mockCampaigns,
        mockActiveCharacters,
        mockArchivedCharacters,
        3,
      )

      const htmlEn = renderDeleteSection({ inventory }, 'en')
      const copyEn = roomCopy('en')

      expect(htmlEn).toContain('2 Campaigns · 2 Characters · 3 Drafts')
      expect(htmlEn).toContain(copyEn.deleteRoomInventoryCampaigns)
      expect(htmlEn).toContain('Lost Mine of Phandelver')
      expect(htmlEn).toContain('Waterdeep: Dragon Heist')
      expect(htmlEn).toContain(copyEn.deleteRoomInventoryCharacters)
      expect(htmlEn).toContain('Mira (Wizard 1)')
      expect(htmlEn).toContain('Brog (Barbarian 2) (archived)')

      const htmlZh = renderDeleteSection({ inventory }, 'zh-TW')
      const copyZh = roomCopy('zh-TW')

      expect(htmlZh).toContain('2 個 Campaign · 2 個角色 · 3 個草稿')
      expect(htmlZh).toContain(copyZh.deleteRoomInventoryCampaigns)
      expect(htmlZh).toContain(copyZh.deleteRoomInventoryCharacters)
      expect(htmlZh).toContain('Brog (Barbarian 2)（已封存）')
    })

    it('(2) empty inventory renders the summary with zeros and no list headings', () => {
      const inventory = buildDeleteInventory([], [], [], 0)

      const htmlEn = renderDeleteSection({ inventory }, 'en')
      const copyEn = roomCopy('en')

      expect(htmlEn).toContain('0 Campaigns · 0 Characters · 0 Drafts')
      expect(htmlEn).not.toContain(`<strong>${copyEn.deleteRoomInventoryCampaigns}</strong>`)
      expect(htmlEn).not.toContain(`<strong>${copyEn.deleteRoomInventoryCharacters}</strong>`)

      const htmlZh = renderDeleteSection({ inventory }, 'zh-TW')
      const copyZh = roomCopy('zh-TW')

      expect(htmlZh).toContain('0 個 Campaign · 0 個角色 · 0 個草稿')
      expect(htmlZh).not.toContain(`<strong>${copyZh.deleteRoomInventoryCampaigns}</strong>`)
      expect(htmlZh).not.toContain(`<strong>${copyZh.deleteRoomInventoryCharacters}</strong>`)
    })

    it('(3) listing failure renders deleteRoomInventoryError and the Delete button is not disabled by it', () => {
      const copyEn = roomCopy('en')
      const html = renderDeleteSection({
        inventory: null,
        inventoryError: true,
        deleteConfirmation: 'Sunday Table',
        roomName: 'Sunday Table',
      })

      expect(html).toContain('class="error-banner"')
      expect(html).toContain(copyEn.deleteRoomInventoryError)

      // The Delete button must NOT have disabled attribute when confirmation matches room name
      expect(html).toMatch(/<button[^>]*class="button danger"[^>]*>Delete Room<\/button>/)
      expect(html).not.toMatch(/<button[^>]*class="button danger"[^>]*disabled[^>]*>Delete Room<\/button>/)
    })

    it('(4) member authority renders no delete panel', () => {
      const htmlMember = renderDeleteSection({ isOwner: false })
      expect(htmlMember).toBe('')

      const copy = roomCopy('en')
      expect(htmlMember).not.toContain(copy.deleteRoomTitle)
      expect(htmlMember).not.toContain(copy.deleteRoomAction)
    })
  })
})
