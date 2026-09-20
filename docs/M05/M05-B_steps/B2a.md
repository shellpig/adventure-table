# B2a — web 純邏輯：history chain 與 API client

## Scope

- `api/sessions.ts`：`SessionHistoryLink` type、`getPreviousSession()`。
- `sessionEventStream.ts`：`OlderSessionHistory`、`SessionHistoryChain`、`emptyHistoryChain()`、`hasOlderHistory(stream, chain)`、`applyOlderSessionPage()`、`pushOlderSession()`（§4.5）。本場 `SessionEventStreamState` 零改動。
- `sessionEventStream.test.ts`：B.4 的 `hasOlderHistory` 四種情境、`applyOlderSessionPage` 冪等／忽略他場、空場 push。

## 前置

- B1b 已 commit（DTO 欄位定案）。

## 紀錄

- **起始**：2026-09-20，worker agy（`Gemini 3.8 Flash (High)`），1 回合 2.6 分鐘，prompt `C:/_work/AI_Work/Tools/agy-runs/agy-m05b-B2a.prompt.txt`，conversation `59b32e00-a585-43f4-b0fe-0be2b02bb7c7`
- **交付**：`SessionHistoryLink` type、`getPreviousSession()`；`OlderSessionHistory`、`SessionHistoryChain`、`emptyHistoryChain()`、`hasOlderHistory(state, chain)`（三段判定）、`pushOlderSession()`（null previous → exhausted；他場 page 視為 null）、`applyOlderSessionPage()`（只改對應場、floor 取 min、重複 seq 冪等）、`nextHistoryRequest()`（§4.6 決策以資料回傳，供 B2b 做 thin switch）；`RoomSessionPage` 兩處呼叫暫傳 `{ older: [], exhausted: true }` 維持既有行為；`sessionEventStream.test.ts` 新增 hasOlderHistory 四情境、push／apply／nextHistoryRequest 邊界（含連續空場）。
- **指揮者審核修正**：無；純函式、無 mutation、無 `any`／`!`。
- **測試**：`npm test -- --run` 90 files／525 passed；`npm run build` 成功。
- **未解問題／下一步**：B2b（指揮者）接線 `nextHistoryRequest` 到 `loadOlderEvents`、`SessionTableSurface` 分隔線、copy。
