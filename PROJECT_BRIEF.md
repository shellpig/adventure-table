# Adventure Table 專案簡報

本文件供新的 ChatGPT / Claude / Codex Session 或實作者快速了解專案全貌；需要產品細節時再深入 `規格企劃.md`。

**本檔負責：專案概述、當前進度、大 Phase Roadmap、當前 Phase 的 Subphase 進度、下一步與文件索引。**

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

目前狀態：**P0-B — Character-Relevant SRD Foundation 已完成並通過完整 CI 驗證；P0-C 尚未開工。**

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
- 全專案規則已補上：**每個 Phase 在 coding 前必須拆成可獨立實作、驗證、commit 的 Subphases；只拆當前 Phase，不提前拆後續 Phase。**
- 基礎技術棧已初步收斂：React + TypeScript + Vite / Python + FastAPI / PostgreSQL。
- `技術棧討論.md` 已瘦身，只保留基礎技術選型，不再提前設計各 Phase。
- `docs/P0/實作規格.md`、`開發設計方針.md`、`測試指南.md` 已重排為完全對齊的 P0-A～P0-F。
- P0 的 SRD scope 已縮為 **Character-Relevant SRD**；Monster / Beast stat blocks 明確延後到 P4-A。
- **P0-A — Project Foundation 已實作完成**：React/TypeScript/Vite app shell、TanStack Query provider、FastAPI、PostgreSQL readiness、SQLAlchemy/Alembic baseline、Docker Compose、pytest/Vitest/Playwright baseline 與 CI 驗證均已建立。
- P0-A CI 已實際驗證 fresh checkout 的 backend tests、Alembic、frontend install/build、Vitest、Playwright，以及 Docker Compose 全棧啟動與 `/health`、`/ready`、Web 回應。
- **P0-B — Character-Relevant SRD Foundation 已實作完成**：`data/srd5.1/` 已建立 version-controlled normalized content；目前包含 22 個 character-relevant categories、1,944 筆 entries，並保留 source / ruleset / license / pinned extraction metadata。
- P0-B 已建立 category-specific Pydantic schemas、stable key（`srd5.1:<kind>:<index>`）、`ContentRegistry`、manifest / count validation、recursive required cross-reference validation、啟動 fail-fast 與 query baseline。
- P0-B 負向驗證已覆蓋 duplicate key、missing required field、malformed spell value、dangling reference 與 Monster / Beast scope violation；Monster / Beast 仍未進入 P0。
- P0-B 完整 CI 已實際通過 backend tests、Alembic、frontend build、Vitest、Playwright、Docker Compose config、全棧啟動與 `/health`、`/ready`、Web response，證明 P0-B 未破壞 P0-A baseline。

**下一步：等待使用者明確指示後開始 P0-C — Character Core & Persistence；不要自行開始下一個 Subphase。**

本 Brief 不列 P0 的 DB schema / API 細節；那些內容只住在 `docs/P0/開發設計方針.md`。

---

## Phase Roadmap

> 原則：先把角色與規則資料做完整，再把角色帶進桌內；每個 Phase 準備開工時才設計該 Phase 的細節。

| Phase | 主題 | 重點 |
|---|---|---|
| **P0** | **Character Core + SRD / Rules Foundation** | 導入角色真正需要的 SRD 5.1 reference content；建立 Character 核心資料、角色卡與角色相關規則計算基礎。**不導入 Monster / Beast stat blocks。** |
| **P1** | **Character Builder Complete** | 完整創角、高等角色建立、Level-by-level progression、Subclass、Multiclass、ASI / Feat、Spell progression、Level Up、Character Version |
| **P2** | **Room / Campaign / Session / Seat** | 把已建立的角色真正放進桌內；建立 Room、Campaign、Party Roster、Player Seat、Controller 與 Session lifecycle |
| **P3** | **Exploration + Roll + AI** | 建立 Exploration、Chat / Action / Check、正式骰子與 PendingAction；Human / AI 開始能在同一桌真正跑團 |
| **P4** | **Quick Combat** | 第一個完整可玩的 Combat MVP：Initiative、Action Economy、Attack、Spell、Condition、Reaction、Death Save 等；**P4-A 必須先承接 P0 延後的 SRD Monster / Beast stat blocks，具體 schema / API 到 P4 規劃時再定。** |
| **P5** | **Tactical Combat** | 在同一 Combat Engine 上增加 Grid、Battle Map、Movement、Range、AoE、Wall / Door / Terrain、Automatic OA 等空間系統 |
| **P6** | **Adventure + AI DM Runtime** | Adventure Definition / Importer、Campaign Runtime、World State、NPC / Scene / Fact、AI DM context 與 write-back |
| **P7** | **Snapshot / Export** | 長期 Campaign 安全與可攜性：Timeline、Snapshot / Restore、Archive lifecycle、Character / Adventure / Campaign / Room Import / Export；不做 Undo 機制 |
| **P8** | **QA / Polish** | 全流程整合測試、權限與 AI reconnect 測試、錯誤處理、效能、Responsive UI、UX polish 與第一版收尾 |

