import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

import { useLocale } from '../../i18n/LocaleProvider'
import { characterIoEn } from '../../i18n/copy/character-io.en'
import { characterIoZhTw } from '../../i18n/copy/character-io.zh-TW'
import { downloadCharacterExport } from './api'
import './character-io.css'

const COPY = {
  en: characterIoEn,
  'zh-TW': characterIoZhTw,
} as const

type ExportCharacterButtonProps = {
  characterId: string
  className?: string
  placement?: 'inline' | 'sheet'
}

export function ExportCharacterButton({
  characterId,
  className = 'button secondary full',
  placement = 'inline',
}: ExportCharacterButtonProps) {
  const { locale } = useLocale()
  const copy = COPY[locale]
  const [pending, setPending] = useState(false)
  const [failed, setFailed] = useState(false)
  const [sheetHeader, setSheetHeader] = useState<HTMLElement | null>(null)

  useEffect(() => {
    if (placement !== 'sheet' || typeof document === 'undefined') {
      setSheetHeader(null)
      return
    }
    setSheetHeader(document.querySelector<HTMLElement>('.character-hero'))
  }, [placement])

  const body = (
    <div className="character-export-action">
      <button
        type="button"
        className={className}
        aria-label={copy.exportAria}
        title={copy.exportTooltip}
        disabled={pending}
        onClick={async () => {
          setPending(true)
          setFailed(false)
          try {
            await downloadCharacterExport(characterId)
          } catch {
            setFailed(true)
          } finally {
            setPending(false)
          }
        }}
      >
        {pending ? copy.exporting : copy.exportLabel}
      </button>
      {failed ? (
        <span className="character-export-toast" role="alert">
          {copy.exportFailed}
        </span>
      ) : null}
    </div>
  )

  if (placement !== 'sheet') return body
  if (sheetHeader === null) return null
  return createPortal(
    <div className="character-export-sheet-action">{body}</div>,
    sheetHeader,
  )
}
