# B4d — Active Session Override／Context／Overlay routes 與完整 stable-error matrix

## Scope

- 在 active Session router 增加 current DM-only override create/get/list/update/clear、context get/update/clear、Adventure entry overlay get/list。
- route 解析 current Human actor 後只呼叫既有 active service methods；Player不得直接讀任何 Adventure Definition／overlay或 override/context DM surface。
- 收斂 B4a～B4d stable machine error mapping與完整 HTTP secrecy／authority matrix，不以 UI hide 代替 server projection。
- 不做 MCP、Web UI、copy 或 P6-C retrieval。

## 契約與輸入

- 依賴 B4b、B4c；讀設計 B.2／B.3、Shared authority、REST surface、concurrency；測試 B.3～B.6。

## 驗收

- Current DM可操作全部；Human Player只保留 B4c Runtime public + own read，override/context/overlay一律拒絕。
- stable errors涵蓋 revision conflict、idempotency conflict、not attached、invalid scene、archived、forbidden、not found、inactive Session；API response不洩漏 persistence exception。
- wrong scope、nonparticipant、stale/revoked actor拒絕零副作用；B4 focused 與既有 P6-B regression全綠。

## 完成紀錄

- **起始**：2026-09-20～2026-09-21；agy 一回合實作，conversation `dedf9df2-78e9-4771-9bfd-c10f3d984390`，約 13 分 23 秒。
- **交付**：active Session override create/get/list/update/clear、context get/update/clear、Adventure overlay get/list routes；共用 typed Human actor resolver；Current DM lifecycle／event tests；Player全 route拒絕；nonparticipant／wrong scope／inactive／stale actor／revision／identity／idempotency／scene validation完整 stable-error matrix。
- **指揮者審核修正**：補上 Player拒絕時 override/context/mutation/event durable state皆零副作用；補 AI Player serialized model無 `dm_notes`／recipient ids；把 detach兩種 blocker改走 public DELETE route，直接驗證 409 `campaign_adventure_detach_blocked` 且清除後204。核對 route無 persistence import、Player無 Adventure Definition／overlay讀取、Human／AI共用 service authority。
- **測試**：B4 API＋P6-B runtime／active／override／context＋P6-A attach＋Exploration API＋quality gate，`106 passed, 2 skipped`；`git diff --check` 通過。
- **驗證 commit**：`3bcc65d4`。
- **未解問題／下一步**：B4無未解；接 B5a Web API／types、雙語 copy、Campaign Changes骨架。
