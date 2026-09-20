# B2a — web 純邏輯：history chain 與 API client

## Scope

- `api/sessions.ts`：`SessionHistoryLink` type、`getPreviousSession()`。
- `sessionEventStream.ts`：`OlderSessionHistory`、`SessionHistoryChain`、`emptyHistoryChain()`、`hasOlderHistory(stream, chain)`、`applyOlderSessionPage()`、`pushOlderSession()`（§4.5）。本場 `SessionEventStreamState` 零改動。
- `sessionEventStream.test.ts`：B.4 的 `hasOlderHistory` 四種情境、`applyOlderSessionPage` 冪等／忽略他場、空場 push。

## 前置

- B1b 已 commit（DTO 欄位定案）。

## 紀錄

（待補）
