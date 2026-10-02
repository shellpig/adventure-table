# P5-G — Full P5 Integration & Closeout · Closeout

- **日期**：2026-10-02
- **Branch**：`feat/p5g-full-p5-integration-closeout`（自 `main@7b019bdc`）
- **Worker**：G1 Muse（backend）；G2 agy（browser E2E 與前端修補）；G2e～G2i §4 人工驗收修正與 G3 由指揮者。步驟紀錄見 [P5-G 實作紀錄](P5-G實作紀錄.md)。
- **關門決定**：使用者 2026-10-02 指示以現況關門並合併 `main`，G.5 真實 AI gate 延後（見「延後項目」）。

## 範圍

P5-A～F 的整合驗收與修補：補齊 restart、併發 stale、secrecy matrix 的 backend 證據；Quick regression 與 Tactical full journey 的 browser E2E；使用者 §4 人工驗收中發現的地圖編輯器與 Tactical UI 缺陷。P5-G 未新增 P5 核心規則；Free Drawing 與 `normal` 地形是 P5-F／P5-A 漏做的既有契約項目（見「P5-F 以前的驗收漏洞」）。

## 驗收對應

| 契約（測試指南） | 證據 |
|---|---|
| G.1 Quick regression | `apps/web/e2e/p4e-quick-combat.spec.ts`：Player 施法者從 action bar 施放 Fireball → DM 在裁定面板取消 Goblin／Mage → `confirmed_target_ids` 精確等於 Hero＋Thug；DM trigger OA → Player 拒絕；全程 map panel 不出現、`/combat/board` 零請求 |
| G.2 Tactical full journey | `apps/web/e2e/p5g-tactical-full-journey.spec.ts`：SRD Monster＋Quick Enemy、Large Ogre 2×2、對角 5/10、Difficult Terrain、split movement（移動→Shove→再移動）、target-check normal／long／out_of_range、自動 OA 暫停→DM 拒絕→resume、Player 施法者 Fireball 模板→preview→confirm→DM resolve、hidden Stalker 不進 Player DOM／board payload、End Session→Start Session 後同一 combat、End Combat；caster 來自真 Builder 流程產生的 `tests/data/p5g/fixture_wizard5_fireball.json` |
| G.2 地圖編輯器（補充） | `apps/web/e2e/p5g-map-editor-save.spec.ts`：把手加高畫布、紅色粗細 8 繪製、單擊放牆與門、存檔 PUT 200、既有牆 id 保留、payload 帶 `color`／`width`、再存 id 不變、重新整理後重開仍在 |
| G.3 Real PostgreSQL restart | `tests/test_p5g_restart.py::test_p5g_g3_postgres_restart_preserves_full_tactical_state`（round 2、Difficult Terrain bookkeeping、OA paused、pending roll、hidden token、未揭露 hidden door；restart 後 board／turn／revision／pending／event 數全等，resume 只一次）；另有 `test_p5e_acceptance.py::test_postgres_restart_recovers_paused_movement_and_resumes_once` |
| G.4 Concurrent stale command | `tests/test_p5g_concurrent_stale.py::test_p5g_g4_human_rest_vs_ai_mcp_movement_stale`、`::test_p5g_g4_dm_reposition_vs_player_stale_confirm`、`::test_p5g_g4_dm_door_change_vs_stale_aoe_propose`（敗方 `combat_movement_stale`／`combat_board_stale`，零副作用） |
| G.5 Real web chat AI agent | **延後**，見下方「延後項目」 |
| G.6 Secrecy matrix | `tests/test_p5g_secrecy.py::test_p5g_g6_surface_{rest_board,session_resume,player_event_stream,mcp_combat_get_board,mcp_get_session_context,hidden_interruption,aoe_preview,target_check}`、`::test_p5g_g6_dm_sees_enemy_hp_ac_players_do_not`（DM 看得到、Human／AI Player 看不到，含 wall 排序側通道） |
| G.7 Standalone | `test_m03_import_boundary.py`、schema parity 在全套 pytest 內通過；P5-G 的 migration `0040` 只改多人層 `battle_map_terrain` 的 check constraint，不觸及 Standalone／packaging，不需 standalone build／frozen smoke |
| G.8 Closeout evidence | 本檔「關門 gate」；secrecy matrix 見 G.6；static review 見「指揮者審核修正」 |
| §4 人工驗收 | 使用者 2026-09-28～29 以兩個瀏覽器當 DM／Player 實際操作，2026-09-29 確認結束；發現的缺陷見「人工驗收修正」 |

