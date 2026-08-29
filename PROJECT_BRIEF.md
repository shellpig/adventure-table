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

目前狀態：**P0 — Character Core + SRD / Rules Foundation 已完成；P1 — Character Builder Complete 已完成規劃與 Subphase 拆分。P1-A — Builder Domain & Draft Foundation 與 P1-B — Character Creation Basics 已完成實作與驗證；下一步是 P1-C — Class Progression & Multiclass，尚未開始 P1-C coding。**

已完成的產品／規劃工作：

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
- 全專案規則：**每個 Phase 在 coding 前必須拆成可獨立實作、驗證、commit 的 Subphases；只拆當前 Phase，不提前拆後續 Phase。**
- 基礎技術棧：React + TypeScript + Vite / Python + FastAPI / PostgreSQL。

P0 已完成：

- **P0-A — Project Foundation**：React/TypeScript/Vite、FastAPI、PostgreSQL、SQLAlchemy/Alembic、Docker Compose、pytest/Vitest/Playwright 與 CI baseline。
- **P0-B — Character-Relevant SRD Foundation**：`data/srd5.1/` normalized content、ContentRegistry、stable keys、schema / cross-reference validation；22 categories、1,944 entries；Monster / Beast 延後 P4-A。
- **P0-C — Character Core & Persistence**：Character identity、immutable Build Version、mutable Current State、`characters` / `character_versions` / `character_states`、Fighter 5 / Wizard 5 deterministic fixture。
- **P0-D — Character Rules & Backend API**：Ability/PB/Skill/Save/Passive/AC/HP/Spell calculations、Numeric Override、CharacterSheetDTO、Reference / Character / State APIs。
- **P0-E — Character Sheet & State UI**：三頁 Character Sheet、responsive UI、searchable accessible selectors、HP / Temp HP / Conditions / Prepared / resources / Hit Dice / Inventory state operations。
- **P0-F — Full P0 Integration & Closeout**：P0 full regression、real backend Playwright、PostgreSQL restart persistence、Prepared / Hit Dice reload、Starting Equipment / live Inventory isolation、人工 smoke。

P1 規劃已完成：

- `docs/P1/實作規格.md`
- `docs/P1/開發設計方針.md`
- `docs/P1/測試指南.md`
- 三份文件使用完全一致的 P1-A～P1-H 名稱與順序。
- P1 直接延伸 P0 已存在的 `CharacterBuild` / `CharacterState` / immutable JSONB Build Version / Current State / ContentRegistry / Rules Layer，不重新設計第二套 Character core。
- Builder Draft 與正式 `CharacterBuild` 明確分離；只有 Confirm 才產生正式 Build candidate / Version。
- Ability generation：Standard Array / Point Buy / Manual Input；P1 不提前做正式 Roll System。
- Lv2+ HP：Fixed Average / Manual Rolled Result；P1 不做正式 `Roll HP`。
- Starting Equipment 做完整 structured choices；P1 不做 Starting Gold shopping workflow。
- Level Up Current State reconciliation 已定：保留 damage delta、舊資源消耗不回滿、新 Hit Die 可用、Prepared 合法者保留、Inventory / Conditions 等 live state延續。
- Character JSON Import / Export 留 P7；Builder MCP / AI transport留後續對應 Phase。P1 只建立可被未來 Human UI / AI Tool共用的 backend domain service。

P1-A 已完成：

- 新增獨立 `character_builder` domain，不把不完整資料塞進正式 `CharacterBuild`。
- 新增 `character_build_drafts` persistence 與 Alembic migration；Create Draft 不會先建立正式 Character。
- Draft 支援 Save / Reload / Cancel，並以 revision optimistic guard 防止 stale update 靜默覆蓋新資料。
- 建立 strict Draft / Choice / Validation DTO；validation issue 使用 machine-readable `code` / `severity` / `path` / `message`。
- Choice ID deterministic，reload 或修改無關欄位不會讓既有 selection 失聯。
- 建立純 server-side Builder compiler / view extension point；P1-A 不假裝已具備 P1-B 之後的完整 D&D resolver，因此尚未開放 Confirm。
- 新增 `/api/character-builder/drafts` create / get / patch / validate / delete lifecycle API。
- 新增 typed frontend Builder API 與最小 feature shell；完整 Character Workshop / Wizard 留 P1-B。
- 新增 P1-A schema / persistence / API / revision / choice-stability 測試，並保持 P0 full regression。

P1-B 已完成：

