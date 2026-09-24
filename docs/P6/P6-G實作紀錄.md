# P6-G — Full P6 Integration & Closeout 實作紀錄

## 接手摘要

- **更新日期**：2026-09-24。
- **目標與邊界**：用 P6-A～F 已交付的 production service 驗空 Campaign 與 Adventure-driven 兩條完整旅程、PostgreSQL restart／next Session continuity、Player secrecy、Quick Combat／Standalone 邊界、真實 ChatGPT Web connector，最後做 P6 closeout。G 不新增核心資料模型或新玩法；若發現 A～F 必要能力缺漏，回所屬 Subphase 補實作與證據。
- **Branch**：`codex/p6g-integration`，基於 P6-F 關門驗證 commit `73a2ee9a`。P6-F 尚待合併 `main`；本分支只建立依賴分支，不合併或改寫 `main`。
- **最近已驗證 commit**：`e1627262`（G3b Player resume network test；指揮者完成跨 transport secrecy matrix、P5／Standalone 靜態邊界與 focused regression）。
- **下一步**：依 [G4](P6-G_steps/G4.md)「測試方法」重跑 G4：新 AI DM Token、新 ChatGPT 對話，只給一句開場指示，AI 須自行從 outline 發現 Adventure、設 scene、Check／Quick Combat 與寫回；需要合法 current AI DM controller grant 與 AT 實際 state／event 證據，不以 Human DM session、逐步口述或模型自述代替。
- **阻礙／未審**：G4 第一次嘗試（Session `412d30c9`）發現 AI DM 看不到 Adventure 內容，已作廢並由 G4a 補 P6-C；重跑前需由 Owner Abandon 該 Session 並以含 G4a 的 image 重建 `server-e2e`。建立 AI DM Token 與 OAuth 貼入由使用者親自完成。G5 全套自動 gate 的 backend／frontend／compose 已先驗，完整 E2E 留 G4 後以免重置測試 Room。
- **正式契約**：`docs/P6/實作規格.md`「P6-G」、`開發設計方針.md`「P6-G」、`測試指南.md`「P6-G／G.1～G.8」與 P6 共用風險／執行環境。
- **共用驗證邊界**：E2E 只用獨立 `adventure_table_e2e` 與 Linux Docker Vite；每步沿現有 Room fixture／backend REST／Playwright helper，不建立 test-only production bypass。Browser journey 要斷言實際 AT UI／API state；Player 的秘密靠 server projection。

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| G1a | Empty Campaign：Start、narration、Quick Add、Exploration、Check／roll | 完成 | P6-F | [G1a](P6-G_steps/G1a.md) |
| G1b-1 | Empty Campaign：Quick Combat attack／damage／End | 完成 | G1a | [G1b-1](P6-G_steps/G1b-1.md) |
| G1b-2 | Empty Campaign：world change、End／next Session | 完成 | G1b-1 | [G1b-2](P6-G_steps/G1b-2.md) |
| G2a | Adventure journey：author／finalize、attach、Scene、Stage | 完成 | P6-F | [G2a](P6-G_steps/G2a.md) |
| G2b-1 | Adventure journey：Exploration／formal Check | 完成 | G2a | [G2b-1](P6-G_steps/G2b-1.md) |
| G2b-2 | Adventure journey：Quick Combat | 完成 | G2b-1 | [G2b-2](P6-G_steps/G2b-2.md) |
| G2b-3 | Adventure journey：write-back／next Session truth | 完成 | G2b-2 | [G2b-3](P6-G_steps/G2b-3.md) |
| G3a | PostgreSQL restart／reconnect continuity | 完成 | G1b-2／G2b-3 | [G3a](P6-G_steps/G3a.md) |
| G3b | Secrecy matrix 與 P5／Standalone 邊界 | 完成 | G2b-3 | [G3b](P6-G_steps/G3b.md) |
| G4a | AI DM Adventure outline 與主持指引（P6-C 補缺） | 完成 | G4 第一次嘗試 | [G4a](P6-G_steps/G4a.md) |
| G4b | AI DM 即興與桌面語言指引（G4 第二次嘗試補缺） | 完成 | G4a | [G4b](P6-G_steps/G4b.md) |
| G4 | 真實 ChatGPT Web connector world-state journey | 進行中 | G2b-3、G4a、G4b | [G4](P6-G_steps/G4.md) |
| G5 | 全套 regression、靜態審核與 P6 closeout | 待做 | G1～G4 | [G5](P6-G_steps/G5.md) |
