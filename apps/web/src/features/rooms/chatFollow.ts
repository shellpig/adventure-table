export const CHAT_FOLLOW_THRESHOLD_PX = 32

export function isChatAtBottom(
  metrics: { scrollTop: number; scrollHeight: number; clientHeight: number },
  threshold = CHAT_FOLLOW_THRESHOLD_PX,
): boolean {
  return metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight <= threshold
}

export function countUnseenChatMessages(
  chatEvents: { seq: number }[],
  lastSeenSeq: number,
): number {
  return chatEvents.filter((event) => event.seq > lastSeenSeq).length
}
