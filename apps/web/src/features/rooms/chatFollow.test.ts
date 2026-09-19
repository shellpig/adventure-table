import { describe, expect, it } from 'vitest'
import {
  CHAT_FOLLOW_THRESHOLD_PX,
  countUnseenChatMessages,
  isChatAtBottom,
} from './chatFollow'

describe('chatFollow helpers', () => {
  describe('isChatAtBottom', () => {
    it('returns true when exactly at the threshold', () => {
      expect(
        isChatAtBottom({
          scrollHeight: 1000,
          scrollTop: 468,
          clientHeight: 500,
        }),
      ).toBe(true)
    })

    it('returns false when at threshold + 1', () => {
      expect(
        isChatAtBottom({
          scrollHeight: 1000,
          scrollTop: 467,
          clientHeight: 500,
        }),
      ).toBe(false)
    })

    it('returns true when scrolled closer than threshold or past bottom', () => {
      expect(
        isChatAtBottom({
          scrollHeight: 1000,
          scrollTop: 500,
          clientHeight: 500,
        }),
      ).toBe(true)
    })

    it('returns true for empty container where scrollHeight === clientHeight', () => {
      expect(
        isChatAtBottom({
          scrollHeight: 300,
          scrollTop: 0,
          clientHeight: 300,
        }),
      ).toBe(true)
    })

    it('supports custom threshold', () => {
      expect(
        isChatAtBottom(
          {
            scrollHeight: 1000,
            scrollTop: 480,
            clientHeight: 500,
          },
          10,
        ),
      ).toBe(false)
      expect(
        isChatAtBottom(
          {
            scrollHeight: 1000,
            scrollTop: 490,
            clientHeight: 500,
          },
          10,
        ),
      ).toBe(true)
    })
  })

  describe('countUnseenChatMessages', () => {
    const events = [{ seq: 1 }, { seq: 3 }, { seq: 5 }, { seq: 7 }]

    it('returns 0 when lastSeenSeq is the newest seq', () => {
      expect(countUnseenChatMessages(events, 7)).toBe(0)
      expect(countUnseenChatMessages(events, 10)).toBe(0)
    })

    it('returns N when N newer exist', () => {
      expect(countUnseenChatMessages(events, 3)).toBe(2)
      expect(countUnseenChatMessages(events, 5)).toBe(1)
    })

    it('returns all when lastSeenSeq is 0', () => {
      expect(countUnseenChatMessages(events, 0)).toBe(4)
    })

    it('returns 0 when chatEvents is empty', () => {
      expect(countUnseenChatMessages([], 0)).toBe(0)
      expect(countUnseenChatMessages([], 5)).toBe(0)
    })
  })
})
