# P5-D — AoE & Tactical Spell Geometry 實作紀錄

## 接手摘要

- **更新日期**：2026-09-27
- **目標與邊界**：Tactical AoE 由 Server 以 canonical geometry（circle／cone／line／square，cell-center 規則）算 affected cells 與 candidate combatants，接回既有 P4 AoE 提案／DM 確認／save／damage pipeline；Player preview 不洩漏 hidden token；confirm 綁 board revision、retry 不重複。**Backend only**；前端 renderer、template 操作 UI、MCP tool 屬 P5-F；OA 屬 P5-E。契約：`docs/P5/實作規格.md` §4.3、§4.5、§8；`docs/P5/開發設計方針.md` §4、§8、§11、§14；`docs/P5/測試指南.md` §3、D.1～D.6。
- **Branch**：`feat/p5d-aoe-tactical-spell-geometry`（自 `main@7eeab560` 開出）
- **最近已驗證 commit**：—
- **Worker**：Muse（thread `https://muse.ai/thread/a2928d6f-41d1-466e-81f9-b9c59bbdca60`，與 P5-C 同一個）。prompt 存 `C:\_work\AI_Work\Tools\agy-runs\muse-p5d-<step>.prompt.txt`。關門（D2）由指揮者做。
- **下一步**：D1
- **阻礙／未審**：無
- **本 Subphase 技術決策（契約未指定，指揮者拍板）**：
  1. 純幾何放 `app/domain/spatial/aoe.py`（不擲骰、不碰 DB）。Shape 由 spell content 的 `area_of_effect`（`type`、`size`）normalize：`sphere`／`cylinder` → `circle`（radius = size）、`cube` → `square`（side = size）、`cone` → `cone`（length = size）、`line` → `line`（length = size，width 固定 5 ft；content 沒有寬度資料，其他寬度交 DM 調整）。不以 spell name hardcode。
  2. Origin 一律是 grid vertex（整數格點）。circle 以 origin 為中心；square 以 origin 為一角、`direction` 指定象限；cone／line 以 origin 為頂點、朝 `aim` 點（grid 座標，可為小數，允許任意角度）。
  3. Cell-center 規則：cell 中心落入模板才算 affected。半徑／長度一律用 shared 5/10 grid distance（`primitives` 同一套）：origin vertex 到 cell 中心的軸向步數取 `ceil(|dx|)`、`ceil(|dy|)` 後套 5/10 規則。cone 另需 cell 中心落在軸線 ±`atan(1/2)` 楔形內（5e cone 寬度等於距離）；line 另需 cell 中心到軸線的垂直距離 ≤ 半寬（2.5 ft），且投影在 0～length 之間。邊界以 `<=` 判定，golden fixture 覆蓋邊界。
  4. Tactical AoE 沿用 P4 AoE 提案／DM 確認流程：caster 送 template → Server 算 candidate list 寫進提案 → DM confirm 時可增刪（obstruction／特殊規則，D.6）→ 既有 resolution 只跑一次。Quick AoE 流程完全不變。
  5. Preview endpoint 無狀態，回 affected cells、visible candidates 與 `board_revision`；提案帶 `board_revision`，與目前 `runtime_revision` 不符 → 409 `combat_board_stale`，重算後重送。Player preview 省略 hidden combatant（cells 是純幾何，照回）；DM preview 完整。
  6. Golden fixture 放 `apps/server/tests/fixtures/p5d_aoe_golden.json`（shape 參數 → affected cells），P5-F 前端 renderer 重用同一檔對齊。
- **跨步依賴**：D2 依賴 D1

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| D1 | AoE geometry、golden fixtures、Tactical AoE preview／提案接線、hidden 過濾、stale 與 idempotency（D.1～D.6） | 進行中 | — | [D1](P5-D_steps/D1.md) |
| D2 | 關門 gate、closeout、合併 `main`（指揮者） | 待做 | D1 | — |
