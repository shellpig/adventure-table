# P6-G — Full P6 Integration & Closeout 實作紀錄

## 接手摘要

- **更新日期**：2026-09-25。
- **目標與邊界**：用 P6-A～F 已交付的 production service 驗空 Campaign 與 Adventure-driven 兩條完整旅程、PostgreSQL restart／next Session continuity、Player secrecy、Quick Combat／Standalone 邊界、真實網頁版 AI agent connector，最後做 P6 closeout。G 不新增核心資料模型或新玩法；若發現 A～F 必要能力缺漏，回所屬 Subphase 補實作與證據。
- **Branch**：`codex/p6g-integration`，基於 P6-F 關門驗證 commit `73a2ee9a`。P6-F 尚待合併 `main`；本分支只建立依賴分支，不合併或改寫 `main`。
- **最近已驗證 commit**：G5a／G5 closeout（見 git log；全套 backend 2556 passed／78 skipped、frontend 775 passed＋build、全套 Docker E2E 各趟與 xge-less 子集通過，詳見 [closeout](P6-G_CLOSEOUT.md)）。
- **下一步**：P6-G 已關門並合併（P6-F `b06e2e21`、P6-G `8b47fb05`）；之後進 M06，再 P5。
- **阻礙／未審**：無。
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
| G4c | World 寫入工具 state 形狀說明與錯誤 detail（G4 續跑補缺） | 完成 | G4b | [G4c](P6-G_steps/G4c.md) |
| G4d | 暫時性 MCP 失敗重試指引與 host 中立措辭（G4 收尾補缺） | 完成 | G4c | [G4d](P6-G_steps/G4d.md) |
| G4 | 真實網頁版 AI agent connector world-state journey | 完成 | G2b-3、G4a～G4d | [G4](P6-G_steps/G4.md) |
| G5a | AI campaign context 自由文字與清單上限（G5 靜態審核補缺） | 完成 | G4 | [G5a](P6-G_steps/G5a.md) |
| G5 | 全套 regression、靜態審核與 P6 closeout | 完成 | G1～G4、G5a | [G5](P6-G_steps/G5.md) |
