import { useEffect, useMemo, useState } from 'react'

import { fetchMcpPublicOrigin } from '../../api/aiControllers'
import type { Locale } from '../../i18n/locale'

export type AIJoinRole = 'dm' | 'player'

export type AIJoinKitUiCopy = {
  aiJoinKitTitle: string
  aiJoinKitHint: string
  aiJoinKitCopy: string
  aiJoinKitCopied: string
  aiJoinKitDownload: string
}

type JoinKitInput = {
  origin: string
  remoteOrigin: string | null
  token: string
  role: AIJoinRole
  locale: Locale
  expiresAt?: string | null
}

const templateCopy = {
  'zh-TW': {
    copyFailed: '無法自動複製 Join Kit，請手動選取文字。',
    localUrl: 'URL（本機）',
    remoteUrl: 'URL（公網）',
    localGuide: 'Guide（本機）',
    remoteGuide: 'Guide（公網）',
    role: 'Role',
    token: 'Token',
    expires: 'Expires',
    expiresFallback: '直到 Session 結束或被撤銷',
    first: '連上後第一步一律呼叫 get_session_context。',
    which: '在這台機器上跑的 AI 用「本機」URL；網頁版 chat 與機器外的 AI 用「公網」URL。',
    safety: '安全：此 token 只顯示這一次；勿轉傳；用完請 Owner／DM 在網站撤銷。',
    refresh: 'Session 開始前後工具清單相同，start_session 後不需 Refresh。換 Role／Seat 必須重新授權；之後工具仍是舊清單就 Refresh／重新掃描 connector 並開新對話。',
    web: 'ChatGPT Web：新增 Adventure Table connector，URL 填「公網」URL；OAuth 要求憑證時貼上此 token。',
    client: '有 MCP client：HTTP transport，header Authorization: Bearer {token}。',
    http: '有 shell 或可對外連網 code execution、但沒有 MCP client：先讀 Guide，再依說明呼叫工具。網頁版 chat 請走 connector。',
    noRemote: '尚未設定公網入口（ADVENTURE_TABLE_MCP_PUBLIC_ORIGIN）；網頁版 chat 與機器外的 AI 目前連不進來，只有「本機」URL 可用。',
  },
  en: {
    copyFailed: 'Could not copy the Join Kit automatically. Select and copy the text manually.',
    localUrl: 'URL (local)',
    remoteUrl: 'URL (remote)',
    localGuide: 'Guide (local)',
    remoteGuide: 'Guide (remote)',
    role: 'Role',
    token: 'Token',
    expires: 'Expires',
    expiresFallback: 'until the Session ends or the grant is revoked',
    first: 'After connecting, always call get_session_context first.',
    which: 'An AI running on this machine uses the local URL; web chat and any AI outside this machine use the remote URL.',
    safety: 'Security: this token is shown only once; do not forward it; ask the Owner/DM to revoke it when finished.',
    refresh: 'The tool list is the same before and after the Session starts; no Refresh is needed after start_session. Changing Role/Seat requires a new authorization; if tools are still stale afterwards, Refresh/rescan the connector and open a new chat.',
    web: 'ChatGPT Web: add the Adventure Table connector using the remote URL; paste this token when OAuth asks for the credential.',
    client: 'With an MCP client: use HTTP transport with header Authorization: Bearer {token}.',
    http: 'With shell or outbound-network code execution but no MCP client: read the Guide, then call tools as documented. Web chat should use the connector.',
    noRemote: 'No public entry point is configured (ADVENTURE_TABLE_MCP_PUBLIC_ORIGIN); web chat and AIs outside this machine cannot connect yet, only the local URL works.',
  },
} as const

function normalizedOrigin(origin: string) {
  return origin.replace(/\/$/, '')
}

export function buildAIJoinKit({ origin, remoteOrigin, token, role, locale, expiresAt }: JoinKitInput) {
  const copy = templateCopy[locale]
  const local = normalizedOrigin(origin)
  const remote = remoteOrigin ? normalizedOrigin(remoteOrigin) : null
  const guidePath = `/mcp/guide?locale=${locale}`
  const displayRole = role === 'dm' ? 'DM' : 'Player'
  const lines = [
    'Adventure Table — AI Join Kit',
    '==============================',
    `${copy.localUrl}: ${local}/mcp`,
    ...(remote ? [`${copy.remoteUrl}: ${remote}/mcp`] : []),
    `${copy.token}: ${token}`,
    `${copy.role}: ${displayRole}`,
    `${copy.expires}: ${expiresAt ?? copy.expiresFallback}`,
    `${copy.localGuide}: ${local}${guidePath}`,
    ...(remote ? [`${copy.remoteGuide}: ${remote}${guidePath}`] : []),
    '',
    copy.first,
    copy.which,
    copy.refresh,
    '',
    `1. ${copy.web}`,
    `2. ${copy.client.replace('{token}', token)}`,
    `3. ${copy.http}`,
    '',
    copy.safety,
  ]
  if (!remote) lines.push('', copy.noRemote)
  return lines.join('\n')
}

export function aiJoinKitFilename(role: AIJoinRole, date = new Date()) {
  const stamp = date.toISOString().slice(0, 10).replaceAll('-', '')
  return `adventure-table-ai-${role}-${stamp}.txt`
}

type AIJoinKitProps = Omit<JoinKitInput, 'remoteOrigin'> & { uiCopy: AIJoinKitUiCopy }

export function AIJoinKit({ origin, token, role, locale, expiresAt, uiCopy }: AIJoinKitProps) {
  const template = templateCopy[locale]
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState(false)
  // undefined while the public origin is still loading; null when none is configured.
  const [remoteOrigin, setRemoteOrigin] = useState<string | null | undefined>(undefined)

  useEffect(() => {
    let cancelled = false
    fetchMcpPublicOrigin()
      .then((value) => {
        if (!cancelled) setRemoteOrigin(value)
      })
      .catch(() => {
        if (!cancelled) setRemoteOrigin(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const kit = useMemo(
    () =>
      remoteOrigin === undefined
        ? null
        : buildAIJoinKit({ origin, remoteOrigin, token, role, locale, expiresAt }),
    [origin, remoteOrigin, token, role, locale, expiresAt],
  )

  if (kit === null) return null

  const copyKit = async () => {
    try {
      await navigator.clipboard.writeText(kit)
      setCopyError(false)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2500)
    } catch {
      setCopyError(true)
    }
  }

  const downloadKit = () => {
    const blob = new Blob([kit], { type: 'text/plain;charset=utf-8' })
    const href = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = href
    anchor.download = aiJoinKitFilename(role)
    anchor.click()
    URL.revokeObjectURL(href)
  }

  return (
    <div className="ai-join-kit" data-ai-join-kit={role}>
      <strong>{uiCopy.aiJoinKitTitle}</strong>
      <p>{uiCopy.aiJoinKitHint}</p>
      <pre className="ai-join-kit__text">{kit}</pre>
      <div className="workshop-card__split-actions">
        <button className="button secondary" type="button" onClick={() => void copyKit()}>{uiCopy.aiJoinKitCopy}</button>
        <button className="button secondary" type="button" onClick={downloadKit}>{uiCopy.aiJoinKitDownload}</button>
        {copied ? <span className="token-copy-feedback" role="status">{uiCopy.aiJoinKitCopied}</span> : null}
      </div>
      {copyError ? <div className="error-banner" role="alert">{template.copyFailed}</div> : null}
    </div>
  )
}
