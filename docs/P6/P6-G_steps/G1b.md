# G1b — Empty Campaign：Combat、world change、next Session

## Scope

- 延續 G1a 同一 browser journey，完成 Quick Combat attack／damage／End Combat、Current Situation／Runtime world change、End Session 與 next Session。
- next Session 以 UI／API 證明先前 Fact／NPC／Current Situation、角色／Combat 結果仍正確；保持 Campaign 零 Adventure。
- 不重造 Combat／Roll 邏輯；使用 P4 既有 action 和 helper。Player 不得操作 DM／Combat 隱藏控制。

## 契約與驗收

- 規格 P6-G G.1；測試指南 G.1 後半、G.6。參考 `e2e/p4f-full-combat-journey.spec.ts`、`p4e-quick-combat.spec.ts`、`p2f-session-lifecycle.spec.ts`。
- `p6g-empty-campaign.spec.ts` Docker E2E、前端 unit／build 通過；指揮者跑受影響 P4／P6 regression。

## 完成紀錄

（待填）
