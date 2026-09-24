import { expect, test } from './support/roomTest'
import {
  addPlayerSeat,
  addSeat,
  createCampaign,
  enterAsMember,
  importCharacter,
  json,
  openSessionAs,
  responseJson,
  restartE2EServer,
  startSession,
  type Lobby,
} from './support/quickCombat'

type RuntimeEntry = {
  id: string
  kind: string
  title: string | null
  body: string | null
  visibility: string
  dm_notes?: string | null
  revision: number
  [key: string]: unknown
}

type RuntimeContext = {
  current_situation: string | null
  current_adventure_scene_entry_id: string | null
  current_runtime_scene_entry_id: string | null
  revision: number
}

type AdventureImport = {
  id: string
  room_id: string
  name: string
  status: string
  revision: number
}

type AdventureImportSource = {
  id: string
  import_id: string
  source_kind: string
  text_length: number
}

type DraftEntry = {
  entry_id: string
  entry_kind: string
  payload: Record<string, unknown>
  title?: string | null
  body?: string | null
  visibility?: string
  provenance?: string
  source_ref?: { source_id: string; locator?: string | null } | null
  review_status?: string
  asset_ids?: string[]
}

type DraftQuestion = {
  question_id: string
  message: string
  entry_id?: string | null
  answer?: string | null
}

type DraftWarning = {
  warning_id: string
  level: string
  code: string
  message: string
  entry_id?: string | null
  source_id?: string | null
  resolved: boolean
  resolution?: string | null
}

type AdventureImportDraft = {
  import_id: string
  draft: {
    schema_version: number
    entries: DraftEntry[]
    questions: DraftQuestion[]
  }
  warnings: DraftWarning[]
  revision: number
}

