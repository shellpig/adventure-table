# Adventure Table 專案簡報

本文件供新的 ChatGPT / Claude / Codex Session 或實作者快速了解專案全貌；需要產品細節時再深入 `規格企劃.md`。

**本檔負責：專案概述、當前進度、大 Phase Roadmap、下一步與文件索引。**

最後更新：2026-08-29

---

## 專案概述

Adventure Table 是一個**輕量、桌上跑團優先的 D&D 5e 2014 VTT**。

核心方向：

- 真人 DM / Player 可以正常跑團。
- 外部 AI 可透過 MCP / Site Tools 正式加入桌內擔任 DM 或 Player。
- Human 與 AI 使用同一套 Game State / Game Actions。
- Server 是唯一真實狀態來源。
- 網站只處理需要共享、同步、計算、保存、權限控制或 AI 接入的資料。
- 不把產品做成 Foundry 式包山包海平台，也不把 D&D 做成 CRPG。
- 真人 DM 能靠口頭敘事完成的事情，不強迫建立結構化資料。
- 網站本身不接 LLM API；AI 能力來自使用者外部 AI Session。

首發規則集：**D&D 5e 2014**  
Built-in Content：**SRD 5.1**  
專案性質：**朋友間私人使用，非預計商品化平台**

完整產品規格見：`規格企劃.md`。

---

## 當前進度

目前狀態：**產品規格已整理完成，尚未進入正式實作 Phase。P0 開工前正在收斂技術方案。**

已完成：

- 產品定位與範圍定案。
- Human / AI 共桌模式定案。
- Room / Campaign / Session / Seat 概念定案。
- Character / Party Roster 行為定案。
- Character Builder / Multiclass / Spellcasting 核心規則方向定案。
- Quick Combat / Tactical Combat 產品行為定案。
- Adventure / Campaign Runtime / AI DM write-back 原則定案。
- Timeline / Transaction / Snapshot / Export 等產品層行為定案。
- 第一版明確不做項目已整理。
- 大 Phase P0～P8 已排定。
- 已建立 `技術棧討論.md` 並完成第一輪外部 AI review；目前技術方案仍屬討論稿，尚未成為正式 technical SSOT。

第一輪技術 review 後，目前推薦方向包括：

- Frontend：React + TypeScript + Vite。
- Backend：Python + FastAPI + Pydantic。
- Database：PostgreSQL。
- Human UI / MCP 共用同一 Application Use Case。
- P0 就保留中央 Authorization / Visibility Projection 架構。
- P0 就保留 revocable scoped AI token / credential boundary。
- P0 的 GameTransaction / Persistence 不得堵死 P7 Undo / Snapshot / Restore。
- Reference SRD / custom definitions：Git file 是 truth，DB 是 derived / indexed copy。
- Runtime / user-created content：DB 是 truth。
- OpenAPI → TypeScript client/types 採自動 codegen，避免雙語言 schema drift。
- Tactical Map renderer 延後到 P5 準備時再選。

這些仍以 `技術棧討論.md` 為 review 狀態；**真正拍板後要編入 `開發設計方針.md`，才算正式技術決策。**

**下一步：完成技術方案收斂，接著撰寫 P0 `Character Core + SRD / Rules Foundation` 的 `實作規格書.md`；P0 詳細子 Phase 到那時才拆。**

目前只維護大 Phase，不預先拆 P0-A / P0-B 等子 Phase。每一個大 Phase 準備開工時，再另外整理該 Phase 的詳細實作規格、開發設計與驗收方式。

---

## Phase Roadmap

> 原則：先把角色與規則資料做完整，再把角色帶進桌內；AI 必須在前段就進入真正跑團流程，而不是所有功能做完後才附加。

