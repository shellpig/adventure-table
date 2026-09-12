import { useMemo, useState } from 'react'

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
  token: string
  role: AIJoinRole
  locale: Locale
  expiresAt?: string | null
}

const templateCopy = {
  'zh-TW': {
    copyFailed: '無法自動複製 Join Kit，請手動選取文字。',
    loopback: '提醒：目前 URL 是 loopback 位址；遠端 AI 必須能連到這台機器，否則請改用可公開存取的 origin。',
    role: 'Role',
    endpoint: 'URL',
    guide: 'Guide',
    token: 'Token',
    expires: 'Expires',
    expiresFallback: '直到 Session 結束或被撤銷',
    first: '連上後第一步一律呼叫 get_session_context。',
    safety: '安全：此 token 只顯示這一次；勿轉傳；用完請 Owner／DM 在網站撤銷。',
    refresh: '若 Session 開始或改用不同 Role／Seat 後工具仍是舊清單，請 Refresh／重新掃描 connector；換 Role／Seat 必須重新授權。',
    web: 'ChatGPT Web：新增 Adventure Table connector，URL 使用上方 URL；OAuth 要求憑證時貼上此 token。',
    client: '有 MCP client：HTTP transport，header Authorization: Bearer {token}。',
    http: '有 shell 或可對外連網 code execution、但沒有 MCP client：先讀上方 Guide，再依說明呼叫工具。網頁版 chat 請走 connector。',
  },
  en: {
    copyFailed: 'Could not copy the Join Kit automatically. Select and copy the text manually.',
    loopback: 'Note: this URL uses a loopback address. A remote AI must be able to reach this machine; otherwise use a publicly reachable origin.',
    role: 'Role',
    endpoint: 'URL',
    guide: 'Guide',
    token: 'Token',
    expires: 'Expires',
    expiresFallback: 'until the Session ends or the grant is revoked',
    first: 'After connecting, always call get_session_context first.',
    safety: 'Security: this token is shown only once; do not forward it; ask the Owner/DM to revoke it when finished.',
    refresh: 'If tools are stale after Session start or a Role/Seat change, Refresh/rescan the connector. Changing Role/Seat requires a new authorization.',
    web: 'ChatGPT Web: add the Adventure Table connector using the URL above; paste this token when OAuth asks for the credential.',
    client: 'With an MCP client: use HTTP transport with header Authorization: Bearer {token}.',
    http: 'With shell or outbound-network code execution but no MCP client: read the Guide above, then call tools as documented. Web chat should use the connector.',
  },
} as const

function normalizedOrigin(origin: string) {
  return origin.replace(/\/$/, '')
}

export function isLoopbackOrigin(origin: string) {
  try {
    const hostname = new URL(origin).hostname
    return (
      hostname === 'localhost' ||
      hostname === '::1' ||
      hostname === '[::1]' ||
      hostname.startsWith('127.')
    )
  } catch {
    return false
  }
}

export function buildAIJoinKit({ origin, token, role, locale, expiresAt }: JoinKitInput) {
  const copy = templateCopy[locale]
  const base = normalizedOrigin(origin)
  const endpoint = `${base}/mcp`
  const guide = `${base}/mcp/guide?locale=${locale}`
  const displayRole = role === 'dm' ? 'DM' : 'Player'
  const lines = [
    'Adventure Table — AI Join Kit',
    '==============================',
    `${copy.endpoint}: ${endpoint}`,
    `${copy.token}: ${token}`,
    `${copy.role}: ${displayRole}`,
    `${copy.expires}: ${expiresAt ?? copy.expiresFallback}`,
    `${copy.guide}: ${guide}`,
    '',
    copy.first,
    copy.refresh,
    '',
    `1. ${copy.web}`,
    `2. ${copy.client.replace('{token}', token)}`,
    `3. ${copy.http}`,
    '',
    copy.safety,
  ]
  if (isLoopbackOrigin(base)) lines.push('', copy.loopback)
  return lines.join('\n')
}

export function aiJoinKitFilename(role: AIJoinRole, date = new Date()) {
  const stamp = date.toISOString().slice(0, 10).replaceAll('-', '')
  return `adventure-table-ai-${role}-${stamp}.txt`
}

type AIJoinKitProps = JoinKitInput & { uiCopy: AIJoinKitUiCopy }

export function AIJoinKit({ origin, token, role, locale, expiresAt, uiCopy }: AIJoinKitProps) {
  const template = templateCopy[locale]
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState(false)
  const kit = useMemo(
    () => buildAIJoinKit({ origin, token, role, locale, expiresAt }),
    [origin, token, role, locale, expiresAt],
  )

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
      {isLoopbackOrigin(origin) ? <p className="session-ai-hint">{template.loopback}</p> : null}
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
