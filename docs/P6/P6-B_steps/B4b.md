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

- **起始**：2026-09-20；agy 一回合實作，conversation `9e99e096-71c9-4150-9f5e-7c35596c7bf1`，約 5 分 15 秒。
- **交付**：Session 外 override create/get/list/update/clear、context get/update/clear、Adventure overlay get/list routes；override-exists stable error；真 service HTTP authority、revision／identity、idempotency、detach blocker與 template separation tests。
- **指揮者審核修正**：核對全部 route 只轉交 management service、Player／wrong scope拒絕、active Session讀寫界線、overlay serialized DTO、clear 後兩種 detach blocker消失，以及拒絕前後 override/context/mutation snapshot不變；本步無需程式修正。
- **測試**：B4 API＋既有 override／context／runtime service／active service／P6-A attach＋quality gate，`80 passed, 2 skipped`；`git diff --check` 通過。
- **驗證 commit**：`3eef7426`。
- **未解問題／下一步**：無；接 B4c Active Session Runtime entry routes 與 Player secrecy。
