# Adventure Table 專案簡報

本文件供新的 ChatGPT / Claude / Codex Session 或實作者快速了解專案全貌；需要產品細節時再深入 `規格企劃.md` 與對應 Phase 文件。

**本檔負責：專案概述、當前進度、大 Phase Roadmap、目前正在準備的 P / M Phase、Subphase 進度、下一步與文件索引。**

最後更新：2026-08-30

---

## 專案概述

Adventure Table 是一個**輕量、桌上跑團優先的 D&D 5e 2014 VTT**。

核心方向：

- 真人 DM / Player 可以正常跑團。
- 外部 AI 可透過未來 MCP / Site Tools 正式加入桌內擔任 DM 或 Player。
- Human 與 AI 使用同一套 Game State / Game Actions。
- Server 是唯一真實狀態來源。
- 網站只處理需要共享、同步、計算、保存、權限控制或 AI 接入的資料。
- 不把產品做成 Foundry 式包山包海平台，也不把 D&D 做成 CRPG。
- 真人 DM 能靠口頭敘事完成的事情，不強迫建立結構化資料。
- 網站本身不接 LLM API；AI 能力來自使用者外部 AI Session。

首發規則集：**D&D 5e 2014**  
Content baseline：**SRD 5.1**；私人非 SRD Content Pack 依實際需求逐步加入  
專案性質：**朋友間私人使用，非預計商品化平台；repository 為 private**

完整產品規格見：`規格企劃.md`。

---

## 當前進度

目前：

- **P0 — Character Core + SRD / Rules Foundation：✅ 完成並關門。**
- **P1 — Character Builder Complete：✅ 完成並關門。**
- **M01 — D&D 5e 2014 Private Content Expansion：📐 M01-A～M01-J 三份正式規格已完成，尚未開始 coding。**
- **下一個可實作 Subphase：M01-A — Multi-Source Content Pack Foundation。**
- **下一個正常產品 Phase仍是 P2 — Room / Campaign / Session / Seat；M01 closeout 後回到 P2。**

> **未獲使用者明確要求開始 M01-A 前，不得自行 coding。M01 進行中不得同時偷跑 P2。**

P1 closeout後，網站已能：

- 從空白 Builder Draft 建立 Lv1 或高等角色。
- 保存完整 level-by-level Class progression。
- 支援 Multiclass / Subclass / ASI / Feat / Spellcasting / Starting Equipment。
- 原子建立 Character + immutable Build Version 1 + initial Current State。
- Existing Character 可 Level Up，建立 immutable Version N+1並 reconcile Current State。
- 查看 Build Version History。
- P0 Character Sheet / State persistence維持 regression green。

M01不是重做 Builder，而是把 SRD-only content foundation擴成 multi-source Content Pack，並把使用者已提供的 PHB / SCAG / GoS / VGM / VRGR / TCE 私人規則資料正式接進 P1 Builder / Character / Inventory。

---

## 已完成的大 Phase

### P0 — Character Core + SRD / Rules Foundation

已完成：

- **P0-A — Project Foundation**：React/TypeScript/Vite、FastAPI、PostgreSQL、SQLAlchemy/Alembic、Docker Compose、pytest/Vitest/Playwright、CI baseline。
- **P0-B — Character-Relevant SRD Foundation**：`data/srd5.1/` normalized content、ContentRegistry、StableKey、schema / cross-reference validation；Monster / Beast延後 P4-A。
- **P0-C — Character Core & Persistence**：Character identity、immutable Build Version、mutable Current State、persistence。
- **P0-D — Character Rules & Backend API**：Ability/PB/Skill/Save/Passive/AC/HP/Spell calculations、Numeric Override、DTO / APIs。
- **P0-E — Character Sheet & State UI**：Character Sheet、HP / Temp HP / Conditions / Prepared / resources / Hit Dice / Inventory state operations。
- **P0-F — Full P0 Integration & Closeout**：full regression、restart persistence、人工 smoke。

正式文件：

```text
docs/P0/實作規格.md
docs/P0/開發設計方針.md
docs/P0/測試指南.md
```

### P1 — Character Builder Complete

P1-A～P1-H全部完成並 closeout。

核心成果：

- Builder Draft與正式 `CharacterBuild`分離。
- Character Workshop / Create / Resume。
- Race / Subrace / Background / Alignment。
- Standard Array / Point Buy / Manual Input。
- ordered level-by-level Class progression。
- starting-class / multiclass grants與 prerequisite。
- Subclass timing。
- HP progression。
- generic structural choices。
- ASI / Feat / prerequisite。
- Known / Prepared / Spellbook / Always Prepared與 source-aware spell access。
- normal multiclass spell slots + Pact Magic。
- Starting Equipment nested choices。
- Review / atomic Confirm。
- Character + immutable Version 1 + initial Current State。
- Existing Character Level Up / Build Edit / Correction。
- immutable Version N+1 / Version History。
- Current State reconciliation。
- P0 → P1 migration / restart persistence / real-backend E2E。

P1 full closeout時已有 15 個 real-backend Playwright flows維持 green。

正式文件：