### §5 blocker 核對

| Blocker | 結論與證據 |
|---|---|
| Quick 需要 Battle Map／coordinates | 否：G.1 E2E 全程無 map panel、零 `/combat/board` 請求 |
| Tactical 有第二套 attack／spell／damage／reaction logic | 否：P5-F `test_p5f_f1b.py::test_f5_human_rest_vs_ai_mcp_movement_parity`；Tactical 走 P4 resolution（P5-C～E closeout） |
| client／MCP 可直接改 canonical position | 否：P5-F F.3 authority 測試（`test_f3b_player_reposition_rejected_zero_side_effects` 等） |
| Map Definition 與 Combat runtime 互相污染 | 否：開戰時複製 `board.baseline`（P5-A 決策），之後編輯地圖不影響進行中戰鬥；地圖編輯器只在無戰鬥時開啟 |
| preview／commit 演算法不同 | 否：P5-B、P5-D closeout；G.2 E2E 中 UI 距離與 server distance 一致 |
| hidden spatial data 外洩 | Tactical 面向否：G.6 matrix。另見「已知限制」的 KI-P5A-001（非 spatial，屬已結束戰鬥的歷史 projection） |
| movement／OA retry 重複消耗或位移 | 否：`test_p5b_b2.py::test_interrupted_retry_returns_same_result_without_duplicate_event`、`test_p5e_acceptance.py::test_resume_replay_with_same_key_moves_only_once`、`test_p5d_aoe_tactical.py::test_duplicate_propose_and_resolve_with_same_key_apply_once` |
| pending OA 在 restart／reconnect 後消失 | 否：G.3 兩個 PostgreSQL restart 測試 |
| forced movement 錯誤觸發 generic OA | 否：`test_p5e_acceptance.py::test_shove_push_moves_the_target_5ft_without_oa_or_fall_damage` |

## 關門 gate

程式基準 `f43c8a2c`＋E2E spec `eaf5b635`；之後的 commit 只有 P7 契約文件與本次關門文件。

- 全套 backend pytest（`P4_POSTGRES_URL=…/adventure_table_p4`）：exit 0，collected 3,126、39 skipped、0 failed（3,087 passed）。skip 全為 P2／P3／M03B／migration CI 專屬 PostgreSQL job 的環境條件；P4／P5 PostgreSQL 測試全部實跑。含 code quality、M03 boundary／schema parity、migration heads。
- 前端：`npm test -- --run` 114 files／892 passed；`npm run build` 通過；`tsc --noEmit`（含 e2e）無錯。
- `docker compose config -q`：exit 0。
- **全套 Docker E2E**（`npm run test:e2e:docker` 無參數）：`parallel` 107 passed／3 skipped、`baseline-room` 30 passed／1 skipped、`serial-restart` 2 passed、去掉 xge 的 `m03c-character-import` 7 passed；合計 146 passed、4 skipped、0 failed。

## 指揮者審核修正

- **G1（Muse）**：測試逐條對照 G.3／G.4／G.6，無退回；移除 `test_p5g_restart.py` 未用 import。Production 修正：MCP `combat_confirm_movement` 遇 revision 衝突原本回通用 `table_conflict`（`CombatMovementStaleError` 繼承 `RuntimeError` 被泛用分支吃掉），改回與 REST 相同的 `combat_movement_stale`、不帶 detail（`059bea72`）。
- **G2（agy）**：退回 agy 在匯入前替 legacy fixture 硬塞 wizard profile 與法術位的假資料，改由真 Builder 流程產生 caster fixture；Shove 是 Server RNG，改依 `resolution_result.status` 斷言，輸時由 DM 走正式 reposition。前端修正：AoE 瞄準模式下 token 攔截格子點擊（`tokensInteractive`）。

## 人工驗收修正（§4）

