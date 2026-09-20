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

- 待補。