```text
docs/P1/實作規格.md
docs/P1/開發設計方針.md
docs/P1/測試指南.md
```

---

## M Phase — Modification / Maintenance Track

M Phase使用與正常產品 P Phase分離的編號軸：

```text
正常產品：P0 → P1 → P2 → P3 → ... → P8
                  ↑
                M01
```

M Phase適用於：

- 補資料／補規則內容。
- 強化已完成系統的可擴充性。
- 為新提供資料增加必要規則表示能力。
- migration / normalization / technical hardening。
- 已完成 Phase在真實使用時暴露出的既有系統缺口。

M Phase不得偷跑未開始的正常產品 Phase。

M Phase與 P Phase一樣：

- coding前必須拆成可獨立實作、驗證、commit的 Subphases。
- 三份正式文件 Subphase名稱／順序必須一致。
- 只拆目前 M Phase；不提前拆 M02/M03。
- 每個 Subphase closeout維持完成 Phase regression green。

命名：

```text
M01-A
M01-B
...
```

---

## M01 — D&D 5e 2014 Private Content Expansion

### 正式文件

```text
docs/M01/實作規格.md
docs/M01/開發設計方針.md
docs/M01/測試指南.md
```

三份文件已完整規劃 **M01-A～M01-J**；不是只規劃到 M01-B。

### M01 supplied references

```text
docs/暫用規則資訊/
├── 種族_PHB_非SRD內容.md
├── 背景_PHB.md
├── 背景_SCAG.md
├── 背景_GoS.md
├── 半精靈變體_SCAG.md
├── 地精_VGM.md
├── 大地精_VGM.md
├── 阿斯莫_VGM.md
├── 半血裔_VRGR.md
├── 奇械師_TCE.md
└── 魔法物品_TCE.md
```

這些是 human / maintainer reference；runtime正式資料放 `data/<content-pack>/`。

### M01 核心架構決策

- StableKey：`<pack-id>:<kind>:<index>`。
- 現有 `srd5.1:*` key全部保持不變。
- non-SRD pack與 SRD分離。
- M01至少使用：`phb2014` / `scag` / `gos` / `vgm` / `vrgr` / `tce`。
- Registry可同時載入多個 pack與 cross-pack refs。
- `CharacterBuild.content_sources`由 server compiler derive。
- new non-SRD data用 explicit stable refs；legacy SRD `/api/2014/...`仍相容。
- Variant / Lineage / Artificer / Item新增的規則只做目前 supplied資料需要的通用 primitive，不建立 generic scripting DSL。
- 複雜 Combat / Rest / day-clock效果可保存 structured metadata + manual marker，不提前做對應未來 subsystem。

---

## M01 Subphase 進度

狀態：📐 規格可實作；⬜ 尚未規劃；🚧 進行中；✅ 完成。

> **每個 Subphase一列。M01-A～M01-J都已完整寫入三份文件。M01-B結束會先做第一次真人創角 Gate，但 M01仍繼續 C～J。**

| Subphase | 狀態 | 重點 |
|---|---|---|
| **M01-A — Multi-Source Content Pack Foundation** | 📐 | 泛化 ContentEntry / manifest / StableKey / ContentRegistry / cross-pack refs / Build provenance；集中 legacy SRD reference normalization；保持 P0/P1 compatibility |
| **M01-B — PHB Background & Core Race Completion** | 📐 | PHB 13 core backgrounds + 5 variants、PHB missing subraces、Variant Human；完成後 mandatory First Real Character-Creation Gate |
| **M01-C — SCAG / GoS Background Expansion** | 📐 | SCAG 13 + GoS 4 backgrounds；multi-source background、roleplay table inheritance、variant/branch、source-aware UI |
| **M01-D — VGM Race Expansion** | 📐 | Goblin、Hobgoblin、Aasimar parent + Protector/Scourge/Fallen；racial level gates / limited-use resource metadata |
| **M01-E — SCAG Half-Elf Variant & Grant Replacement** | 📐 | 4 descents；`race-variant` identity；Skill Versatility replacement primitive；movement mode / racial magic |
| **M01-F — VRGR Lineage & Dhampir** | 📐 | `lineage` identity；direct create；Existing Character transformation；Ancestral Legacy whitelist；Vampiric Bite metadata；immutable Version N+1 |
| **M01-G — TCE Artificer Core** | 📐 | Lv1–20 class progression、starting/multiclass grants、four specialists、prepared spellcasting、Artificer half-ceil multiclass contribution、Level Up |
| **M01-H — TCE Artificer Advanced Rules & Infusions** | 📐 | Known Infusions(Build) vs active infusions(State)、capacity / item eligibility、class resources、Armor Model state、attunement progression、advanced subclass boundaries |
| **M01-I — TCE Magic Items** | 📐 | supplied 84 TCE items完整資料化；typed attunement requirements；Inventory attuned state；Artificer bypass/capacity；simple modifiers + manual-effect fallback |
| **M01-J — Full M01 Integration & Closeout** | 📐 | A～I整合；P1→M01 migration、full regression、real-backend E2E、restart persistence、desktop/mobile human smoke、manual/deferred automation report、文件關門 |

### M01-B 真人 Gate

