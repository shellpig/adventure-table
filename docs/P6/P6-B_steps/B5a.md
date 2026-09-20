# B5a — Web API／types、雙語 copy、Campaign Changes 骨架

## Scope

- 新增與 B4 精確對齊的 web API client/types、machine error mapping 與 tests。
- Campaign page 增加 Campaign Changes 入口／頁面骨架，載入 Runtime entries、overrides、context；支援 loading/empty/fatal 狀態。
- 所有首次 expose copy 同步 zh-TW/en，沿用既有 auth/session helpers 與 form/layout pattern。

## 契約與輸入

- 依賴 B4；P6 REST/UI surface；既有 `RoomCampaignPage`、Adventure API/client/copy patterns。

## 驗收

- API contract tests、component empty/load/error tests、locale parity、`npm test -- --run`、`npm run build`。

## 完成紀錄

- **起始**：2026-09-21；agy 一回合實作，conversation `6b70e9f2-8af6-4abb-9255-b01f4dbb3712`，約 4 分 46 秒；prompt `C:/_work/AI_Work/Tools/agy-runs/agy-p6b-B5a.prompt.txt`。
- **交付**：新增完整 B4 management／active Campaign Runtime web client 與精確 transport types、九個 stable machine error 的雙語呈現；新增 `/rooms/{room_id}/campaigns/{campaign_id}/changes` 路由與 loading／empty／fatal／summary 骨架；Campaign 詳情頁只對 Owner／DM 顯示入口。
- **指揮者審核修正**：收緊 Pydantic response 一定存在的 payload 欄位與 server 拒絕 null 的 patch 欄位型別；把 active client 測試的空 patch 改成 server 合法 payload；將 Runtime 管理權從 roster 命名拆成明確 `canManageRuntime`；locale 切換時重新取得並呈現對應語言的錯誤狀態。完整審核確認全部 B4 route、request body、DM／Player projection 與 machine error mapping 對齊，沒有把秘密欄位補成 null 或 `?`。
- **測試**（驗證 commit `950308a5`）：`npm test -- --run` → 97 files／584 tests passed；`npm run build` → passed；`..\..\.venv\Scripts\python.exe -m pytest tests/test_code_quality_gate.py -q -n 0` → 2 passed。指揮者修正後再跑三個 focused frontend modules → 3 files／24 tests passed，並重跑 build passed。既有 Vite dynamic-import／chunk-size warning 未因本步新增；B6 依正式步驟負責 P6-B browser E2E。
- **未解問題／下一步**：B5a 無未解；下一步 B5b 在既有 Campaign Changes page/client 上加入 Runtime CRUD 與 Quick Add UI。
