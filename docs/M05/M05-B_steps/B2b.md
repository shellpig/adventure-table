# B2b — web 接線：載入流程、分隔線、copy

## Scope

- `RoomSessionPage.tsx`：`historyChain` state、`loadOlderEvents` 三段流程（§4.6）、chain reset、anchor 依賴。
- `SessionTableSurface.tsx`：`olderSessions`／`historyExhausted` props、分隔線、舊場角色名解析、`historyStart`（§4.7）。
- `sessionCopy.ts`：§4.8 五個 key 兩 locale；`sessionTable.css` 分隔線樣式。
- Vitest：`RoomSessionPage.test.ts`（一步一頁、兩個 request、空場、連續空場、reset、cursor 不變）、`SessionTableSurface.test.tsx`（順序、分隔線、角色名、已到最前、投影不受影響）、copy parity。

## 前置

- B2a 已 commit。

## 紀錄

- **起始**：2026-09-20，指揮者自己實作（UI 接線＋雙語 copy，依 conductor-handbook §6）。
- **交付**：`RoomSessionPage` 新 `historyChain` state；`loadOlderEvents` 改為 `nextHistoryRequest` 的 thin switch（current／older／previous＋該場最新頁），全量 Resume 時 `setHistoryChain(emptyHistoryChain())`；`SessionTableSurface` 新 props `olderSessions`／`historyExhausted`，聊天訊息渲染抽成 `renderChatMessage(event, participants)` 供本場與舊場共用（舊場角色名取自該場 participants），`sessionDividerLabel`、`role="separator"` 分隔線、`historyStart`；prepend anchor effect 依賴加 `olderSessions`；copy 五個 key 兩 locale；CSS 分隔線樣式。
- **指揮者審核修正**：不適用。
- **測試**：`SessionTableSurface.test.tsx` 新 describe「cross-Session history」3 案（順序＋分隔線＋雙語＋已到最前、舊場角色名＋DC 不外露＋按鈕存續、Stage 投影不受舊場事件影響）；`RoomSessionPage.test.ts` 新 source 斷言（一次 nextHistoryRequest、previous＋history 同一步、舊頁不進 eventStream、Resume reset、chain 傳入 surface）。`npm test -- --run` 90 files／529 passed；`npm run build` 成功；長行數不變。
- **未解問題／下一步**：`loadOlderEvents` 的行為級測試（mock API）沿用既有 RoomSessionPage 的 source-assertion 慣例，行為由 `nextHistoryRequest` 單元測試＋B3 E2E 覆蓋。下一步 B3。