| 回合 | 使用者回報 | 修正 |
|---|---|---|
| G2e | 開戰設定面板「難以入目」 | P5-F 的 29 個 `tactical-*`／`battle-map-*` class 沒有任何樣式、牆門 token 無 fill／stroke——補 `sessionTable.css`；設定面板獨立成區塊；空地圖清單文案 |
| G2f | 格線太淡、Ctrl+Z 無效、選取無提示、畫牆門跑偏、「繪製」無作用 | 指標換算改用 SVG `getScreenCTM()` 反矩陣；Ctrl／Cmd+Z；選取金色加粗；hover 脈動提示；補做 Free Drawing（存檔原本固定送 `drawings: []`，會清掉既有 drawing） |
| G2g | 牆與粗格線顏色相近、牆門要單擊放置、滾輪同時捲動網頁 | 移除粗格線；單擊放最近一格邊；原生 `{ passive: false }` wheel listener |
| G2h | 目前工具沒亮、地形要拖曳塗色並有綠色正常地形、中鍵觸發自動捲動 | server 加 `normal` 地形（migration `0040_p5g_terrain_normal`）；地形改正常／困難／阻擋拖曳塗色；工具 active 樣式；中鍵 `preventDefault` |
| G2i | 繪製要 8 色＋可調粗細、編輯區可往下拉 | freehand payload 選填 `color`／`width`（舊資料預設白色／3）；選取改金色光暈；畫布底部拖曳把手（最低 320 px） |
| G2i | （實測發現）新物件存檔一律 422 | 見下節；修正後補 `p5g-map-editor-save.spec.ts` |

## P5-F 以前的驗收漏洞

以下都是已關門 Subphase 的契約項目，關門時未被證據抓到，已在 P5-G 修正：

- **Free Drawing 未實作**：規格 Battle Map Definition 最低支援 Free Drawing，P5-F 的「繪製」按鈕無作用，且編輯器存檔固定送 `drawings: []`。
- **地形選項與 server 不一致**：P5-F 編輯器提供 difficult／water／lava，server 只接受 difficult／blocked（water／lava 存檔被拒、blocked 選不到）；設計文件為 `normal | difficult | blocked`，P5-A 漏了 `normal`。
- **編輯器新增的牆／門／drawing 無法存檔**：自 P5-F `634be143` 起以 `wall-local-N` 等本機 id 送出，server 只接受 UUID 或 null，任何含新物件的存檔都 422；只有無 id 的地形能存。P5-F 的 E2E 以 API 建地圖物件，從未經過編輯器存檔。
- **Tactical UI 無樣式**：P5-F 新增的 class 沒有任何 CSS 規則。

共同原因：P5-F 的 browser 證據集中在戰鬥 journey，地圖編輯器只有元件靜態渲染測試，沒有真 UI 存檔與人眼檢查。後續 Phase 的編輯型 UI 應至少有一條「操作→存檔→重開」E2E。

## 延後項目

- **G.5 真實網頁版 AI agent Tactical gate**：使用者 2026-09-28 決定延後，2026-10-02 指示不等 G.5 先關門合併，以便先做場外地圖庫／怪物庫。因此 G.8 要求的「real web chat AI agent Tactical gate 日期／role／journey」缺席，§4「AI 可從 structured context 理解地圖」也只有 MCP 協定層測試（P5-F F.4／F.6、G.6 MCP 面），沒有真實 AI 證據。補跑方式：E2E 桌（8001）開 Funnel＋本機 `docker-compose.gate.yml`，使用者貼完整 AI Join Kit 給網頁版 AI agent，指揮者在 AT UI 核對 position／turn／roll／HP／reaction。登記於 [已知問題](../../已知問題.md#跨-phase-限制與驗收索引)。

## 已知限制

- **KI-P5A-001**：已結束戰鬥的 hidden Monster 名稱會經 M05 Player 歷史讀取外洩（projection 只讀 active Combat 的 hidden 名單）。這不是 Tactical spatial data，G.6 matrix 涵蓋的是進行中戰鬥的各介面；已登記為 P7-A 必修。見 [已知問題](../../已知問題.md) KI-P5A-001。
- **M03 legacy 角色無法在戰鬥中施法**：legacy 匯入的角色缺 `spellcasting_profiles`，action bar 不出現法術。G2 以真 Builder 產生的 fixture 迴避，未修正；登記於已知問題索引，留待 M 類工作。
- **Shove 輸掉分支**：G.2 兩次綠燈中 Shove 勝負由 Server RNG 決定，輸的 reposition 路徑是否走到無法指定；程式路徑與 P5-F 已驗證的 DM reposition 相同。
- **地圖編輯器互動仍以 E2E 與純函式覆蓋**：前端沒有 testing-library，元件層 pointer／keyboard 事件不做單元測試。
- **地圖編輯器只在開戰前可用**：開戰後 board 是 runtime snapshot（P5-A 決策），戰鬥中只能改 door 狀態與 placement／reposition。
- **DM tactical briefing 距 3,000 字上限只剩 32 字**（P5-F 起），後續新增指引需先精簡。
