# P5-B — Movement & Path Resolution 實作紀錄

## 接手摘要

- **更新日期**：2026-09-27
- **目標與邊界**：Tactical movement `Plan → Preview → Confirm → Execute`、Server authoritative 本 Turn movement budget／5-10 diagonal parity／split movement、terrain／wall／door／creature-space step validation、stale／idempotent Confirm、hidden blocker 安全中斷、DM proxy movement 與 DM reposition。**Backend only**；Tactical UI／MCP tools 屬 P5-F，range／reach 屬 P5-C，OA 屬 P5-E（`pending_movement_state` 只建欄位與 reset，不做 Reaction 暫停）。契約：`docs/P5/實作規格.md` §4、§6；`docs/P5/開發設計方針.md` §4、§6、§11、§12、§13、§14；`docs/P5/測試指南.md` §3、B.1～B.8。
- **Branch**：`feat/p5b-movement-path-resolution`（自 `main@63f63f95` 開出）
- **最近已驗證 commit**：`6e4ec630`（最終 code）＋`7935b7d3`（測試數字）
- **Worker**：Muse（thread 見指揮者手冊 §4b.1）。prompt 存 `C:\_work\AI_Work\Tools\agy-runs\muse-p5b-<step>.prompt.txt`。關門（B3）由指揮者做。
- **下一步**：無；P5-B 已關門並合併 `main`，接 P5-C。證據見 [P5-B closeout](P5-B_CLOSEOUT.md)
- **阻礙／未審**：無
- **本 Subphase 技術決策（契約未指定，指揮者拍板）**：
  1. 純幾何／path 函式放 `app/domain/spatial/`（沿用 P5-A primitives）；movement service 放 `app/domain/combat/movement.py`，persistence 放既有 `app/persistence/combat_boards/`；routes 加在 `app/api/rooms/combat_board.py`。
  2. Migration `0038_p5b_movement_bookkeeping`（parent `0037`）：`combat_entries` 加 `movement_used_feet`、`movement_diagonal_steps_used`、`movement_budget_feet`、`pending_movement_state`（JSON，P5-B 只 reset 不寫入）。
  3. Path 以相鄰 anchor 序列表達（含起點）；每步 8 向、anchor 移動一格，footprint 全體隨之 sweep。Diagonal 步不得「切角」穿過 wall／closed door 或 blocked cell 的角。
  4. Hostility 沿用既有 subject-kind 判斷（Character vs Monster）；`is_hostile` 由 subject kind 決定是已知邊界，不在 P5-B 擴充。
  5. Budget = 目前 walk speed（套既有 condition／exhaustion speed 修正；`speed_zero` → 0）＋本 Turn 每次 Dash 再加一次 speed。Preview 不持久化；Confirm 以 `expected_position_revision`＋`expected_board_revision`＋`idempotency_key` 做 CAS。
- **跨步依賴**：B2 依賴 B1 的 movement service／path validator；B3 依賴全部

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| B1 | `0038` bookkeeping＋lifecycle reset、spatial path／distance／step cost、creature space、Preview／Confirm＋CAS＋idempotency＋event（B.1～B.6） | 完成 | — | [B1](P5-B_steps/B1.md) |
| B2 | hidden blocker 安全中斷、DM proxy movement audit、DM reposition（B.7、B.8）、B1 審核修正與測試缺口 | 完成 | B1 | [B2](P5-B_steps/B2.md) |
| B3 | 關門 gate、closeout、合併 `main`（指揮者） | 完成 | B1、B2 | — |