尚未輪到的 Phase 維持大 Phase，不提前拆 Subphase。P1～P8 各自準備開工時才依當時 codebase 拆分。

---

## P0 Subphase 進度

狀態：📐 規格可實作；⬜ 尚未規劃／未開工；✅ 完成。

> **子階段一律一列一個，不得合併。** P0 已拆分後，本表就是 P0 進度的單一事實來源。

| Subphase | 狀態 | 重點 |
|---|---|---|
| **P0-A — Project Foundation** | ✅ | React/Vite、FastAPI、PostgreSQL、SQLAlchemy/Alembic、Docker Compose、pytest/Vitest/Playwright baseline；專案可啟動、DB 可 migration、health/smoke 可驗 |
| **P0-B — Character-Relevant SRD Foundation** | ✅ | ContentRegistry、Pydantic schemas、stable keys、cross-reference validation，以及 P0/P1 角色需要的 SRD 5.1 normalized data；**不含 Monster / Beast stat blocks** |
| **P0-C — Character Core & Persistence** | 📐 | Character identity、immutable Build Version、mutable Current State、Build/State split、class order、spell access、HP progression、Hit Dice、Starting Equipment / live Inventory、fixture、DB round-trip |
| **P0-D — Character Rules & Backend API** | 📐 | Ability/PB/Skill/Save/Passive/AC/HP/Spell calculations、Numeric Override、CharacterSheetDTO、Character/State/Reference APIs |
| **P0-E — Character Sheet & State UI** | 📐 | 三頁 Character Sheet、Header、Attributes/Skills、Spells、Inventory、Hit Dice、Roleplay，以及 P0 需要的 Current State 操作與保存 |
| **P0-F — Full P0 Integration & Closeout** | 📐 | 全套 backend/frontend/E2E regression、Build/State isolation、Starting Equipment reload regression、restart persistence、scope guard、人工 smoke test；P0 正式關門 |

實作順序固定由 P0-A → P0-F。每個 Subphase 完成時都必須先通過該階段自己的測試／驗證，再 commit，才進下一個。

---

## P0 / P1 邊界

### P0 — Character Core + SRD / Rules Foundation

P0 建立後續角色系統共用的正式內容與角色地基：

- **Character-Relevant SRD 5.1 reference data**：Race、Class、Subclass、Background、Feature / Trait、Feat、Ability / Skill / Save reference、Equipment、Weapon、Armor、Adventuring Gear / Items、Spells、Conditions、Damage Types、Languages 與角色規則需要的 structured constants。
- Character 核心資料與保存／載入能力。
- Digital Character Sheet。
- Ability / Skill / Save / AC / Proficiency / Spell DC 等基礎計算。
- Build 與 Current State 分離。
- Spell / Item / Feature 等 reference data 能被角色引用。

**P0 明確不導入 Monster / Beast stat blocks、Monster Actions / Traits 等 combat content。** P0～P3 沒有需要完整怪物戰鬥資料的驗收；這一塊延後到 **P4-A — Quick Combat 的第一個 Subphase** 承接。

P0 的資料與規則地基必須能**承載**複雜角色，例如 Human Fighter 5 / Wizard 5，但 P0 不要求玩家從 UI 依完整升級流程建立它。

P0 詳細範圍、設計、驗收分別見：

```text
docs/P0/實作規格.md
docs/P0/開發設計方針.md
docs/P0/測試指南.md
```

### P1 — Character Builder Complete

P1 才把「角色資料能存在」提升成「網站能依 D&D 5e 2014 規則建立與成長角色」。

核心驗證案例之一：