test('P6-G G3a: real Docker PostgreSQL restart continuity across active Session, runtime entries, context, import draft, and next session', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(300_000)
  const { roomId } = roomContext

  // 1. Fresh Room & Campaign with DM Seat and Player Seat
  const campaign = await createCampaign(request, roomId, 'P6-G Restart Campaign')

  const lobby = await json<Lobby>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`),
  )
  expect(lobby.caller_access_session_id).not.toBeNull()
  await addSeat(request, roomId, campaign.id, 'dm', lobby.caller_access_session_id!, 'P6-G DM')

  const playerGrant = await enterAsMember(request, roomContext, 'P6-G Player')
  const character = await importCharacter(request)
  await addPlayerSeat(
    request,
    roomId,
    campaign.id,
    character,
    playerGrant.access_session_id,
    'P6-G Player',
  )

  // 2. Start Session 1 through official UI
  const sessionId = await startSession(page, roomId, campaign.id)
  const sessionUrl = `/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const activePrefix = `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`

  const player = await openSessionAs(browser, playerGrant, roomContext, sessionUrl)

  try {
    // Verify initial layout & role-based separation
    const dmWorldPanel = page.locator('.session-world-panel')
    await expect(dmWorldPanel).toBeVisible()
    await expect(page.locator('.session-journal-panel')).toHaveCount(0)

    const playerJournalPanel = player.page.locator('.session-journal-panel')
    await expect(playerJournalPanel).toBeVisible()
    await expect(player.page.locator('.session-world-panel')).toHaveCount(0)

    // 3. Persist Runtime entries (including DM-only secret and public fact/scene)
    const PUBLIC_FACT_TITLE = 'Ruined Watchtower'
    const PUBLIC_FACT_BODY = 'The ancient stone watchtower overlooks the misty valley.'
    const publicFact = await json<RuntimeEntry>(
      await request.post(`${activePrefix}/runtime/entries`, {
        data: {
          idempotency_key: `p6g-restart-fact-${sessionId}`,
          kind: 'fact',
          title: PUBLIC_FACT_TITLE,
          body: PUBLIC_FACT_BODY,
          state: { kind: 'fact' },
          visibility: 'public',
          character_recipient_ids: [],
          dm_notes: null,
          needs_review: false,
          provenance_json: null,
        },
      }),
    )

    const DM_SECRET_TITLE = 'Hidden Catacombs Entrance'
    const DM_SECRET_BODY = 'A concealed trapdoor lies under the collapsed hearth.'
    const DM_SECRET_NOTES = 'Trapped with poison darts: DC 15 Perception to spot.'
    const dmSecret = await json<RuntimeEntry>(
      await request.post(`${activePrefix}/runtime/entries`, {
        data: {
          idempotency_key: `p6g-restart-secret-${sessionId}`,
          kind: 'secret',
          title: DM_SECRET_TITLE,
          body: DM_SECRET_BODY,
          state: { kind: 'secret' },
          visibility: 'dm_only',
          character_recipient_ids: [],
          dm_notes: DM_SECRET_NOTES,
          needs_review: false,
          provenance_json: null,
        },
      }),
    )

    const RUNTIME_SCENE_TITLE = 'Watchtower Courtyard'
    const RUNTIME_SCENE_BODY = 'Broken columns scattered across overgrown flagstones.'
    const runtimeScene = await json<RuntimeEntry>(
      await request.post(`${activePrefix}/runtime/entries`, {
        data: {
          idempotency_key: `p6g-restart-scene-${sessionId}`,
          kind: 'scene',
          title: RUNTIME_SCENE_TITLE,
          body: RUNTIME_SCENE_BODY,
          state: { kind: 'scene' },
          visibility: 'public',
          character_recipient_ids: [],
          dm_notes: null,
          needs_review: false,
          provenance_json: null,
        },
      }),
    )

    // 4. Persist Current Context (Situation + Scene)
    const CURRENT_SITUATION_TEXT = 'The party inspects the crumbling watchtower walls.'
    const initialContext = await json<RuntimeContext>(
      await request.get(`${activePrefix}/runtime/context`),
    )
    const updatedContext = await json<RuntimeContext>(
      await request.patch(`${activePrefix}/runtime/context`, {
        data: {
          idempotency_key: `p6g-restart-context-${sessionId}`,
          expected_revision: initialContext.revision,
          current_runtime_scene_entry_id: runtimeScene.id,
          current_situation: CURRENT_SITUATION_TEXT,
        },
      }),
    )
    expect(updatedContext.current_situation).toBe(CURRENT_SITUATION_TEXT)
    expect(updatedContext.current_runtime_scene_entry_id).toBe(runtimeScene.id)
    expect(updatedContext.revision).toBe(initialContext.revision + 1)

    // 5. Persist a mutable Import Draft with entry, warning, question, and known revision
    const importItem = await json<AdventureImport>(
      await request.post(`/api/rooms/${roomId}/adventure-imports`, {
        data: { name: 'P6-G Restart Crypt Import' },
      }),
    )
    expect(importItem.status).toBe('source')

    const source = await json<AdventureImportSource>(
      await request.post(`/api/rooms/${roomId}/adventure-imports/${importItem.id}/sources`, {
        data: {
          source_kind: 'paste',
          text: 'The sunken crypt of King Gerald lies beneath black water. An iron door blocks the descent.',
        },
      }),
    )
    expect(source.source_kind).toBe('paste')

    const initialDraft = await json<AdventureImportDraft>(
      await request.get(`/api/rooms/${roomId}/adventure-imports/${importItem.id}/draft`),
    )

    const updatedDraft = await json<AdventureImportDraft>(
      await request.put(`/api/rooms/${roomId}/adventure-imports/${importItem.id}/draft`, {
        data: {
          draft: {
            schema_version: 1,
            entries: [
              {
                entry_id: 'crypt_descent_scene',
                entry_kind: 'scene',
                payload: {
                  kind: 'scene',
                  read_aloud: 'Cold water drips from the arched ceiling of the crypt staircase.',
                },
                title: 'Crypt Descent',
                body: 'A steep flight of stone stairs descends into stagnant water.',
                visibility: 'dm_only',
                provenance: 'source_document',
                source_ref: {
                  source_id: source.id,
                  locator: 'offset:0',
                },
                review_status: 'pending',
                asset_ids: [],
              },
            ],
            questions: [
              {
                question_id: 'q_water_depth',
                message: 'How deep is the black water flooding the crypt stairs?',
                entry_id: 'crypt_descent_scene',
                answer: null,
              },
            ],
          },
          warnings: [
            {
              warning_id: 'w_door_athletics',
              level: 'warning',
              code: 'unverified_rule_value',
              message: 'Iron door DC requires verification against campaign level.',
              entry_id: 'crypt_descent_scene',
              source_id: source.id,
              resolved: false,
              resolution: null,
            },
          ],
          expected_revision: initialDraft.revision,
        },
      }),
    )
    expect(updatedDraft.revision).toBe(initialDraft.revision + 1)
    expect(updatedDraft.draft.entries).toHaveLength(1)
    expect(updatedDraft.draft.questions).toHaveLength(1)
    expect(updatedDraft.warnings).toHaveLength(1)

    // 6. Capture pre-restart state & verify pre-restart projections
    const capturedContextRevision = updatedContext.revision
    const capturedDraftRevision = updatedDraft.revision
    const capturedFactRevision = publicFact.revision
    const capturedSecretRevision = dmSecret.revision
    const capturedSceneRevision = runtimeScene.revision

    // DM UI pre-restart projection
    await expect(dmWorldPanel).toContainText(PUBLIC_FACT_TITLE)
    await expect(dmWorldPanel).toContainText(DM_SECRET_TITLE)
    await expect(dmWorldPanel).toContainText(RUNTIME_SCENE_TITLE)
    const dmContextCard = dmWorldPanel.locator('.runtime-context-card')
    await expect(dmContextCard).toContainText(CURRENT_SITUATION_TEXT)

    // Player UI pre-restart projection
    await expect(playerJournalPanel).toContainText(PUBLIC_FACT_BODY)
    await expect(player.page.locator('body')).not.toContainText(DM_SECRET_NOTES)
    await expect(player.page.locator('body')).not.toContainText(DM_SECRET_TITLE)

    // Player REST direct-read assertions before restart
    const prePlayerContextResp = await request.get(`${activePrefix}/runtime/context`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    })
    expect(prePlayerContextResp.status()).toBe(403)

    const prePlayerImportsResp = await request.get(`/api/rooms/${roomId}/adventure-imports`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    })
    expect(prePlayerImportsResp.status()).toBe(403)

    const prePlayerDraftResp = await request.get(
      `/api/rooms/${roomId}/adventure-imports/${importItem.id}/draft`,
      { headers: { Authorization: `Bearer ${playerGrant.access_token}` } },
    )
    expect(prePlayerDraftResp.status()).toBe(403)

    const prePlayerSourcesResp = await request.get(
      `/api/rooms/${roomId}/adventure-imports/${importItem.id}/sources`,
      { headers: { Authorization: `Bearer ${playerGrant.access_token}` } },
    )
    expect(prePlayerSourcesResp.status()).toBe(403)

    // 7. Restart ONLY server-e2e container
    await restartE2EServer(request)

    // 8. Reconnect DM and Player pages
    await page.reload()
    await expect(page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
    await expect(dmWorldPanel).toBeVisible()

    await player.page.reload()
    await expect(player.page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
    await expect(playerJournalPanel).toBeVisible()

    // 9. Verify all persisted data/revisions/visibility unchanged after restart
    // Context check
    const postRestartContext = await json<RuntimeContext>(
      await request.get(`${activePrefix}/runtime/context`),
    )
    expect(postRestartContext.revision).toBe(capturedContextRevision)
    expect(postRestartContext.current_situation).toBe(CURRENT_SITUATION_TEXT)
    expect(postRestartContext.current_runtime_scene_entry_id).toBe(runtimeScene.id)

    // Runtime entries check
    const postRestartDmEntries = await json<RuntimeEntry[]>(
      await request.get(`${activePrefix}/runtime/entries`),
    )
    const postFact = postRestartDmEntries.find((e) => e.id === publicFact.id)
    expect(postFact).toBeDefined()
    expect(postFact!.revision).toBe(capturedFactRevision)
    expect(postFact!.body).toBe(PUBLIC_FACT_BODY)
    expect(postFact!.visibility).toBe('public')

    const postSecret = postRestartDmEntries.find((e) => e.id === dmSecret.id)
    expect(postSecret).toBeDefined()
    expect(postSecret!.revision).toBe(capturedSecretRevision)
    expect(postSecret!.visibility).toBe('dm_only')
    expect(postSecret!.dm_notes).toBe(DM_SECRET_NOTES)

    const postScene = postRestartDmEntries.find((e) => e.id === runtimeScene.id)
    expect(postScene).toBeDefined()
    expect(postScene!.revision).toBe(capturedSceneRevision)
    expect(postScene!.visibility).toBe('public')

    // Import Draft check
    const postRestartDraft = await json<AdventureImportDraft>(
      await request.get(`/api/rooms/${roomId}/adventure-imports/${importItem.id}/draft`),
    )
    expect(postRestartDraft.revision).toBe(capturedDraftRevision)
    expect(postRestartDraft.draft).toEqual(updatedDraft.draft)
    expect(postRestartDraft.warnings).toEqual(updatedDraft.warnings)

    // Verify Draft remains mutable after restart
    const mutatedDraft = await json<AdventureImportDraft>(
      await request.put(`/api/rooms/${roomId}/adventure-imports/${importItem.id}/draft`, {
        data: {
          draft: {
            ...postRestartDraft.draft,
            questions: [
              {
                question_id: 'q_water_depth',
                message: 'How deep is the black water flooding the crypt stairs?',
                entry_id: 'crypt_descent_scene',
                answer: 'Waist-deep cold water (about 3 feet).',
              },
            ],
          },
          warnings: postRestartDraft.warnings,
          expected_revision: postRestartDraft.revision,
        },
      }),
    )
    expect(mutatedDraft.revision).toBe(postRestartDraft.revision + 1)
    expect(mutatedDraft.draft.questions[0].answer).toBe('Waist-deep cold water (about 3 feet).')

    // UI projections post-restart
    await expect(dmWorldPanel).toContainText(PUBLIC_FACT_TITLE)
    await expect(dmWorldPanel).toContainText(DM_SECRET_TITLE)
    await expect(dmWorldPanel).toContainText(CURRENT_SITUATION_TEXT)
    await expect(playerJournalPanel).toContainText(PUBLIC_FACT_BODY)
    await expect(player.page.locator('body')).not.toContainText(DM_SECRET_NOTES)
    await expect(player.page.locator('body')).not.toContainText(DM_SECRET_TITLE)

    // Player direct-read assertions post-restart
    const postPlayerContextResp = await request.get(`${activePrefix}/runtime/context`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    })
    expect(postPlayerContextResp.status()).toBe(403)

    const postPlayerImportsResp = await request.get(`/api/rooms/${roomId}/adventure-imports`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    })
    expect(postPlayerImportsResp.status()).toBe(403)

    const postPlayerDraftResp = await request.get(
      `/api/rooms/${roomId}/adventure-imports/${importItem.id}/draft`,
      { headers: { Authorization: `Bearer ${playerGrant.access_token}` } },
    )
    expect(postPlayerDraftResp.status()).toBe(403)

    const postPlayerSourcesResp = await request.get(
      `/api/rooms/${roomId}/adventure-imports/${importItem.id}/sources`,
      { headers: { Authorization: `Bearer ${playerGrant.access_token}` } },
    )
    expect(postPlayerSourcesResp.status()).toBe(403)

    const postPlayerChunkResp = await request.get(
      `/api/rooms/${roomId}/adventure-imports/${importItem.id}/sources/${source.id}/chunk?offset=0&limit=100`,
      { headers: { Authorization: `Bearer ${playerGrant.access_token}` } },
    )
    expect(postPlayerChunkResp.status()).toBe(403)

    // 10. End Session 1 through official UI
    page.once('dialog', (dialog) => dialog.accept())
    const endSessionPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().includes(`/sessions/${sessionId}/end`),
    )
    await page.getByRole('button', { name: 'End Session' }).click()
    await responseJson(await endSessionPromise)
    await expect(page.getByText('Ended', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'End Session' })).toHaveCount(0)

    // 11. Return to Lobby and start Session 2
    await page.getByRole('link', { name: 'Back to Lobby' }).click()
    await expect(page.getByRole('heading', { name: 'Lobby & Seats', level: 1 })).toBeVisible()

    await page.getByRole('button', { name: 'Start Session' }).click()
    await expect(page).toHaveURL(
      new RegExp(`/rooms/${roomId}/campaigns/${campaign.id}/sessions/[0-9a-fA-F-]{36}/?$`),
    )
    await expect(page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()

    const nextSessionMatch = page.url().match(/\/sessions\/([0-9a-fA-F-]{36})/)
    expect(nextSessionMatch).not.toBeNull()
    const nextSessionId = nextSessionMatch![1]
    expect(nextSessionId).not.toBe(sessionId)
    const nextSessionUrl = `/rooms/${roomId}/campaigns/${campaign.id}/sessions/${nextSessionId}`
    const nextActivePrefix = `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${nextSessionId}`

    // 12. Verify Campaign Runtime / context continuity in Session 2
    const session2Context = await json<RuntimeContext>(
      await request.get(`${nextActivePrefix}/runtime/context`),
    )
    expect(session2Context.current_situation).toBe(CURRENT_SITUATION_TEXT)
    expect(session2Context.current_runtime_scene_entry_id).toBe(runtimeScene.id)

    const session2DmEntries = await json<RuntimeEntry[]>(
      await request.get(`${nextActivePrefix}/runtime/entries`),
    )
    const s2Fact = session2DmEntries.find((e) => e.id === publicFact.id)
    expect(s2Fact).toBeDefined()
    expect(s2Fact!.body).toBe(PUBLIC_FACT_BODY)

    const s2Secret = session2DmEntries.find((e) => e.id === dmSecret.id)
    expect(s2Secret).toBeDefined()
    expect(s2Secret!.visibility).toBe('dm_only')
    expect(s2Secret!.dm_notes).toBe(DM_SECRET_NOTES)

    // DM UI in Session 2
    const nextWorldPanel = page.locator('.session-world-panel')
    await expect(nextWorldPanel).toBeVisible()
    await expect(nextWorldPanel).toContainText(PUBLIC_FACT_TITLE)
    await expect(nextWorldPanel).toContainText(DM_SECRET_TITLE)
    await expect(nextWorldPanel).toContainText(CURRENT_SITUATION_TEXT)

    // 13. Connect Player to Session 2 and verify secrecy filtering
    await player.page.goto(nextSessionUrl)
    await expect(player.page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
    const nextJournalPanel = player.page.locator('.session-journal-panel')
    await expect(nextJournalPanel).toBeVisible()
    await expect(player.page.locator('.session-world-panel')).toHaveCount(0)

    // Player sees public fact in journal
    await expect(nextJournalPanel).toContainText(PUBLIC_FACT_BODY)

    // Player does NOT see DM secret or DM notes in DOM
    await expect(player.page.locator('body')).not.toContainText(DM_SECRET_NOTES)
    await expect(player.page.locator('body')).not.toContainText(DM_SECRET_TITLE)

    // Player REST projection has secrets filtered
    const session2PlayerEntries = await json<RuntimeEntry[]>(
      await request.get(`${nextActivePrefix}/runtime/entries`, {
        headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      }),
    )
    expect(session2PlayerEntries.some((e) => e.title === PUBLIC_FACT_TITLE)).toBe(true)
    expect(session2PlayerEntries.some((e) => e.title === DM_SECRET_TITLE)).toBe(false)
    for (const entry of session2PlayerEntries) {
      expect(entry).not.toHaveProperty('dm_notes')
      expect(entry).not.toHaveProperty('character_recipient_ids')
      expect(entry).not.toHaveProperty('needs_review')
      expect(entry).not.toHaveProperty('provenance_json')
    }

    // Player cannot direct-read context or draft in Session 2
    const s2PlayerContextResp = await request.get(`${nextActivePrefix}/runtime/context`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    })
    expect(s2PlayerContextResp.status()).toBe(403)

    const s2PlayerDraftResp = await request.get(
      `/api/rooms/${roomId}/adventure-imports/${importItem.id}/draft`,
      { headers: { Authorization: `Bearer ${playerGrant.access_token}` } },
    )
    expect(s2PlayerDraftResp.status()).toBe(403)
  } finally {
    await player.context.close()
  }
})
