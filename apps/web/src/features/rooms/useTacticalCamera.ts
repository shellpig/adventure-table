import { useCallback, useRef, useState } from 'react'

export type TacticalCamera = {
  x: number
  y: number
  zoom: number
}

export const MIN_ZOOM = 0.25
export const MAX_ZOOM = 4
export const ZOOM_STEP = 1.2

export function clampZoom(zoom: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom))
}

export function applyZoom(
  camera: TacticalCamera,
  factor: number,
  centerX?: number,
  centerY?: number,
): TacticalCamera {
  const nextZoom = clampZoom(camera.zoom * factor)
  if (nextZoom === camera.zoom) return camera
  if (centerX !== undefined && centerY !== undefined) {
    const scale = nextZoom / camera.zoom
    return {
      zoom: nextZoom,
      x: centerX - (centerX - camera.x) * scale,
      y: centerY - (centerY - camera.y) * scale,
    }
  }
  return { ...camera, zoom: nextZoom }
}

export function applyPan(
  camera: TacticalCamera,
  startClientX: number,
  startClientY: number,
  startCamX: number,
  startCamY: number,
  clientX: number,
  clientY: number,
): TacticalCamera {
  return {
    ...camera,
    x: startCamX + (clientX - startClientX),
    y: startCamY + (clientY - startClientY),
  }
}

export function computeFitMap(
  mapWidthPx: number,
  mapHeightPx: number,
  viewportWidth: number,
  viewportHeight: number,
): TacticalCamera | null {
  if (mapWidthPx <= 0 || mapHeightPx <= 0 || viewportWidth <= 0 || viewportHeight <= 0) return null
  const zoom = clampZoom(Math.min(viewportWidth / mapWidthPx, viewportHeight / mapHeightPx))
  return {
    zoom,
    x: (viewportWidth - mapWidthPx * zoom) / 2,
    y: (viewportHeight - mapHeightPx * zoom) / 2,
  }
}

export function computeCenterOn(
  camera: TacticalCamera,
  mapX: number,
  mapY: number,
  viewportWidth: number,
  viewportHeight: number,
): TacticalCamera {
  return {
    ...camera,
    x: viewportWidth / 2 - mapX * camera.zoom,
    y: viewportHeight / 2 - mapY * camera.zoom,
  }
}

export function useTacticalCamera() {
  const [camera, setCamera] = useState<TacticalCamera>({ x: 0, y: 0, zoom: 1 })
  const dragRef = useRef<{ startX: number; startY: number; camX: number; camY: number } | null>(
    null,
  )

  const zoomBy = useCallback((factor: number, centerX?: number, centerY?: number) => {
    setCamera((prev) => applyZoom(prev, factor, centerX, centerY))
  }, [])

  const zoomIn = useCallback(() => zoomBy(ZOOM_STEP), [zoomBy])
  const zoomOut = useCallback(() => zoomBy(1 / ZOOM_STEP), [zoomBy])

  const handleWheel = useCallback(
    (event: { deltaY: number; clientX?: number; clientY?: number }) => {
      const factor = event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP
      zoomBy(factor, event.clientX, event.clientY)
    },
    [zoomBy],
  )

  const startPan = useCallback((clientX: number, clientY: number) => {
    setCamera((prev) => {
      dragRef.current = { startX: clientX, startY: clientY, camX: prev.x, camY: prev.y }
      return prev
    })
  }, [])

  const panBy = useCallback((clientX: number, clientY: number) => {
    const drag = dragRef.current
    if (!drag) return
    setCamera((prev) => applyPan(prev, drag.startX, drag.startY, drag.camX, drag.camY, clientX, clientY))
  }, [])

  const endPan = useCallback(() => {
    dragRef.current = null
  }, [])

  const fitMap = useCallback(
    (mapWidthPx: number, mapHeightPx: number, viewportWidth: number, viewportHeight: number) => {
      const next = computeFitMap(mapWidthPx, mapHeightPx, viewportWidth, viewportHeight)
      if (next) setCamera(next)
    },
    [],
  )

  const centerOn = useCallback(
    (mapX: number, mapY: number, viewportWidth: number, viewportHeight: number) => {
      setCamera((prev) => computeCenterOn(prev, mapX, mapY, viewportWidth, viewportHeight))
    },
    [],
  )

  const reset = useCallback(() => {
    setCamera({ x: 0, y: 0, zoom: 1 })
    dragRef.current = null
  }, [])

  return {
    camera,
    zoomIn,
    zoomOut,
    handleWheel,
    startPan,
    panBy,
    endPan,
    fitMap,
    centerOn,
    reset,
  }
}