> 從空白建立一名 **Human Fighter 5 / Wizard 5（Character Level 10）** 的合法角色，不直接修改底層資料。

P1 詳細規格與 Subphase 等 P1 準備開工時再寫，不在 P0 提前完成。

---

## P4 已知承接項目

這不是 P4 的提前實作設計，只是 P0 scope cut 的**跨 Phase 承接契約**：

- P4 的第一個 Subphase 命名為 **P4-A**。
- P4-A 必須承接 P0 明確延後的 **SRD 5.1 Monster / Beast stat blocks**。
- P4-A 開工時再依當時 Combat Engine 需求決定 Monster Template 的 schema、actions / attacks / spellcasting representation、validation 與 API；**現在不預先設計。**
- P0 不得為了 P4 提前建立 `monsters.json`、Monster-specific Pydantic schema、Monster Action normalization 或 combat-only validation。

---

## 文件分工

| 文件 | 責任 |
|---|---|
| **`AGENTS.md`** | Agent 開工規則、Subphase 規則、文件查閱方式、修改與驗證守則 |
| **`PROJECT_BRIEF.md`** | 專案總覽、當前 Phase / Subphase、Roadmap、下一步、文件索引 |
| **`規格企劃.md`** | 產品定位、跑團方式、Human / AI 行為、角色、戰鬥、Adventure、UI/UX 與產品單一事實來源 |
| **`技術棧討論.md`** | 暫時性的基礎技術選型討論；不負責各 Phase 的實作設計 |
| **`docs/Px/實作規格.md`** | 該 Phase / Subphase 必須做到什麼、驗收意圖 |
| **`docs/Px/開發設計方針.md`** | 該 Phase / Subphase 實際怎麼做：資料模型、模組、API、資料流與必要技術決策 |
| **`docs/Px/測試指南.md`** | 該 Phase / Subphase 的自動／人工驗收流程 |
| **`待決事項.md`** | 真正無法從既有規格推導、且會影響核心玩法／方向的未決問題 |

目前主要文件與 P0-A / P0-B 實作入口：

```text
adventure-table/
├── apps/
│   ├── server/          # FastAPI / SQLAlchemy / Alembic / Pydantic content registry / pytest
│   └── web/             # React / TypeScript / Vite / Vitest / Playwright
├── data/
│   └── srd5.1/          # P0-B normalized SRD 5.1 content + manifest / attribution
├── scripts/
│   └── vendor_srd.py    # maintainer-only pinned SRD vendor tool
├── .github/workflows/
│   └── p0a-foundation.yml
├── docker-compose.yml
├── README.md
├── AGENTS.md
├── PROJECT_BRIEF.md
├── 規格企劃.md
├── 技術棧討論.md
└── docs/
    └── P0/
        ├── 實作規格.md
        ├── 開發設計方針.md
        └── 測試指南.md
```

---

## Phase 規劃規則

每個 Phase 準備開工時固定走：

```text
確認該 Phase 的產品目標
↓
拆成 P<n>-A、P<n>-B… 可獨立實作／驗證／commit 的 Subphases
↓
三份文件使用完全一致的 Subphase 標題與順序
↓
實作規格.md：每個 Subphase 完成後什麼必須成立
↓
開發設計方針.md：每個 Subphase 實際怎麼做
↓
測試指南.md：每個 Subphase 如何證明做對
↓
等待使用者決定是否開始實作
↓
依序逐 Subphase：Implement → Test → Verify → Commit
↓
最後一個 Subphase 完成整個 Phase regression / closeout
↓
更新 PROJECT_BRIEF
```

可以保留必要的跨 Phase 相容性／承接要求，但**不要因此提前設計後續 Phase 的 schema / API / module**。

---

## 開發接手原則

新的 ChatGPT / Claude / Codex Session 或實作者進入專案時：

1. 先讀 `AGENTS.md`。
2. 再讀 `PROJECT_BRIEF.md` 取得目前 Phase、Subphase 與下一步。
3. 按任務讀 `規格企劃.md` 對應章節。
4. P0 相關任務再依 Subphase id 讀 `docs/P0/` 三份文件的對應段落。
5. 不重新討論已定案產品規格。
6. 不為還沒開工的 Phase 預先設計具體實作。
7. **未獲使用者明確要求，不開始 coding。**
8. 每完成一個 Subphase，先驗證再 commit；每完成一個 Phase，再更新本檔整體進度。
