import { useMemo, useState } from 'react'

import type { Locale } from '../../i18n/locale'

export type AIJoinRole = 'dm' | 'player'

type JoinKitInput = {
  origin: string
  token: string
  role: AIJoinRole
  locale: Locale
  expiresAt?: string | null
}

const labels = {
  'zh-TW': {
    title: 'AI Join Kit', hint: '把整份 kit 交給 AI；完整操作規則由 server guide 提供。Token 只顯示一次，請勿轉傳。',
    copy: '複製 Join Kit', copied: '已複製 Join Kit', copyFailed: '無法自動複製 Join Kit，請手動選取文字。', download: '下載 .txt',
    loopback: '提醒：目前 URL 是 loopback 位址；遠端 AI 必須能連到這台機器，否則請改用可公開存取的 origin。',
    role: 'Role', endpoint: 'MCP URL', guide: 'Guide', token: 'AI Join Token', expires: 'Expires',
    first: '第一步：連線後先呼叫 get_session_context。',
    safety: '安全：Token 只顯示一次；不要轉傳或貼到不受信任的位置；使用完畢請由人類撤銷。',
    refresh: '若 Session 開始或改用不同 Role／Seat 後工具仍是舊清單，請 Refresh／重新掃描 connector；換 Role／Seat 必須重新授權。',
    web: 'ChatGPT Web：新增 Adventure Table connector，URL 使用上方 MCP URL；OAuth 要求憑證時貼上此 token。',
    client: 'MCP client：以 Bearer token 連到上方 MCP URL。',
    http: '純 HTTP：只限有 shell 或可對外連網 code execution 的 AI；依 Guide 的 POST /mcp 契約呼叫。',
  },
  en: {
    title: 'AI Join Kit', hint: 'Give the whole kit to the AI; the server-hosted guide contains the full operating rules. The token is shown only once; do not forward it.',
    copy: 'Copy Join Kit', copied: 'Join Kit copied', copyFailed: 'Could not copy the Join Kit automatically. Select and copy the text manually.', download: 'Download .txt',
    loopback: 'Note: this URL uses a loopback address. A remote AI must be able to reach this machine; otherwise use a publicly reachable origin.',
    role: 'Role', endpoint: 'MCP URL', guide: 'Guide', token: 'AI Join Token', expires: 'Expires',
    first: 'First step: after connecting, call get_session_context.',
    safety: 'Security: this token is shown once; do not forward it or paste it into untrusted places; ask the human to revoke it when finished.',
    refresh: 'If tools are stale after Session start or a Role/Seat change, Refresh/rescan the connector. Changing Role/Seat requires a new authorization.',
    web: 'ChatGPT Web: add the Adventure Table connector using the MCP URL above; paste this token when OAuth asks for the credential.',
    client: 'MCP client: connect to the MCP URL above using this token as the Bearer credential.',
    http: 'Raw HTTP: only for an AI with shell or outbound-network code execution; follow the Guide POST /mcp contract.',
  },
} as const

function normalizedOrigin(origin: string) { return origin.replace(/\/$/, '') }

export function isLoopbackOrigin(origin: string) {
  try {
    const hostname = new URL(origin).hostname
    return hostname === 'localhost' || hostname === '::1' || hostname === '[::1]' || hostname.startsWith('127.')
  } catch { return false }
}

export function buildAIJoinKit({ origin, token, role, locale, expiresAt }: JoinKitInput) {
  const copy = labels[locale]
  const base = normalizedOrigin(origin)
  const endpoint = `${base}/mcp`
  const guide = `${base}/mcp/guide?locale=${locale}`
  const lines = [
    'Adventure Table AI Join Kit',
    `${copy.role}: ${role}`,
    `${copy.endpoint}: ${endpoint}`,
    `${copy.guide}: ${guide}`,
    `${copy.token}: ${token}`,
    `${copy.expires}: ${expiresAt ?? 'session/grant lifetime'}`,
    '', copy.first, copy.safety, copy.refresh, '',
    `1. ${copy.web}`, `2. ${copy.client}`, `3. ${copy.http}`,
  ]
  if (isLoopbackOrigin(base)) lines.push('', copy.loopback)
  return lines.join('\n')
}

export function aiJoinKitFilename(role: AIJoinRole, date = new Date()) {
  const stamp = date.toISOString().slice(0, 10).replaceAll('-', '')
  return `adventure-table-ai-${role}-${stamp}.txt`
}

type AIJoinKitProps = JoinKitInput

export function AIJoinKit({ origin, token, role, locale, expiresAt }: AIJoinKitProps) {
  const copy = labels[locale]
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState(false)
  const kit = useMemo(() => buildAIJoinKit({ origin, token, role, locale, expiresAt }), [origin, token, role, locale, expiresAt])

  const copyKit = async () => {
    try {
      await navigator.clipboard.writeText(kit)
      setCopyError(false); setCopied(true)
      window.setTimeout(() => setCopied(false), 2500)
    } catch { setCopyError(true) }
  }

  const downloadKit = () => {
    const blob = new Blob([kit], { type: 'text/plain;charset=utf-8' })
    const href = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = href; anchor.download = aiJoinKitFilename(role); anchor.click(); URL.revokeObjectURL(href)
  }

  return (
    <div className="ai-join-kit" data-ai-join-kit={role}>
      <strong>{copy.title}</strong><p>{copy.hint}</p>
      {isLoopbackOrigin(origin) ? <p className="session-ai-hint">{copy.loopback}</p> : null}
      <pre className="ai-join-kit__text">{kit}</pre>
      <div className="workshop-card__split-actions">
        <button className="button secondary" type="button" onClick={() => void copyKit()}>{copy.copy}</button>
        <button className="button secondary" type="button" onClick={downloadKit}>{copy.download}</button>
        {copied ? <span className="token-copy-feedback" role="status">{copy.copied}</span> : null}
      </div>
      {copyError ? <div className="error-banner" role="alert">{copy.copyFailed}</div> : null}
    </div>
  )
}
