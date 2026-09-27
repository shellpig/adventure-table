# P5-A — Battle Map & Spatial Foundation 實作紀錄

## 接手摘要

- **更新日期**：2026-09-27
- **目標與邊界**：Battle Map Definition（Blank／Image、Wall／Door／Terrain／Drawing、hidden projection）、`room_assets` 新增 `battle_map_image`、`combats.mode` 放寬 `tactical`、Combat board runtime、footprint／placement validator、Tactical start placement gate、Player／DM secrecy projection。**Backend only**；Human Tactical UI、Map editor UI、MCP Tactical tools 屬 P5-F，movement 屬 P5-B。契約：`docs/P5/實作規格.md` §3～§5、`docs/P5/開發設計方針.md` §2～§5、§11、§12、§14、`docs/P5/測試指南.md` §3 與 A.1～A.7。
- **Branch**：`feat/p5a-battle-map-spatial-foundation`（自 `main@47c2a3e4` 開出）
- **最近已驗證 commit**：Muse A2 `0437ff6e`＋指揮者修正與關門 commit（見 git log）
- **Worker**：Muse（muse.ai，thread `bf1c7224-66b0-40a1-8705-066f2d4afa86`），在自己的 Linux 環境 clone repo、跑 pytest 綠燈後直接 push 本 branch。使用者 2026-09-27 指示 step 可大（每步約 2,000～3,000 行）。prompt 存 `C:\_work\AI_Work\Tools\agy-runs\muse-p5a-<step>.prompt.txt`。關門（A3）由指揮者做。
- **下一步**：無；P5-A 已關門並合併 `main`，接 P5-B。證據見 [P5-A closeout](P5-A_CLOSEOUT.md)
- **阻礙／未審**：無
- **本 Subphase 技術決策（契約未指定，指揮者拍板，verifier 可同步回設計文件）**：
  1. 模組：`app/persistence/battle_maps/`、`app/domain/battle_maps/`、`app/api/rooms/battle_maps.py`；A2 的純幾何放 `app/domain/spatial/`，board runtime table 放 `app/persistence/combat/`。M03 boundary regex 在 A1 同 commit 加 `battle_maps?|combat_boards?|spatial|tactical`。
  2. Migration：A1 `0035_p5a_combat_mode_tactical`、`0036_p5a_battle_maps`（含 `ck_room_assets_kind` 加 `battle_map_image`）；A2 `0037_p5a_combat_board_positions`。`0035` downgrade 遇到 `mode='tactical'` row 直接拒絕（raise），不改寫資料。
  3. Battle Map Definition 讀寫只限 Room Owner／DM（沿用 `require_adventure_author` 同型 authority，拒絕一律 404 不洩漏存在）；Player／AI Player 只從 A2 的 Combat board projection 看到地圖。A1 先交付可單測的 audience projector。
  4. Wall 限 grid vertex 間的水平／垂直線段；Door 為長度 1 的水平／垂直 edge；Terrain 以 cell 記 `difficult | blocked`（normal = 無 row）；Drawing 為純視覺 JSON。Semantic objects 以整批 PUT＋`expected_revision` 原子替換，物件 id 可由 client 保留以維持穩定 identity。
  5. Player projection：hidden wall 省略；hidden door 投影成無 id、無 state 的普通 wall segment；Player 端 wall 一律不帶 id。
- **跨步依賴**：A2 依賴 A1 schema／projector；A3 依賴全部

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| A0 | Muse 環境準備：clone、venv、全套 pytest、PostgreSQL、node | 完成 | — | [A0](P5-A_steps/A0.md) |
| A1 | migrations `0035`／`0036`、`battle_map_image` kind、Battle Map Definition persistence／service／routes／projector、M03 boundary、PG migration test（A.1、A.6、A.7） | 完成 | A0 | [A1](P5-A_steps/A1.md) |
| A2 | spatial primitives、`0037` board runtime、Tactical start＋placement gate＋mid-combat entrant、runtime door、secrecy projection（REST／event／MCP）（A.2～A.5） | 完成 | A1 | [A2](P5-A_steps/A2.md) |
| A3 | 關門 gate、closeout、合併 `main`（指揮者） | 完成 | A1、A2 | — |