| Phase | 主題 | 重點 |
|---|---|---|
| **P0** | **Character Core + SRD / Rules Foundation** | 完整導入 SRD 5.1 可用資料；建立 Character 核心資料模型、角色卡與角色相關規則計算基礎 |
| **P1** | **Character Builder Complete** | 完整創角、高等角色建立、Level-by-level progression、Subclass、Multiclass、ASI / Feat、Spell progression、Level Up、Character Version |
| **P2** | **Room / Campaign / Session / Seat** | 把已建立的角色真正放進桌內；建立 Room、Campaign、Party Roster、Player Seat、Controller 與 Session lifecycle |
| **P3** | **Exploration + Roll + AI** | 建立 Exploration、Chat / Action / Check、正式骰子與 PendingAction；Human / AI 開始能在同一桌真正跑團 |
| **P4** | **Quick Combat** | 完成第一個完整可玩的 Combat MVP：Initiative、Action Economy、Attack、Spell、Condition、Reaction、Death Save 等，不依賴精準地圖 |
| **P5** | **Tactical Combat** | 在同一 Combat Engine 上增加 Grid、Battle Map、Movement、Range、AoE、Wall / Door / Terrain、Automatic OA 等空間系統 |
| **P6** | **Adventure + AI DM Runtime** | Adventure Definition / Importer、Campaign Runtime、World State、NPC / Scene / Fact、AI DM context 與 write-back |
| **P7** | **Undo / Snapshot / Export** | 長期 Campaign 的安全性與可攜性：Timeline、Undo、Snapshot / Restore、Archive lifecycle、Character / Adventure / Campaign / Room Import / Export |
| **P8** | **QA / Polish** | 全流程整合測試、權限與 AI reconnect 測試、錯誤處理、效能、Responsive UI、UX polish 與第一版收尾 |

---

## Phase 邊界說明

### P0 — Character Core + SRD / Rules Foundation

P0 的核心不是只塞幾筆測試資料，而是先建立後續所有系統共用的正式內容與角色基礎。

SRD 5.1 應在 P0 完成主要資料導入，包括後續創角與遊戲會使用的：

- Race / Traits
- Class / SRD Subclass
- Background
- Features / Traits
- Feats
- Skills / Saves / Ability reference
- Equipment
- Weapons
- Armor
- Adventuring Gear / Items
- Spells
- Conditions
- Monster stat blocks
- Damage types
- Languages
- 其他 Rules Engine 後續需要引用的 SRD reference data

但「資料已導入」不代表該資料的所有玩法自動化都必須在 P0 完成。

例如 Fireball 的正式資料可在 P0 已存在；Tactical Map 上自動畫 AoE 則屬 P5。

P0 同時建立：

- Character 核心資料模型。
- Digital Character Sheet。
- Ability / Skill / Save / AC / Proficiency / Spell DC 等角色計算基礎。
- Build 與 Current State 的基本分離。

此外，雖然以下功能會在較後 Phase 完整實作，但 P0 地基不得把它們堵死：

- P1 Multiclass / high-level progression。
- P2 / P3 Role / Seat / scoped credential / AI Join Token。
- Server-side Permission / Visibility filtering。
- P7 Revert Transaction / Snapshot / Restore。
- P5 Tactical geometry 作為可疊加 spatial layer，而不是 Combat Engine 必備前提。

這些是 architecture compatibility requirement，不代表 P0 要把後續功能 UI 提前做完。

### P1 — Character Builder Complete

P1 要把「角色存在」提升成「網站真正能依 D&D 5e 2014 規則建立與成長角色」。

P1 完成後應可直接從空白建立複雜高等角色，而不是只能手填角色卡。

核心驗證案例之一：

> 從空白建立一名 **Human Fighter 5 / Wizard 5（Character Level 10）** 的合法角色，不直接修改底層 JSON。

系統必須正確處理：

- Total Character Level 與 Class Level 分離。
- Multiclass prerequisite。
- Class level progression order。
- Starting class 與後續 multiclass proficiency 差異。
- Subclass timing。
- ASI / Feat timing 與 prerequisite。
- Fighter / Wizard 各自 features。
- Wizard Spellbook / Prepared Spells。
- Spell Access 與 Spell Slot Resource 分離。
- Character Version / Level Up。

