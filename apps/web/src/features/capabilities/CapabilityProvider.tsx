import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'

import { fetchCapabilities } from './api'
import {
  DEFAULT_WEB_CAPABILITIES,
  type CapabilityKey,
  type CapabilitySnapshot,
} from './types'

type CapabilityContextValue = {
  snapshot: CapabilitySnapshot
  status: 'loading' | 'ready' | 'fallback'
  isEnabled: (capability: CapabilityKey) => boolean
}

type CapabilityProviderProps = PropsWithChildren<{
  initialSnapshot?: CapabilitySnapshot
  fetcher?: () => Promise<CapabilitySnapshot>
}>

const CapabilityContext = createContext<CapabilityContextValue>({
  snapshot: DEFAULT_WEB_CAPABILITIES,
  status: 'ready',
  isEnabled: (capability) => DEFAULT_WEB_CAPABILITIES.capabilities[capability],
})

export function CapabilityProvider({
  children,
  initialSnapshot,
  fetcher = fetchCapabilities,
}: CapabilityProviderProps) {
  const [snapshot, setSnapshot] = useState<CapabilitySnapshot>(
    initialSnapshot ?? DEFAULT_WEB_CAPABILITIES,
  )
  const [status, setStatus] = useState<CapabilityContextValue['status']>(
    initialSnapshot ? 'ready' : 'loading',
  )

  useEffect(() => {
    if (initialSnapshot) return
    let active = true
    void fetcher()
      .then((next) => {
        if (!active) return
        setSnapshot(next)
        setStatus('ready')
      })
      .catch(() => {
        if (!active) return
        setSnapshot(DEFAULT_WEB_CAPABILITIES)
        setStatus('fallback')
      })
    return () => {
      active = false
    }
  }, [fetcher, initialSnapshot])

  const isEnabled = useCallback(
    (capability: CapabilityKey) => snapshot.capabilities[capability],
    [snapshot],
  )
  const value = useMemo(
    () => ({ snapshot, status, isEnabled }),
    [snapshot, status, isEnabled],
  )

  return <CapabilityContext.Provider value={value}>{children}</CapabilityContext.Provider>
}

export function useCapabilities(): CapabilityContextValue {
  return useContext(CapabilityContext)
}
