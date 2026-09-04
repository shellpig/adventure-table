import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import { CapabilityProvider } from './features/capabilities/CapabilityProvider'
import { LocaleProvider } from './i18n/LocaleProvider'
import { LocaleSwitcher } from './i18n/LocaleSwitcher'
import './styles.css'
import './i18n/locale.css'

const queryClient = new QueryClient()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <LocaleProvider>
        <CapabilityProvider>
          <LocaleSwitcher />
          <App />
        </CapabilityProvider>
      </LocaleProvider>
    </QueryClientProvider>
  </StrictMode>,
)
