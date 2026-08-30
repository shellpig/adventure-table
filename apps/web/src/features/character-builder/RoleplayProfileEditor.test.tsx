import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'

import type { BuilderView } from '../../api/characterBuilder'
import { RoleplayProfileEditor } from './RoleplayProfileEditor'

const view = {
  draft: {
    id: 'draft-1',
    mode: 'create',
    revision: 1,
    draft_payload: {
      background_selection: { reference_id: 'phb2014:background:soldier' },
      roleplay_profile: {},
    },
    created_at: '2026-08-30T00:00:00Z',
    updated_at: '2026-08-30T00:00:00Z',
  },
  resolved_summary: {
    selected_reference_count: 1,
    choice_selection_count: 0,
    grants: [],
    ability_scores: [],
    progression: [],
    spellcasting_profiles: [],
    spell_resource_pools: [],
  },
  choices: [],
  validation: { issues: [], can_confirm: false, non_standard_count: 0 },
} as BuilderView

function wrapper(children: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

test('background suggestions are optional and manual text persists through onSave', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true,
    json: async () => ({
      data: {
        roleplay_suggestions: {
          personality_traits: ['Always polite and respectful.'],
          ideals: [], bonds: [], flaws: [],
        },
      },
    }),
  })))
  const onSave = vi.fn()
  render(wrapper(<RoleplayProfileEditor view={view} disabled={false} onSave={onSave} />))

  expect(screen.getByText('Roleplay Profile')).toBeInTheDocument()
  const suggestion = await screen.findByRole('button', { name: /Always polite and respectful/ })
  fireEvent.click(suggestion)
  expect(onSave).toHaveBeenCalledWith({
    roleplay_profile: { personality_traits: ['Always polite and respectful.'] },
  })

  const personality = screen.getByLabelText('Personality Traits')
  fireEvent.change(personality, { target: { value: 'My own custom trait.' } })
  fireEvent.blur(personality)
  await waitFor(() => expect(onSave).toHaveBeenLastCalledWith({
    roleplay_profile: { personality_traits: ['My own custom trait.'] },
  }))

  vi.unstubAllGlobals()
})
