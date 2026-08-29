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

目前狀態：**產品規格與大 Phase 已整理完成；基礎技術棧已初步討論，下一步正式進入 P0 規劃。**

已完成：

- 產品定位與範圍定案。
- Human / AI 共桌模式定案。
- Room / Campaign / Session / Seat 概念定案。
- Character / Party Roster 行為定案。
- Character Builder / Multiclass / Spellcasting 核心規則方向定案。
- Quick Combat / Tactical Combat 產品行為定案。
- Adventure / Campaign Runtime / AI DM write-back 原則定案。
- Timeline / Snapshot / Export 等產品層行為定案。
- 第一版明確不做項目已整理。
- 大 Phase P0～P8 已排定。
- 基礎技術棧方向已初步收斂：React + TypeScript + Vite / Python + FastAPI / PostgreSQL。

`技術棧討論.md` 只處理語言、Framework、DB、基本測試與部署工具；**不提前承擔各 Phase 的資料模型、API、權限、事件或其他實作設計。**

**下一步：建立 `docs/P0/`，完成 P0 的 `實作規格.md`、`開發設計方針.md`、`測試指南.md`，再開始 coding。**

---

## Phase Roadmap

> 原則：先把角色與規則資料做完整，再把角色帶進桌內；每個 Phase 準備開工時才設計該 Phase 的細節。

| Phase | 主題 | 重點 |
|---|---|---|
| **P0** | **Character Core + SRD / Rules Foundation** | 完整導入 SRD 5.1 可用資料；建立 Character 核心資料、角色卡與角色相關規則計算基礎 |
| **P1** | **Character Builder Complete** | 完整創角、高等角色建立、Level-by-level progression、Subclass、Multiclass、ASI / Feat、Spell progression、Level Up、Character Version |
| **P2** | **Room / Campaign / Session / Seat** | 把已建立的角色真正放進桌內；建立 Room、Campaign、Party Roster、Player Seat、Controller 與 Session lifecycle |
| **P3** | **Exploration + Roll + AI** | 建立 Exploration、Chat / Action / Check、正式骰子與 PendingAction；Human / AI 開始能在同一桌真正跑團 |
| **P4** | **Quick Combat** | 第一個完整可玩的 Combat MVP：Initiative、Action Economy、Attack、Spell、Condition、Reaction、Death Save 等，不依賴精準地圖 |
| **P5** | **Tactical Combat** | 在同一 Combat Engine 上增加 Grid、Battle Map、Movement、Range、AoE、Wall / Door / Terrain、Automatic OA 等空間系統 |
| **P6** | **Adventure + AI DM Runtime** | Adventure Definition / Importer、Campaign Runtime、World State、NPC / Scene / Fact、AI DM context 與 write-back |
| **P7** | **Snapshot / Export** | 長期 Campaign 安全與可攜性：Timeline、Snapshot / Restore、Archive lifecycle、Character / Adventure / Campaign / Room Import / Export；不做 Undo 機制 |
| **P8** | **QA / Polish** | 全流程整合測試、權限與 AI reconnect 測試、錯誤處理、效能、Responsive UI、UX polish 與第一版收尾 |

---

## P0 / P1 邊界

### P0 — Character Core + SRD / Rules Foundation

P0 先建立後續系統共用的正式內容與角色地基：

- 完整可用的 SRD 5.1 reference data。
- Character 核心資料與保存／載入能力。
- Digital Character Sheet。
- Ability / Skill / Save / AC / Proficiency / Spell DC 等基礎計算。
- Build 與 Current State 的基本分離。
- Spell / Item / Feature 等 reference data 能被角色引用。

P0 的資料與規則地基必須**能承載**複雜角色，例如 Human Fighter 5 / Wizard 5，但 P0 不要求玩家從 UI 依完整升級流程建立它。

### P1 — Character Builder Complete

P1 才把「角色資料能存在」提升成「網站能依 D&D 5e 2014 規則建立與成長角色」。

核心驗證案例之一：

> 從空白建立一名 **Human Fighter 5 / Wizard 5（Character Level 10）** 的合法角色，不直接修改底層資料。

P1 詳細規格等 P1 開工時再寫，不在 P0 提前完成。

---

## 文件分工

| 文件 | 責任 |
|---|---|
| **`AGENTS.md`** | Agent 開工規則、文件查閱方式、修改與驗證守則 |
| **`PROJECT_BRIEF.md`** | 專案總覽、當前 Phase、Roadmap、下一步、文件索引 |
| **`規格企劃.md`** | 產品定位、跑團方式、Human / AI 行為、角色、戰鬥、Adventure、UI/UX 與產品單一事實來源 |
| **`技術棧討論.md`** | 暫時性的基礎技術選型討論；不負責各 Phase 的實作設計 |
| **`docs/Px/實作規格.md`** | 該 Phase 必須做到什麼、驗收意圖 |
| **`docs/Px/開發設計方針.md`** | 該 Phase 實際怎麼做：資料模型、模組、API、資料流與必要技術決策 |
| **`docs/Px/測試指南.md`** | 該 Phase 的自動／人工驗收流程 |
| **`待決事項.md`** | 真正無法從既有規格推導、且會影響核心玩法／方向的未決問題 |

目前：

```text
adventure-table/
├── AGENTS.md
├── PROJECT_BRIEF.md
├── 規格企劃.md
└── 技術棧討論.md
```

接下來建立：

```text
docs/
└── P0/
    ├── 實作規格.md
    ├── 開發設計方針.md
    └── 測試指南.md
```

---

## Phase 規劃規則

每個 Phase 準備開工時才進行詳細拆解：

```text
確認該 Phase 的產品目標
↓
寫 實作規格.md：完成後什麼必須成立
↓
寫 開發設計方針.md：這一 Phase 實際怎麼做
↓
寫 測試指南.md：如何證明做對
↓
開始實作
↓
Phase 收尾後更新 PROJECT_BRIEF
```

可以保留必要的跨 Phase 相容性要求，但**不要因此提前設計後續 Phase 的 schema / API / module**。

---

## 開發接手原則

新的 ChatGPT / Claude / Codex Session 或實作者進入專案時：

1. 先讀 `AGENTS.md`。
2. 再讀 `PROJECT_BRIEF.md` 取得目前 Phase 與下一步。
3. 按任務讀 `規格企劃.md` 對應章節。
4. 若目前 Phase 已有 `docs/Px/` 文件，再讀該 Phase 的實作規格、開發設計與測試指南。
5. 不重新討論已定案產品規格。
6. 不為還沒開工的 Phase 預先設計具體實作。
7. 每完成一個 Phase，更新本檔進度與下一步。