P1 詳細驗收案例與子 Phase 在 P1 開工前再正式撰寫，不在本 Brief 提前拆解。

### P2 之後

P2 起才把完整角色帶入多人桌面；P3 讓 Human / AI 正式開始 Exploration；P4 先完成沒有精準 geometry 的 Quick Combat；P5 再把 Tactical spatial layer 疊到同一 Combat Engine。

這個順序的目的，是避免 Tactical Map 或大量 Adventure 工具提早擋住真正核心的 Character、Human / AI 共桌與 Rules Engine 驗證。

---

## 文件分工

Adventure Table 採與 ReturnFare 類似的文件分流方式，但只有真正需要時才建立文件，避免一開始產生大量空文件。

| 文件 | 責任 |
|---|---|
| **`PROJECT_BRIEF.md`** | 專案總覽、當前進度、大 Phase Roadmap、下一步、文件索引；隨專案進度持續更新 |
| **`規格企劃.md`** | 產品定位、跑團方式、Human / AI 行為、角色、戰鬥、Adventure、UI/UX 與明確不做項目的產品單一事實來源 |
| **`技術棧討論.md`** | **暫時性技術提案／review 文件**；收集候選技術、外部 AI 意見與尚未正式編入方針的架構結論。討論完成後停止維護／刪除 |
| **`實作規格書.md`** | 某 Phase 準備開工時，定義該 Phase 系統「必須做到什麼」與驗收意圖 |
| **`開發設計方針.md`** | **正式 technical SSOT**：拍板技術棧與具體實作契約，包括架構、模組、檔案、API、資料流、MCP、接線方式等 |
| **`測試指南.md`** | 實際操作驗收流程、整合案例與必要人工測試 |
| **`待決事項.md`** | 只有真正未拍板、無法依既有規格合理推導，而且會影響核心玩法／產品方向的問題 |

技術文件生命週期：

```text
技術棧討論.md
↓
外部 AI / 工程 review
↓
討論收斂
↓
正式內容寫入 開發設計方針.md
↓
技術棧討論.md 停止維護／刪除
```

目前主要專案文件：

```text
adventure-table/
├── AGENTS.md
├── PROJECT_BRIEF.md
├── 規格企劃.md
└── 技術棧討論.md
```

P0 準備正式開工時，再依需要建立：

```text
實作規格書.md
開發設計方針.md
測試指南.md
```

若當時真的有重大未決問題，再建立 `待決事項.md`。

---

## Phase 規劃規則

每個大 Phase 準備開工時才進行詳細拆解。

流程：

```text
選定下一個大 Phase
↓
確認產品規格沒有重大缺口
↓
確認晚期功能對本 Phase 是否有反向 architecture requirement
↓
拆該 Phase 子階段
↓
撰寫實作規格
↓
將拍板技術決策寫入開發設計方針
↓
定義自動／人工驗收
↓
開始實作
↓
Phase 收尾後更新 PROJECT_BRIEF
```

不要現在就把 P0～P8 全部拆到最細；後面的實作細節會受前面真正做出的架構與驗證結果影響。

---

## 開發接手原則

新的 ChatGPT / Claude / Codex Session 或實作者進入專案時：

1. 先讀 `PROJECT_BRIEF.md` 取得目前 Phase 與下一步。
2. 再讀 `規格企劃.md` 理解產品與玩法硬規格。
3. 如果任務是技術選型／架構 review，讀 `技術棧討論.md`；但不得把其中尚未編入 `開發設計方針.md` 的內容誤認為正式定案。
4. 若目前 Phase 已有 `實作規格書.md` / `開發設計方針.md` / `測試指南.md`，再依序讀取；其中 `開發設計方針.md` 是正式 technical SSOT。
5. 不重新討論已定案產品規格。
6. 技術細節在不違反產品規格與正式開發方針的前提下自行決定。
7. 只有會明顯改變實際跑團方式、DM / Player 核心權利、D&D 規則玩法或難以逆轉的產品方向，才回來討論。
8. 每完成一個 Phase / 子 Phase，更新本檔進度與下一步。
