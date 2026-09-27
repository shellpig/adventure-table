# P5-G — Full P5 Integration & Closeout 實作紀錄

## 接手摘要

- **更新日期**：2026-09-28
- **目標與邊界**：P5 全 Phase 整合驗收與修補；補齊 P5-A～F 未涵蓋的整合 gate 證據，跑真實 AI gate 後關 P5。不得在 G 第一次實作 P5 核心功能——若 gate 揭露核心功能缺失，先回報使用者。契約：`docs/P5/實作規格.md` §11、§13；`docs/P5/開發設計方針.md` P5-G 段；`docs/P5/測試指南.md` G.1～G.8、§4、§5。
- **Branch**：`feat/p5g-full-p5-integration-closeout`（自 `main@7b019bdc` 開出）
- **最近已驗證 commit**：無（開工）
- **Worker**：G1 Muse（thread `https://muse.ai/thread/3c177caa-543a-46dd-8438-94f54b07df80`，只做 backend）；G2 agy（本機工作樹，只改 `apps/web`，由指揮者 commit）；G3 指揮者。prompt 存 `C:\_work\AI_Work\Tools\agy-runs\<worker>-p5g-<step>.prompt.txt`。
- **並行規則**：G1 與 G2 同時進行、同一 branch。Muse 只動 `apps/server/**`、agy 只動 `apps/web/**`；指揮者 commit agy 產出前先 `git pull --ff-only` 取 Muse 的 commit。G2 若需要 backend 改動，回報給指揮者轉派，不自己改 server。
- **下一步**：等 G1（Muse，2026-09-28 送出）與 G2（agy，2026-09-28 背景啟動）交付後依手冊 §2.3 驗證
- **阻礙／未審**：無
- **跨步依賴**：G3 依賴 G1、G2

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| G1 | Backend 整合測試與修補：G.3 restart 補齊、G.4 concurrent stale、G.6 secrecy matrix（Muse） | 進行中 | — | [G1](P5-G_steps/G1.md) |
| G2 | Browser E2E：G.1 Quick regression、G.2 Tactical full journey 與 UI 修補（agy） | 進行中 | — | [G2](P5-G_steps/G2.md) |
| G3 | G.5 真實 AI gate、G.7 Standalone、§4 人工驗收、全套 gate、closeout、合併 `main`（指揮者＋使用者） | 待做 | G1、G2 | [G3](P5-G_steps/G3.md) |
