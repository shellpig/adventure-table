# P5-E — Opportunity Attack & Spatial Reactions 實作紀錄

## 接手摘要

- **更新日期**：2026-09-27
- **目標與邊界**：Tactical voluntary movement 離開敵對 combatant 的 melee reach 時，Server 自動在 trigger boundary 暫停 movement、以既有 P4-D `ReactionWindow` 開 OA window，resolve 後由 MovementService 從 durable path 續走或停止；Shove push／Grapple drag 接入 spatial system。**Backend only**；UI、MCP tools 屬 P5-F。契約：`docs/P5/實作規格.md` §9；`docs/P5/開發設計方針.md` §9、§11、§14；`docs/P5/測試指南.md` §3、E.1～E.6。
- **Branch**：`feat/p5e-opportunity-attack-spatial-reactions`（自 `main@7f08b266` 開出）
- **最近已驗證 commit**：`e9f64b8c`（E1＋E1b＋指揮者修正與驗收測試）
- **Worker**：Muse（thread `https://muse.ai/thread/932eaf87-f705-4b76-9fd7-8d011d7163e0`，使用者 2026-09-27 指定）。prompt 存 `C:\_work\AI_Work\Tools\agy-runs\muse-p5e-<step>.prompt.txt`。關門（E2）由指揮者做。
- **下一步**：無；P5-E 已關門並合併 `main`，接 P5-F。證據見 [P5-E closeout](P5-E_CLOSEOUT.md)
- **阻礙／未審**：無
- **本 Subphase 技術決策（契約未指定，指揮者拍板）**：
  1. **觸發點**：confirm 逐步執行 path；某一步由 previous footprint 在 reactor reach 內、next footprint 在 reach 外時，movement commit 到 previous footprint（仍在 reach 內，5e OA 發生於離開之前）後暫停，`outcome="paused"`。Reach＝reactor 所有 melee `ResolvedAttack.reach_feet` 的最大值（`AttackDefinitionResolver`，沒有 melee attack 時以 unarmed 5 ft），距離一律經 P5-C `is_within_reach`／`grid_distance`。
  2. **Eligible reactor**：active、與 mover 敵對（`is_hostile` 不同側，沿用既有語意）、`reaction_available`、沒有 incapacitated 類 condition（沿用 `effect_resolver` 語意）、0 HP 以外、自己沒有尚未關閉的 reaction window；mover 本回合用過 Disengage 則全部不觸發。Disengage 以新 migration `0039_p5e_disengaged`（parent `0038`）加 `combat_entries.disengaged`，寫入與 `dodging` 同一處、清空併入既有同一批 reset。
  3. **Hidden reactor 不自動 OA**：未揭露的 hidden reactor 不開 window、不暫停 movement（Player 會從「暫停」推知附近有隱藏敵人）；Server 另寫一筆 DM-only 事件記錄該 crossing（reactor、step index），DM 可照既有手動 OA 裁定。Hidden mover 的暫停／續走事件一律 DM-only。
  4. **多 reactor 順序**：同一 boundary 依 canonical initiative order，再以 stable entry order tie-break；window id 與順序寫進 `pending_movement_state`，reload 不變；同一 idempotency key 重送 confirm 回放同一 paused view，不建第二組 window。
  5. **`pending_movement_state`**：至少 `command_id`（confirm idempotency key）、`path`（original anchors）、`current_path_index`、`committed_feet`、`diagonal_steps_used`、`pending_window_ids`（依 reactor 排序）、`boundary_reactor_ids`、`revision`。
  6. **Resume 是明確 command**：`POST .../movement/resume`（mover controller 或 DM，只在 mover 自己的 Turn），前提為本次暫停的 window 全部不再 open。**只要有任一 OA 被 accept，resume 只限 DM**（DM 先依既有 semantic damage 等流程處理 OA 結果）；全部 decline／expire／cancel 時 mover controller 也可 resume。不做「最後一個 window resolve 就自動續走」，避免 OA 傷害尚未套用就繼續移動。Resume 以 `expected_pending_revision`＋idempotency key 保證只續一次。
  7. **Resume revalidation**：重讀 mover HP、conditions、speed、grapple、canonical position。0 HP、speed 0、不能移動 → 停止並清 pending；position 已被別的效果改變 → 取消剩餘 path；否則剩餘 path 從目前 anchor 以剩餘 budget 對 Server truth 驗證（hidden blocker 仍走 P5-B interrupted 路徑），可再次在後續 boundary 暫停。同一 boundary 已詢問過的 reactor 不重複觸發。
  8. **Cancel／advance_turn**：`POST .../movement/cancel-pending`（DM only、必填 reason、audit event），mover 停在已提交位置。`advance_turn` 在 pending 非空且仍有 open window 時回既有 409 state conflict、零副作用；pending 非空但 window 都已關閉時照常推進（等同 mover 選擇不續走）。
  9. **Shove push**：Tactical 的 shove push 方向＝由 attacker footprint 中心指向 target footprint 中心的逐軸符號（可斜向），推 5 ft；request 時以 caller 可見投影 preflight 目的地（出界、Blocked、牆／關門、occupied → 409 零副作用、不擲骰）；complete 時以 Server truth 重驗，不合法則成功的 shove 不移動、事件只說 blocked 不洩漏 hidden。Cause 非 voluntary，不觸發 OA；不做掉落／hazard 傷害。
  10. **Grapple drag**：confirm／preview 加 optional `drag_entry_id`（必須被 mover grapple）；移動成本加倍，除非被拖者小兩級以上；被拖者 footprint 隨 mover 同步平移，每步用同一 occupancy validator（互相佔位除外），不合法整筆 400 零副作用；被拖者不觸發 OA，mover 照常觸發。不拖而離開 reach 的 grapple 結束規則不在本 Subphase 自動化。
- **跨步依賴**：E2 依賴 E1

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| E1 | 自動 OA、durable paused movement、resume／cancel、advance_turn guard、Shove／Grapple 空間化（E.1～E.6） | 完成 | — | [E1](P5-E_steps/E1.md) |
| E2 | 關門 gate、closeout、合併 `main`（指揮者） | 完成 | E1 | — |
