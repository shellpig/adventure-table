# P5-C — Range, Reach & Spatial Targeting 實作紀錄

## 接手摘要

- **更新日期**：2026-09-27
- **目標與邊界**：Tactical Attack／targeted Spell 由 Server 依 footprint、attack／spell range、shared grid distance 與 hard blocker 產生 spatial targeting result，取代 Quick 的 DM in-range 裁定；reach／range 經 `AttackDefinitionResolver → ResolvedAttack` 單一來源；long range disadvantage 與「5 呎內／外」condition 事實接回既有 P4 modifier pipeline。**Backend only**；不做 Cover 自動計算、LOS／lighting、OA（P5-E）、AoE（P5-D）、UI／MCP（P5-F）。契約：`docs/P5/實作規格.md` §4、§7；`docs/P5/開發設計方針.md` §4、§7、§11、§14；`docs/P5/測試指南.md` §3、C.1～C.6。
- **Branch**：`feat/p5c-range-reach-spatial-targeting`（自 `main@6d3997a0` 開出）
- **最近已驗證 commit**：`ceac4627`
- **Worker**：Muse（新 thread「AT P5C」，見指揮者手冊 §4b.1）。prompt 存 `C:\_work\AI_Work\Tools\agy-runs\muse-p5c-<step>.prompt.txt`。關門（C2）由指揮者做。
- **下一步**：無；P5-C 已關門並合併 `main`，接 P5-D。證據見 [P5-C closeout](P5-C_CLOSEOUT.md)
- **阻礙／未審**：無
- **本 Subphase 技術決策（契約未指定，指揮者拍板）**：
  1. Spatial targeting 為純函式放 `app/domain/spatial/targeting.py`（消費 `ResolvedAttack` 與 board snapshot，不擲骰、不寫 DB）；接線放既有 `app/domain/combat/attacks.py`／spell service，不新增 `TacticalAction` model。
  2. Direct targeting 的 hard blocker：從 source footprint 任一格中心到 target footprint 任一格中心，存在一條不穿過 wall／closed／locked door 邊的線段即不擋（只要有一對格子看得到就合法）；open／broken door 不擋。這不是 Cover 計算，只判「完全被牆隔開」。
  3. Tactical attack 不再建立 DM range adjudication：`legal=false` → 409 `combat_target_out_of_range` 或 `combat_target_blocked`（Player 不得從錯誤得知 hidden 物件）；`legal=true` 直接進 P4 formal roll。Quick 流程完全不變。
  4. P4-F 的 Quick 假設（melee＝5 呎內、ranged＝5 呎外）在 Tactical 改用實際 grid distance：prone／paralyzed／unconscious 等「5 呎內／外」的 condition 效果依真實距離判斷。
  5. Spell range 由既有 spell content 的 `range` 解析：`Self`、`Touch`（＝5 呎 reach）、`N feet`；無法解析 → `requires_dm_adjudication=true`，走既有 P4 DM 裁定。
- **跨步依賴**：C2 依賴 C1

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| C1 | `ResolvedAttack` reach／range 欄位、spatial targeting result、hard blocker、Tactical attack／targeted spell 接線、long range 與 5 呎 condition 事實（C.1～C.6） | 完成 | — | [C1](P5-C_steps/C1.md) |
| C2 | 關門 gate、closeout、合併 `main`（指揮者） | 完成 | C1 | — |
