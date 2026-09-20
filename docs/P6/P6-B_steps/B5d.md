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

- 待補。
