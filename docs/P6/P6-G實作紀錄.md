# P6-G — Full P6 Integration & Closeout 實作紀錄

## 接手摘要

- **更新日期**：2026-09-24。
- **目標與邊界**：用 P6-A～F 已交付的 production service 驗空 Campaign 與 Adventure-driven 兩條完整旅程、PostgreSQL restart／next Session continuity、Player secrecy、Quick Combat／Standalone 邊界、真實 ChatGPT Web connector，最後做 P6 closeout。G 不新增核心資料模型或新玩法；若發現 A～F 必要能力缺漏，回所屬 Subphase 補實作與證據。
- **Branch**：`codex/p6g-integration`，基於 P6-F 關門驗證 commit `73a2ee9a`。P6-F 尚待合併 `main`；本分支只建立依賴分支，不合併或改寫 `main`。
- **最近已驗證 commit**：`8ea3600e`（G1b-2 code；指揮者完成 Docker E2E、frontend、code quality 與 diff 審核）。
- **下一步**：G2a Adventure-driven browser journey 的 author／finalize、attach、Scene、Stage；由 agy 實作，指揮者審核驗證。
- **阻礙／未審**：無。G4 真實 ChatGPT Web gate 需要既有 M04 connector 可操作，不用 host chat 自述代替 AT state 證據。
- **正式契約**：`docs/P6/實作規格.md`「P6-G」、`開發設計方針.md`「P6-G」、`測試指南.md`「P6-G／G.1～G.8」與 P6 共用風險／執行環境。
- **共用驗證邊界**：E2E 只用獨立 `adventure_table_e2e` 與 Linux Docker Vite；每步沿現有 Room fixture／backend REST／Playwright helper，不建立 test-only production bypass。Browser journey 要斷言實際 AT UI／API state；Player 的秘密靠 server projection。

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| G1a | Empty Campaign：Start、narration、Quick Add、Exploration、Check／roll | 完成 | P6-F | [G1a](P6-G_steps/G1a.md) |
| G1b-1 | Empty Campaign：Quick Combat attack／damage／End | 完成 | G1a | [G1b-1](P6-G_steps/G1b-1.md) |
| G1b-2 | Empty Campaign：world change、End／next Session | 完成 | G1b-1 | [G1b-2](P6-G_steps/G1b-2.md) |
| G2a | Adventure journey：author／finalize、attach、Scene、Stage | 待做 | P6-F | [G2a](P6-G_steps/G2a.md) |
| G2b | Adventure journey：Explore／Check／Combat、write-back、next Session | 待做 | G2a | [G2b](P6-G_steps/G2b.md) |
| G3a | PostgreSQL restart／reconnect continuity | 待做 | G1b-2／G2b | [G3a](P6-G_steps/G3a.md) |
| G3b | Secrecy matrix 與 P5／Standalone 邊界 | 待做 | G2b | [G3b](P6-G_steps/G3b.md) |
| G4 | 真實 ChatGPT Web connector world-state journey | 待做 | G2b | [G4](P6-G_steps/G4.md) |
| G5 | 全套 regression、靜態審核與 P6 closeout | 待做 | G1～G4 | [G5](P6-G_steps/G5.md) |
