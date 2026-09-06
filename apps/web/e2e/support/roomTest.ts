import { test as base } from '@playwright/test'

import { enterRoom, openCharacterWorkshop, type E2ERoomContext } from './room'

export { expect } from '@playwright/test'
export type * from '@playwright/test'
export { openCharacterWorkshop }

export const test = base.extend<{ roomContext: E2ERoomContext }>({
  roomContext: [
    async ({ page }, use) => {
      const roomContext = await enterRoom(page)
      await use(roomContext)
    },
    { auto: true },
  ],
})
