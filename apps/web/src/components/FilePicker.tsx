import { useRef, useState } from 'react'

import { useUiCopy } from '../i18n/useUiCopy'

type FilePickerProps = {
  accept: string
  disabled: boolean
  onFileChange: (file: File | null) => void
  chooseLabel?: string
}

export function FilePicker({
  accept,
  disabled,
  onFileChange,
  chooseLabel,
}: FilePickerProps) {
  const { t } = useUiCopy()
  const inputRef = useRef<HTMLInputElement>(null)
  const [fileName, setFileName] = useState<string | null>(null)

  return (
    <span className="file-picker">
      <input
        ref={inputRef}
        type="file"
        className="file-picker__input"
        tabIndex={-1}
        accept={accept}
        disabled={disabled}
        onChange={(event) => {
          const file = event.target.files?.[0] ?? null
          setFileName(file ? file.name : null)
          onFileChange(file)
          // Clear the native value so picking the same file again still fires onChange.
          event.target.value = ''
        }}
      />
      <button
        type="button"
        className="button secondary compact file-picker__button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        {chooseLabel ?? t('shared.chooseFile')}
      </button>
      <span className="file-picker__name">
        {fileName ?? t('shared.noFileChosen')}
      </span>
    </span>
  )
}
