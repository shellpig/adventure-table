import { useEffect, useState } from 'react'
import { getRoomAssetContent } from '../../api/roomAssets'

export type AssetThumbnailProps = {
  roomId: string
  assetId: string
  token: string
  alt: string
  onError: (error: unknown) => void
}

export function AssetThumbnail({ roomId, assetId, token, alt, onError }: AssetThumbnailProps) {
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    let objectUrl: string | null = null
    void getRoomAssetContent(roomId, assetId, token)
      .then((blob) => {
        if (!active) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      .catch(onError)
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [roomId, assetId, token, onError])

  if (!url) return null
  return <img alt={alt} className="adventure-asset-thumb" src={url} />
}
