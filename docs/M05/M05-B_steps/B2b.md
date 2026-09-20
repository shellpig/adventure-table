# B2b — web 接線：載入流程、分隔線、copy

## Scope

- `RoomSessionPage.tsx`：`historyChain` state、`loadOlderEvents` 三段流程（§4.6）、chain reset、anchor 依賴。
- `SessionTableSurface.tsx`：`olderSessions`／`historyExhausted` props、分隔線、舊場角色名解析、`historyStart`（§4.7）。
- `sessionCopy.ts`：§4.8 五個 key 兩 locale；`sessionTable.css` 分隔線樣式。
- Vitest：`RoomSessionPage.test.ts`（一步一頁、兩個 request、空場、連續空場、reset、cursor 不變）、`SessionTableSurface.test.tsx`（順序、分隔線、角色名、已到最前、投影不受影響）、copy parity。

## 前置

- B2a 已 commit。

## 紀錄

（待補）