- 新增 `/characters` Character Workshop，可查看 Existing Characters、建立新角色 Draft、Resume Draft 與進入既有 Character Sheet。
- 完成 Create Character Wizard 的 Basic / Origin / Abilities 三個 P1-B 步驟；Class progression 與 Review 依邊界維持 locked。
- Race / Subrace / Background / Alignment 與 starting choices 由 server-generated choices 驅動；前端以 searchable selectors 操作，不硬編 eligible option 清單。
- `subrace_ref` 明確保存在 formal `CharacterBuild` schema，並驗證 Subrace 必須屬於所選 Race。
- Ability generation 支援 Standard Array / Point Buy / Manual Input；規則常數由 versioned server rules data 提供，Point Buy budget / cost 不硬編在 React。
- Race / Subrace / Background 的 ability bonus、languages、proficiencies、traits / feature 與已選 structured choices 由 server resolver 彙整成 live summary。
- Manual ability values超出一般 3–18 仍可保存，但會標記 Non-standard；Numeric Override 與 base / resolved / effective ability summary 保持分離。
- Builder Draft 仍可 Save / Reload / Cancel，但 P1-B 不產生正式 Build candidate，也不開放 Confirm；Class progression 由 P1-C 接手。
- Docker server image 已包含 `data/rules`，確保 container / CI 環境與本機使用同一份 authoritative Builder rules。
- P1-B regression 已通過 backend pytest、Alembic、frontend build、Vitest、Docker full stack、real-browser Playwright 與 PostgreSQL restart persistence，並保持 P0 regression。

**下一步：只有在使用者明確要求開始 P1-C 實作後，才進 P1-C — Class Progression & Multiclass。不要自行開始 P1-C coding。**

P1 的具體 DB / API / module 契約只住在 `docs/P1/開發設計方針.md`；本 Brief 不重複維護。

---

## Phase Roadmap

> 原則：先把角色與規則資料做完整，再把角色帶進桌內；每個 Phase 準備開工時才設計該 Phase 的細節。

| Phase | 主題 | 重點 |
|---|---|---|
| **P0** | **Character Core + SRD / Rules Foundation** | 導入角色真正需要的 SRD 5.1 reference content；建立 Character 核心資料、角色卡與角色相關規則計算基礎。**不導入 Monster / Beast stat blocks。** |
| **P1** | **Character Builder Complete** | 完整創角、高等角色建立、Level-by-level progression、Subclass、Multiclass、ASI / Feat、Spell progression、Level Up、Character Version |
| **P2** | **Room / Campaign / Session / Seat** | 把已建立的角色真正放進桌內；建立 Room、Campaign、Party Roster、Player Seat、Controller 與 Session lifecycle |
| **P3** | **Exploration + Roll + AI** | 建立 Exploration、Chat / Action / Check、正式骰子與 PendingAction；Human / AI 開始能在同一桌真正跑團 |
| **P4** | **Quick Combat** | 第一個完整可玩的 Combat MVP；**P4-A 必須先承接 P0 延後的 SRD Monster / Beast stat blocks。** |
| **P5** | **Tactical Combat** | 在同一 Combat Engine 上增加 Grid、Battle Map、Movement、Range、AoE、Wall / Door / Terrain、Automatic OA 等空間系統 |
| **P6** | **Adventure + AI DM Runtime** | Adventure Definition / Importer、Campaign Runtime、World State、NPC / Scene / Fact、AI DM context 與 write-back |
| **P7** | **Snapshot / Export** | Timeline、Snapshot / Restore、Archive lifecycle、Character / Adventure / Campaign / Room Import / Export；不做 Undo 機制 |
| **P8** | **QA / Polish** | 全流程整合測試、權限與 AI reconnect、錯誤處理、效能、Responsive UI、UX polish 與第一版收尾 |

P1 已拆 Subphase；**P2～P8 仍維持大 Phase，不提前拆。**

---

## P0 Subphase 進度

狀態：📐 規格可實作；⬜ 尚未開工；🚧 進行中；✅ 完成。

| Subphase | 狀態 | 重點 |
|---|---|---|
| **P0-A — Project Foundation** | ✅ | Project / DB / tests / CI baseline |
| **P0-B — Character-Relevant SRD Foundation** | ✅ | Character-relevant SRD / ContentRegistry / validation |
| **P0-C — Character Core & Persistence** | ✅ | Build Version / Current State / persistence / fixture |
| **P0-D — Character Rules & Backend API** | ✅ | Character rules / DTO / APIs / overrides |
| **P0-E — Character Sheet & State UI** | ✅ | 三頁 Character Sheet / state UI / E2E |
| **P0-F — Full P0 Integration & Closeout** | ✅ | Full regression / persistence / smoke / closeout |

---

## P1 Subphase 進度

> **子階段一律一列一個，不得合併。** P1 三份文件已拆分後，本表就是 P1 進度的單一事實來源。

