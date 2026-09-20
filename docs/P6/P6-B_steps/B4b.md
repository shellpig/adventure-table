# B4b — Session 外 Override／Context／Overlay REST routes

## Scope

- 在 B4a management router 增加 override create/get/list/update/clear、context get/update/clear、Adventure entry overlay get/list routes。
- route 只呼叫既有 management service methods；不直碰 repository，不複製 attach／scene validation。
- 沿用 B4a stable error mapper，補 not-attached、invalid scene／payload 與 override identity/revision 對應。
- 不做 active Session routes、Web UI 或 MCP。

## 契約與輸入

- 依賴 B3a、B3b、B4a；讀設計 B.2／B.3、Shared authority、REST surface、concurrency；測試 B.3／B.5／B.6。

## 驗收

- Owner／DM 在無 active Session 時可操作；Player 被拒。
- overlay 不回寫 Adventure Definition；未 attach、invalid scene、stale identity/revision、active Session mutation 均 stable error 且零副作用。
- clear 後 override/context 狀態與 detach blocker 行為維持既有 service 契約。

## 完成紀錄

- 待補。
