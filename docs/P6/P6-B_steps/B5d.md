# B5d — Session DM Current Context 與 Quick Add 接線

## Scope

- Session DM 畫面接入 Current Scene／Situation 顯示與更新，以及 NPC/Fact/Scene 最小 Quick Add。
- 只讓 current DM 操作；Player、非 current controller、失效 session/grant 不顯示控制且 Server 仍拒絕。
- 成功 mutation 透過既有 durable event/waiter 刷新，不新增平行 polling 或第二套 state truth。
- 不做 P6-D AI MCP write-back、definitive narration transaction 或 Stage bridge。

## 契約與輸入

- 依賴 B5a/B5b/B5c；P6 Shared authority、Events、Subphase boundary。

## 驗收

- Session component tests：DM success、Player absence、controller change/reconnect、event refresh、error recovery。
- 全 web unit、build 通過。

## 完成紀錄

- **起始**：2026-09-21；agy conversation `7777fb54-f40c-4582-832d-be79cda255ce` 三回合實作／退修，總計約 23 分鐘；prompt 位於 `C:/_work/AI_Work/Tools/agy-runs/agy-p6b-B5d*.prompt.txt`。
- **交付**：active Session 僅 current Human DM 掛載 Campaign World panel；使用 active-session API 顯示／修改 optional Current Scene／Situation，並 Quick Add Scene／NPC／Fact。初次載入一次，之後只由既有 Session event stream 的新 `world.*` seq 觸發 snapshot refresh；無新增 polling／wait／第二份 canonical state。Player、非 current controller、ended／abandoned Session 不掛載；active API 回 forbidden／inactive 或錯誤 Player projection 時立即清除 DM snapshot/actions。
- **指揮者審核修正**：三輪審查補上 event 早於 HTTP response 造成等待提示永久卡住、重疊 initial/event/retry/conflict load 舊回應覆蓋新狀態、authority loss 後在途 load 恢復 DM controls 等競態；改由 production mount predicate、monotonic load generation／invalidate、active mutation helper 與明確 Retry contract 收斂。另移除 kind selector casts、將 panel error callback 改為必填，並在 conflict refresh 成功時清除舊等待提示。
- **測試**（驗證 commit `4c77d876`）：`npm test -- --run` → 99 files／672 tests passed；`npm run build` → passed；`..\..\.venv\Scripts\python.exe -m pytest tests/test_code_quality_gate.py -q -n 0` → 2 passed；`git diff --check` 通過。既有 Vite dynamic-import／chunk-size warning 不影響輸出；正式 browser E2E 依步驟留在 B6。
- **未解問題／下一步**：B5d 無未解；下一步 B5e 實作 Player Journal public／own-character projection，不在本步加入 AI MCP write-back、narration transaction 或 Stage bridge。
