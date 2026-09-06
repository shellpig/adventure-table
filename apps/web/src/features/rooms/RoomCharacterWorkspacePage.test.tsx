import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { LocaleProvider } from '../../i18n/LocaleProvider'
import { RoomCharacterWorkspacePage } from './RoomCharacterWorkspacePage'
import { recentRoomForId } from './roomStorage'

vi.mock('./roomStorage', async () => {
  const actual = await vi.importActual<typeof import('./roomStorage')>('./roomStorage')
  return { ...actual, recentRoomForId: vi.fn() }
})

vi.mock('../character-builder/CharacterWorkshopPage', () => ({
  CharacterWorkshopPage: ({ allowPermanentDelete }: { allowPermanentDelete?: boolean }) => (
    <div data-testid="workshop-delete-authority">{String(allowPermanentDelete)}</div>
  ),
}))

vi.mock('../../api/roomCharacters', () => ({
  getLegacyCharacterDataStatus: vi.fn().mockResolvedValue({
    character_count: 0,
    draft_count: 0,
    available: false,
  }),
  claimLegacyCharacterData: vi.fn(),
}))

const ROOM_ID = '22222222-2222-4222-8222-222222222222'

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <LocaleProvider>
        <RoomCharacterWorkspacePage roomId={ROOM_ID} />
      </LocaleProvider>
    </QueryClientProvider>,
  )
}

describe('Room Character workspace authority', () => {
  beforeEach(() => {
    vi.mocked(recentRoomForId).mockReset()
  })

  it('passes permanent-delete authority only to the owner', () => {
    vi.mocked(recentRoomForId).mockReturnValue({
      id: ROOM_ID,
      name: 'Owner Room',
      code: '0123456789',
      authority: 'owner',
      accessToken: 'owner-token',
    })
    renderPage()
    expect(screen.getByTestId('workshop-delete-authority')).toHaveTextContent('true')
  })

  it.each(['member', 'dm'] as const)('does not render permanent-delete authority for %s', (authority) => {
    vi.mocked(recentRoomForId).mockReturnValue({
      id: ROOM_ID,
      name: 'Shared Room',
      code: '0123456789',
      authority,
      accessToken: `${authority}-token`,
    })
    renderPage()
    expect(screen.getByTestId('workshop-delete-authority')).toHaveTextContent('false')
  })
})