| Subphase | 狀態 | 重點 |
|---|---|---|
| **P1-A — Builder Domain & Draft Foundation** | ✅ | Builder Draft、choice model、compiler / validation、draft persistence；不完整 Draft 不污染正式 Character |
| **P1-B — Character Creation Basics** | ✅ | Character Workshop、Wizard basics、Race/Subrace、Background、Standard Array / Point Buy / Manual、starting skills/proficiencies |
| **P1-C — Class Progression & Multiclass** | ⬜ | Level-by-level rail、starting class、multiclass prerequisites / grants、Subclass timing、HP progression |
| **P1-D — ASI, Feat & Structural Choices** | ⬜ | ASI / Feat timing、prerequisites、generic structural choice resolver、Numeric Override boundary |
| **P1-E — Spellcasting Progression** | ⬜ | Known / Spellbook / Prepared / Always Prepared、multiclass slots、Pact Magic、source profiles |
| **P1-F — Equipment, Review & Character Creation** | ⬜ | Starting Equipment nested choices、Review、atomic Create Confirm、Version 1 + initial State |
| **P1-G — Level Up & Character Versions** | ⬜ | Level Up Draft、immutable Version N+1、Version History、stale base guard、State reconciliation、correction/build edit |
| **P1-H — Full P1 Integration & Closeout** | ⬜ | P1 full regression、Create / high-level / multiclass / caster / Level Up E2E、P0 regression、closeout |

P1-B 已完成實作與驗收；P1-C 是下一個可實作 Subphase，但未獲使用者明確要求前不開始 P1-C coding。

---

## P0 / P1 邊界

### P0 — Character Core + SRD / Rules Foundation

P0 建立後續角色系統共用的正式內容與角色地基：

- Character-Relevant SRD 5.1 reference data。
- Character 核心資料與保存／載入能力。
- immutable Character Build Version / mutable Current State。
- Character Sheet authoritative calculations。
- Current State APIs / UI。
- Build / State isolation。
- 可承載 Human Fighter 5 / Wizard 5 Character Level 10。

P0 不負責從 UI 合法地一級一級建立該角色。

P0 正式文件：

```text
docs/P0/實作規格.md
docs/P0/開發設計方針.md
docs/P0/測試指南.md
```

### P1 — Character Builder Complete

P1 把「角色資料能存在」提升成「網站能依 D&D 5e 2014 規則建立與成長角色」。

核心驗證案例包括：

- 從空白建立合法 Lv1 角色。
- 直接建立高等角色，但保存完整逐級 progression。
- 建立 Fighter 5 / Wizard 5 等 Multiclass 角色，不直接改底層資料。
- 正確處理 Subclass、ASI / Feat、Spell progression、Starting Equipment。
- Existing Character 可 Level Up 並產生新 immutable Build Version，Current State依規則 reconciliation。

P1 正式文件：

```text
docs/P1/實作規格.md
docs/P1/開發設計方針.md
docs/P1/測試指南.md
```

---

## P4 已知承接項目

這不是 P4 的提前實作設計，只是 P0 scope cut 的**跨 Phase 承接契約**：

- P4 的第一個 Subphase 命名為 **P4-A**。
- P4-A 必須承接 P0 明確延後的 **SRD 5.1 Monster / Beast stat blocks**。
- P4-A 開工時再依當時 Combat Engine 需求決定 Monster Template schema、actions / attacks / spellcasting representation、validation 與 API。
- P0 / P1 不為此提前建立 Monster-specific schema / validation / combat data。

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

目前：

```text
docs/
├── P0/
│   ├── 實作規格.md
│   ├── 開發設計方針.md
│   └── 測試指南.md
└── P1/
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
讀當時真正存在的 codebase
↓
拆成可獨立實作 / 驗證 / commit 的 Subphases
↓
同時寫 docs/Px/ 三份對齊文件
↓
使用者明確要求後才開始 coding
```

Subphase 只拆當前 Phase；例如目前只拆 P1，不拆 P2～P8。

可以保留必要的跨 Phase 相容性／承接要求，但**不要因此提前設計後續 Phase 的 schema / API / module**。

---

## 開發接手原則

新的 ChatGPT / Claude / Codex Session 或實作者進入專案時：

1. 先讀 `AGENTS.md`。
2. 再讀 `PROJECT_BRIEF.md` 取得目前 Phase、Subphase 與下一步。
3. 按任務讀 `規格企劃.md` 對應章節。
4. P1 實作／驗收依 Subphase id 讀 `docs/P1/實作規格.md`、`開發設計方針.md`、`測試指南.md` 的同名段落；必要時再回看 P0 相容契約。
5. 不重新討論已定案產品規格。
6. 不為還沒開工的 Phase 預先設計具體實作。
7. **未獲使用者明確要求，不開始 coding。**