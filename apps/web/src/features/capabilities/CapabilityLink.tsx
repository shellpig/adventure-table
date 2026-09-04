import type { AnchorHTMLAttributes, PropsWithChildren } from 'react'

import { useCapabilities } from './CapabilityProvider'
import type { CapabilityKey } from './types'

type CapabilityLinkProps = PropsWithChildren<
  AnchorHTMLAttributes<HTMLAnchorElement> & {
    capability: CapabilityKey
  }
>

export function CapabilityLink({ capability, children, ...anchorProps }: CapabilityLinkProps) {
  const { isEnabled } = useCapabilities()
  if (!isEnabled(capability)) return null
  return <a {...anchorProps}>{children}</a>
}