M01-B closeout前，真人至少完整建立：

1. SRD regression角色。
2. PHB new subrace。
3. Variant Human。
4. 有 tool/language choice的 PHB Background。
5. martial。
6. caster。

Gate發現的 M01-A/B blocker / major UX confusion在 B closeout前修完；**不代表 C～J可以不做。**

---

## Phase Roadmap

> 正常 P Roadmap不因 M01改號；M01只是插入式 maintenance track。

| Phase | 主題 | 重點 |
|---|---|---|
| **P0** | **Character Core + SRD / Rules Foundation** | Character-relevant SRD 5.1、Character core、Sheet、State；Monster/Beast延後 P4-A |
| **P1** | **Character Builder Complete** | 完整創角、高等角色、progression、Subclass、Multiclass、ASI/Feat、Spells、Equipment、Level Up、Build Version |
| **P2** | **Room / Campaign / Session / Seat** | 把角色放進桌內；Room、Campaign、Party Roster、Seat、Controller、Session lifecycle |
| **P3** | **Exploration + Roll + AI** | Exploration、Chat/Action/Check、正式骰子、PendingAction；Human/AI共桌 |
| **P4** | **Quick Combat** | 第一個完整 Combat MVP；**P4-A先承接 SRD Monster / Beast stat blocks** |
| **P5** | **Tactical Combat** | Grid、Battle Map、Movement、Range、AoE、Wall/Door/Terrain、Automatic OA |
| **P6** | **Adventure + AI DM Runtime** | Adventure Definition / Importer、Campaign Runtime、NPC/Scene/Fact、AI context/write-back |
| **P7** | **Snapshot / Export** | Timeline、Snapshot/Restore、Archive lifecycle、Import/Export；不做 Undo |
| **P8** | **QA / Polish** | 全流程整合、權限/AI reconnect、錯誤、效能、Responsive、UX polish |

**P2～P8仍維持大 Phase，不提前拆。M01 closeout後才開始 P2規劃／Subphase拆分。**

---

## P4 已知承接項目

這只是跨 Phase承接契約，不是提前設計 P4：

- P4第一個 Subphase固定 **P4-A**。
- P4-A承接 P0延後的 SRD 5.1 Monster / Beast stat blocks。
- Monster Template schema/actions/combat data等到 P4-A按當時 Combat Engine需求設計。
- M01不得因為 VGM race / Artificer feature提到 combat就提前建立 Monster/Combat subsystem。

---

## 文件分工

| 文件 | 責任 |
|---|---|
| **`AGENTS.md`** | Agent開工規則、P/M Phase與Subphase規則、文件查閱、修改與驗證守則 |
| **`PROJECT_BRIEF.md`** | 專案總覽、當前 P/M Phase、Subphase進度、Roadmap、下一步、文件索引 |
| **`規格企劃.md`** | 產品定位、跑團方式、Human/AI行為、角色、戰鬥、Adventure、UI/UX產品單一事實來源 |
| **`技術棧討論.md`** | 基礎技術選型，不負責各 Phase implementation design |
| **`docs/Px/*`** | 正常產品 Phase的實作規格／開發設計／測試指南 |
| **`docs/Mxx/*`** | Modification / Maintenance Phase的實作規格／開發設計／測試指南 |
| **`docs/暫用規則資訊/*`** | 使用者提供的私人規則 human reference；不是 runtime Source of Truth |
| **`data/<pack>/`** | 正式 content runtime Source of Truth |

目前：

```text
docs/
├── P0/
├── P1/
├── M01/
│   ├── 實作規格.md
│   ├── 開發設計方針.md
│   └── 測試指南.md
└── 暫用規則資訊/
```

---

## Phase 規劃規則

正常 P Phase與 M Phase都固定走：

```text
確認 Phase目標
↓
讀當時真正存在的 codebase
↓
拆可獨立實作 / 驗證 / commit的 Subphases
↓
同時寫三份對齊文件
↓
使用者明確要求後才開始 coding
```

規則：

- P Phase：`P<n>-A`、`P<n>-B`…
- M Phase：`M<nn>-A`、`M<nn>-B`…
- 只拆當前 Phase。
- M Phase不改 P Roadmap號碼。
- 可以記必要 future compatibility / runtime metadata，但不提前建 future subsystem。

目前 M01-A～J已拆完，所以**不需要再重新規劃 M01；下一步若使用者說開始 M01-A，就直接讀 M01-A三份契約與最新 codebase後實作。**

---

## 開發接手原則

新的 ChatGPT / Claude / Codex Session：

1. 先讀 `AGENTS.md`。
2. 再讀 `PROJECT_BRIEF.md`。
3. 依任務讀 `規格企劃.md`對應產品章節。
4. 目前 M01已規劃，實作某個 M01 Subphase時只讀該 Subphase的三份對齊段落 + 必要共通前言。
5. 不重新討論已拍板：M Phase命名、M01-A～J拆法、M01-B真人 Gate、Variant Human納入 B。
6. 不提前做 P2。
7. 不把 non-SRD data塞回 `data/srd5.1/`。
8. **未獲使用者明確要求，不開始 coding。**
