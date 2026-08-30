# Adventure Table 專案簡報

本文件供新的 ChatGPT / Claude / Codex Session 或實作者快速了解專案全貌；需要產品細節時再深入 `規格企劃.md` 與對應 Phase 文件。

**本檔負責：專案概述、當前進度、大 Phase Roadmap、當前 Phase 的 Subphase 進度、下一步與文件索引。**

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
Built-in Content：**SRD 5.1 為基礎，非 SRD 內容依私人專案需求逐步加入**  
專案性質：**朋友間私人使用，非預計商品化平台**

完整產品規格見：`規格企劃.md`。

---

## 當前進度

目前狀態：**P0 — Character Core + SRD / Rules Foundation 與 P1 — Character Builder Complete 均已完成並關門。P1-A～P1-H 全部完成；網站現在能從空白 Builder Draft 建立 Lv1 或高等角色，保存完整 level-by-level progression / Multiclass / Subclass / ASI / Feat / Spellcasting / Starting Equipment，原子建立 Character + immutable Build Version 1 + initial Current State；Existing Character 也能進行 Level Up，建立 immutable Version N+1、reconcile live Current State，並查看 Version History。**

目前進行 **M01 — Multi-Source Character Content Expansion**。M01 是第一個 Maintenance / Modification Phase，用來補資料、補設定與強化既有 Character Content 能力，不改寫正常 P0 → P1 → P2 Roadmap。**M01-A 與 M01-B 已完成並關門（含 M01-B 真人創角 Gate）；M01-C～M01-J 尚未開工。**

M01 的直接目標：

- 將單一 `srd5.1` Content Registry 升級成 Multi-Source Content Pack。（M01-A ✅）
- 補 PHB 非 SRD Background / race / subrace / Variant Human。（M01-B ✅）
- M01-B 完成後先進行第一輪真人創角測試。（✅ 已執行）
- 再補 SCAG / GoS Background、VGM race、SCAG Half-Elf variant、VRGR Dhampir、TCE Artificer、TCE magic items。
- M01 closeout 後回到 P2 規劃。

**M01-C closeout 後，M01 暫停，插入 M02 — Traditional Chinese / English Localization；M02 closeout 後回到 M01-D。**

> **下一個 coding step 是 M01-C — SCAG / GoS Background Expansion。只有在使用者明確要求後才 coding。M01-C 完成後先做 M02-A～M02-H，再回 M01-D～M01-J，最後才回到 P2 — Room / Campaign / Session / Seat 的規劃。不得因 M01 / M02 提前拆 P2～P8。**

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
- 新增 M Phase 規則：**M01、M02… 用於補資料／補設定、既有能力加強或 migration；可插在正常 P Phase 之間，也可插在另一個 M Phase 的 Subphase 之間，但不改寫正常 P Roadmap。**
- M01-A～M01-J 三份正式文件已完成。
- M02-A～M02-H 三份正式文件已完成。
- 基礎技術棧：React + TypeScript + Vite / Python + FastAPI / PostgreSQL。

---

## P0 已完成

- **P0-A — Project Foundation**：React/TypeScript/Vite、FastAPI、PostgreSQL、SQLAlchemy/Alembic、Docker Compose、pytest/Vitest/Playwright 與 CI baseline。
- **P0-B — Character-Relevant SRD Foundation**：`data/srd5.1/` normalized content、ContentRegistry、stable keys、schema / cross-reference validation；Monster / Beast 延後 P4-A。
- **P0-C — Character Core & Persistence**：Character identity、immutable Build Version、mutable Current State、`characters` / `character_versions` / `character_states`、Fighter 5 / Wizard 5 deterministic fixture。
- **P0-D — Character Rules & Backend API**：Ability/PB/Skill/Save/Passive/AC/HP/Spell calculations、Numeric Override、CharacterSheetDTO、Reference / Character / State APIs。
- **P0-E — Character Sheet & State UI**：三頁 Character Sheet、responsive UI、searchable accessible selectors、HP / Temp HP / Conditions / Prepared / resources / Hit Dice / Inventory state operations。
- **P0-F — Full P0 Integration & Closeout**：P0 full regression、real backend Playwright、PostgreSQL restart persistence、Prepared / Hit Dice reload、Starting Equipment / live Inventory isolation、人工 smoke。

---

## P1 規劃與共通契約

正式文件：

- `docs/P1/實作規格.md`
- `docs/P1/開發設計方針.md`
- `docs/P1/測試指南.md`

三份文件使用完全一致的 P1-A～P1-H 名稱與順序。

P1 共通原則：

- P1 直接延伸 P0 已存在的 `CharacterBuild` / `CharacterState` / immutable JSONB Build Version / Current State / ContentRegistry / Rules Layer，不重新設計第二套 Character core。
- Builder Draft 與正式 `CharacterBuild` 明確分離；不完整 Draft 可以保存，正式 Build 不可以是假資料。
- Ability generation：Standard Array / Point Buy / Manual Input；P1 不提前做正式 Roll System。
- Lv2+ HP：Fixed Average / Manual Rolled Result；P1 不做正式 `Roll HP`。
- Starting Equipment 做完整 structured choices；P1 不做 Starting Gold shopping workflow。
- Spell access identity 與 live prepared state / resource usage 分離。
- Level Up Current State reconciliation：保留 damage delta、舊資源消耗不回滿、新 Hit Die 可用、Prepared 合法者保留、Inventory / Conditions 等 live state 延續。
- Character JSON Import / Export 留 P7；Builder MCP / AI transport 留後續對應 Phase。
- Human UI 與未來 AI Tool 應共用同一 server-authoritative Builder domain，不在 React 複製規則引擎。

---

## P1-A～P1-H 已完成內容

### P1-A — Builder Domain & Draft Foundation

- 建立獨立 `character_builder` domain；不把不完整資料塞進正式 `CharacterBuild`。
- 新增 `character_build_drafts` persistence / Alembic migration。
- Draft 支援 Save / Reload / Cancel 與 revision optimistic guard。
- 建立 strict Draft / Choice / Validation DTO，validation issue 使用 machine-readable `code` / `severity` / `path` / `message`。
- Choice ID deterministic。
- 新增 `/api/character-builder/drafts` lifecycle API 與 typed frontend API。

### P1-B — Character Creation Basics

- 新增 `/characters` Character Workshop，可查看 Existing Characters、建立新 Draft、Resume Draft 與開啟 Character Sheet。
- 完成 Basic / Origin / Abilities。
- Race / Subrace / Background / Alignment 與 starting choices 由 server-generated choices 驅動。
- Ability generation 支援 Standard Array / Point Buy / Manual Input。
- Base / permanent grants / resolved / effective ability 與 Numeric Override 保持分離。
- Searchable accessible selectors 延續 P0 UI pattern。

### P1-C — Class Progression & Multiclass

- 建立 ordered level-by-level progression engine，Character Level 與 Class Level 分離 derive。
- Starting class grants 與 multiclass grants 分離。
- Multiclass prerequisites 由 server structural validation enforce，使用 effective ability scores。
- Subclass timing 依 Class Level 驗證。
- HP progression 支援 First Level / Fixed Average / Manual Rolled Result。
- 新增 level-by-level rail UI。

### P1-D — ASI, Feat & Structural Choices

- 新增 generic structural choice resolver，支援 choose-N proficiency、language、tool / weapon / armor、fighting style、nested feature choice 與 ASI-or-Feat branch。
- ASI eligibility 依 Class Level progression 判定；永久能力變化只編譯進 Build 一次。
- Feat prerequisite 為 server structural validation。
- Numeric Override 可影響 numeric prerequisite，但不能繞過 structural rule。
- Level rail 呈現 ASI / Feat 與 structural choices。

### P1-E — Spellcasting Progression

- 建立 source-aware spellcasting profiles，Build 保存來源身份與 eligibility，不把 daily prepared state 塞回 immutable Build access。
- 支援 Known、Spellbook、Prepared caster 與 subclass Always Prepared source。
- Wizard Spellbook 與 Current State prepared list 分離；Prepared caster 不把整張 class spell list materialize 進 Build。
- 同一 spell 可保留不同 source identity。
- 支援 normal spell slots、full / half caster multiclass contribution 與 Pact Magic 獨立 resource pool。
- Build spell resource capacity 與 live `used + remaining == capacity` invariant 分離。
- Character Builder Step 05 已完成 Spellcasting access / preparation / resource summary UI。

### P1-F — Equipment, Review & Character Creation

- 新增 SRD-driven Starting Equipment resolver：automatic grants、A/B branch、nested choices、equipment category 與 quantity。
- Starting Equipment 只從 starting class + background 規則取得；**Starting Gold 不建立購物流程。**
- Starting equipment Build entry ID deterministic；live Inventory 只在 Create Confirm 初始化一次，之後不會從 Build 重建覆蓋玩家修改。
- `starting_equipment_choices` 與 generic `choice_selections` namespace 分離；跨 namespace 誤值不會被當成有效 Build choice。
- 過期的 nested equipment branch selection 不參與 Build，只提示 warning；目前有效 branch 的非法／未完成 choice 仍是 blocking。
- 新增 server-derived Review DTO，Review 同時顯示 immutable Build candidate 與 initial Current State preview。
- initial Current State 包含：full HP、0 Temp HP、empty Conditions、Hit Dice、Prepared Spells、Spell Resource counters 與 Starting Inventory。
- 新增 Review / Confirm API；warning / non-standard 可 Confirm，blocking error 不可 Confirm。
- Confirm 以單一 DB transaction 建立 `Character + immutable Version 1 + Current State + draft confirmation marker`；任一步失敗整筆 rollback。
- Confirm 使用實際 reviewed Draft revision，避免 concurrent Draft edit 讓舊 Build 配新 revision 落庫。
- repeated / double-submit Confirm idempotent，回傳同一 Character，不建立第二隻。
- Character Version metadata baseline 已加入 `version_kind`（`legacy` / `create`）、nullable lineage fields 與 `change_note`，供 P1-G 延伸。
- Character Builder Step 06 已完成 Equipment / Review / Confirm；成功後直接進既有 Character Sheet。
- P1-F regression 覆蓋 equipment deterministic resolution、nested category、quantities、Starting Gold exclusion、Review、initial State、double-submit、Version 1 metadata、inventory isolation 與 forced transaction rollback。
- real-browser closeout 覆蓋從 Character Workshop 建立 Lv1 角色、Starting Equipment、Review、Confirm 到 Character Sheet 的完整 Create flow。

### P1-G — Level Up & Character Versions

- Existing Character 可建立 versioned Builder Draft，Draft 明確綁定 `base_version_id`，不直接修改既有 immutable Build。
- Level Up Confirm append immutable Version N+1，保存 parent / superseded lineage 與 `version_kind`；Version 1 永不覆寫。
- stale base version 由 server 阻擋，避免兩個舊 Draft 同時覆蓋目前 Build。
- Level Up Review 同時產生 Build candidate 與 Current State reconciliation preview。
- reconciliation 保留既有 damage delta、Temporary HP、Conditions、Inventory 與合法 Prepared；既有資源不因升級自動回滿，新取得 Hit Die / capacity 依規則增加。
- Starting Equipment 只保留 Build provenance；Level Up 不從 starting equipment 重建 live Inventory。
- Character Workshop 提供 Level Up / Edit Build / Correct Build / Version History 入口；Version History 清楚區分 immutable Build history 與 live Current State。
- real-backend Playwright 覆蓋 Lv1 Barbarian → Lv2、HP damage-delta reconciliation、Temp HP / Inventory preservation、Hit Die 增加與 Version 1 / 2 history。

### P1-H — Full P1 Integration & Closeout

- CI 升級為 **P1 Full Regression**：backend pytest、fresh Alembic、P0 schema → P1 head migration、frontend build / Vitest、Docker full stack、Playwright、restart persistence 全部納入同一 gate。
- P0 → P1 migration 會先在真正 P0 schema 寫入 legacy Fighter 5 / Wizard 5 Character，再升到 head，驗證 Build / Current State 不變且 P1 metadata / Draft schema 正確補齊。
- 新增 direct high-level real-backend E2E：從 UI 建立 **Fighter 5 / Wizard 5 Character Level 10**，完整經過 progression、Subclass、ASI、Spellbook、Starting Equipment、Review、Confirm，並驗證正式 Build v1 / initial Current State。
- 高等 Create E2E 明確等待 server-persisted Draft revision，並驗證 browser reload 後 progression 不遺失。
- P1 full flow 保留既有 Lv1 Create、Level Up / Version History 與 P0 Character Sheet regression，共 **15 個 Playwright flows 全綠**。
- server restart 驗證同時覆蓋 P0 Character Current State、P1 active Builder Draft、P1 Level-Up Character v2、Version History 與 Current State，重啟前後資料一致。
- closeout smoke artifact 覆蓋 Workshop、Level Rail desktop/mobile、Spellcasting / searchable spell selector、Review、Character Sheet、Level Up reconciliation、Version History；人工檢視並修正 Version History badge positioning 回歸。
- P1-H 不新增 P2 system；P1 關門後停在 P2 規劃邊界。

---

## M01 規劃與共通契約

M01 正式文件：

- `docs/M01/實作規格.md`
- `docs/M01/開發設計方針.md`
- `docs/M01/測試指南.md`

M01 共通原則：

- M Phase 專門承接資料補完、既有架構加強與 migration，不改寫正常產品 Phase 編號。
- `docs/暫用規則資訊/` 是人類參考來源，不是 runtime data source。
- 正式 runtime 內容進 `data/<pack>/`，由 Content Registry 驗證與載入。
- StableKey 維持 `<pack_id>:<kind>:<index>`；`srd5.1:*` 舊 key 不改名。
- `content_sources` 要成為真正可驗證的 Build provenance。
- 不為 SCAG / Dhampir / Artificer 各做一套 Builder；優先延伸既有 generic choice / progression / rules 模型。
- 複雜 runtime effect 若需要未來 Combat / Rest context，可以明確標為 manual/deferred，但 structural rule / capacity / identity 必須先正確。
- M01-B 是第一個真人創角 Gate；Gate blocker 必須在 M01-B closeout前修完並補 regression。

---

## M01 Subphase 進度

狀態：📐 規格可實作；⬜ 尚未開工；🚧 進行中；✅ 完成。

| Subphase | 狀態 | 重點 |
|---|---|---|
| **M01-A — Multi-Source Content Pack Foundation** | ✅ | 泛化 Content Pack / StableKey / registry / cross-reference / `content_sources`，維持 SRD compatibility |
| **M01-B — PHB Character Origins & Background Expansion** | ✅ | PHB Background、PHB 非 SRD subrace、Variant Human；真人創角 Gate 已執行並關門 |
| **M01-C — SCAG / GoS Background Expansion** | 📐 | SCAG / GoS Background、source collision、background variant / replacement 最小支援 |
| **M01-D — VGM Race Expansion** | 📐 | Goblin / Hobgoblin / Aasimar、level-gated racial features / resource metadata |
| **M01-E — SCAG Half-Elf Variant & Grant Replacement** | 📐 | Half-Elf ancestry variants、最小通用 Grant Replacement、stale branch isolation |
| **M01-F — VRGR Lineage & Dhampir** | 📐 | Lineage、Dhampir、Ancestral Legacy、既有角色 versioned transformation |
| **M01-G — TCE Artificer Core** | 📐 | Artificer progression / spellcasting / subclass；multiclass half-caster ceil rounding |
| **M01-H — TCE Artificer Advanced Features & Infusions** | 📐 | Infusion known vs active state、feature resources、attunement capacity、advanced feature boundary |
| **M01-I — TCE Magic Items** | 📐 | TCE item registry、rarity / attunement / restrictions / charges、manual-effect fallback |
| **M01-J — Full M01 Integration & Closeout** | 📐 | all-pack validation、P0/P1 regression、full E2E、restart persistence、真人 Gate recheck |

**M01-A、M01-B 已完成並關門。下一個可開工 Subphase 是 M01-C；M01-C closeout 後暫停 M01，先做 M02，再回 M01-D。**

---

## M02 規劃與共通契約

M02 正式文件：

- `docs/M02/實作規格.md`
- `docs/M02/開發設計方針.md`
- `docs/M02/測試指南.md`

M02 插入時點：**M01-C closeout 後暫停 M01；M02 closeout 後回到 M01-D。**

M02 共通原則：

- 第一版只支援兩個 locale：`zh-TW`、`en`；無既存偏好時預設 `zh-TW`。
- 兩者都是純語言模式，正常流程不得出現可避免的中英混合 system / rules presentation。
- locale 是 browser presentation preference，**不得寫入 Draft / CharacterBuild / CharacterState / Version metadata**。
- 切換語言即時 rerender，不 reload、不 navigation、不觸發任何 Draft / Character mutation。
- Rules identity（StableKey / refs / choice id / provenance）永遠不因翻譯改變；Display Name 不是 foreign key。
- Localization 是 presentation overlay，不得複製出第二套會各自演化的 mechanics content。
- 缺翻譯不得以 silent fallback 當成完成；completeness gate 必須能讓 CI 失敗。
- 使用者自行輸入的自由文字不翻譯、不因切換語言被改寫。
- M02 closeout 涵蓋當時 enabled packs：`srd5.1`、`phb2014`、`scag`、`gos`。
- **M02 closeout 後成為永久規則：任何後續 Subphase 新增或修改 user-visible system / rules content，必須同步提供所有正式 supported locale，缺一語即視為該 Subphase 未完成。**

---

## M02 Subphase 進度

狀態：📐 規格可實作；⬜ 尚未開工；🚧 進行中；✅ 完成。

| Subphase | 狀態 | 重點 |
|---|---|---|
| **M02-A — Locale Foundation & Runtime Switch** | 📐 | 全站單一 locale state、一鍵切換、browser 記憶、不動 Draft / Character domain state |
| **M02-B — Full UI Copy Localization** | 📐 | 既有 frontend UI copy 全部進 localization resources，含 accessibility text |
| **M02-C — Localized Content Model & Terminology Contract** | 📐 | canonical / overlay 邊界、localized content resolver、roleplay suggestion identity、glossary 定稿 |
| **M02-D — SRD 5.1 Names & Structured Text** | 📐 | SRD 名稱與短型／結構型 presentation 雙語覆蓋 |
| **M02-E — SRD 5.1 Full Descriptions** | 📐 | SRD 長篇規則說明雙語覆蓋，不改 mechanics semantics |
| **M02-F — PHB / SCAG / GoS Localization** | 📐 | M01-B / M01-C 導入的非 SRD content 雙語覆蓋 |
| **M02-G — Localized Search, Errors & Completeness Gates** | 📐 | localized search / alias / sort、error code + localized message、machine-verifiable completeness gate |
| **M02-H — Full M02 Integration & Closeout** | 📐 | 全站雙語驗收、Draft-safe switch、completeness final gate、真人 browser gate |

**M02 全部仍未 coding。M02 要在 M01-C closeout 後才開工。**

---

## Phase Roadmap

> 原則：先把角色與規則資料做完整，再把角色帶進桌內；每個 Phase 準備開工時才設計該 Phase 的細節。

| Phase | 主題 | 重點 |
|---|---|---|
| **P0** | **Character Core + SRD / Rules Foundation** | 導入角色真正需要的 SRD 5.1 reference content；建立 Character 核心資料、角色卡與角色相關規則計算基礎。**不導入 Monster / Beast stat blocks。** |
| **P1** | **Character Builder Complete** | 完整創角、高等角色建立、Level-by-level progression、Subclass、Multiclass、ASI / Feat、Spell progression、Level Up、Character Version |
| **M01** | **Multi-Source Character Content Expansion** | 插入式 Maintenance Phase：多來源 Content Pack、PHB/SCAG/GoS/VGM/VRGR/TCE 角色內容與既有 Character 系統強化；完成後回到 P2 |
| **M02** | **Traditional Chinese / English Localization** | 插入於 M01-C 與 M01-D 之間的 Maintenance Phase：`zh-TW` / `en` 雙語 foundation、全站 UI 與 SRD/PHB/SCAG/GoS content 翻譯、completeness gate；完成後回到 M01-D |
| **P2** | **Room / Campaign / Session / Seat** | 把已建立的角色真正放進桌內；建立 Room、Campaign、Party Roster、Player Seat、Controller 與 Session lifecycle |
| **P3** | **Exploration + Roll + AI** | 建立 Exploration、Chat / Action / Check、正式骰子與 PendingAction；Human / AI 開始能在同一桌真正跑團 |
| **P4** | **Quick Combat** | 第一個完整可玩的 Combat MVP；**P4-A 必須先承接 P0 延後的 SRD Monster / Beast stat blocks。** |
| **P5** | **Tactical Combat** | 在同一 Combat Engine 上增加 Grid、Battle Map、Movement、Range、AoE、Wall / Door / Terrain、Automatic OA 等空間系統 |
| **P6** | **Adventure + AI DM Runtime** | Adventure Definition / Importer、Campaign Runtime、World State、NPC / Scene / Fact、AI DM context 與 write-back |
| **P7** | **Snapshot / Export** | Timeline、Snapshot / Restore、Archive lifecycle、Character / Adventure / Campaign / Room Import / Export；不做 Undo 機制 |
| **P8** | **QA / Polish** | 全流程整合測試、權限與 AI reconnect、錯誤處理、效能、Responsive UI、UX polish 與第一版收尾 |

P0/P1 已完成；**目前已拆 M01 與 M02。P2～P8 仍維持大 Phase，不提前拆。**

實際執行順序：

```text
M01-A ✅ → M01-B ✅ → M01-C → M02-A～M02-H → M01-D～M01-J → P2
```

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

> **子階段一律一列一個，不得合併。**

| Subphase | 狀態 | 重點 |
|---|---|---|
| **P1-A — Builder Domain & Draft Foundation** | ✅ | Builder Draft、choice model、compiler / validation、draft persistence；不完整 Draft 不污染正式 Character |
| **P1-B — Character Creation Basics** | ✅ | Character Workshop、Wizard basics、Race/Subrace、Background、Standard Array / Point Buy / Manual、starting skills/proficiencies |
| **P1-C — Class Progression & Multiclass** | ✅ | Level-by-level rail、starting class、multiclass prerequisites / grants、Subclass timing、HP progression |
| **P1-D — ASI, Feat & Structural Choices** | ✅ | ASI / Feat timing、prerequisites、generic structural choice resolver、Numeric Override boundary |
| **P1-E — Spellcasting Progression** | ✅ | Known / Spellbook / Prepared / Always Prepared、multiclass slots、Pact Magic、source profiles |
| **P1-F — Equipment, Review & Character Creation** | ✅ | Starting Equipment nested choices、Review、atomic Create Confirm、Version 1 + initial State |
| **P1-G — Level Up & Character Versions** | ✅ | Level Up Draft、immutable Version N+1、Version History、stale base guard、State reconciliation、correction/build edit |
| **P1-H — Full P1 Integration & Closeout** | ✅ | P1 full regression、Create / high-level / multiclass / caster / Level Up E2E、P0 regression、migration / restart persistence / smoke closeout |

---

## P0 / P1 / M01 / M02 邊界

### P0 — Character Core + SRD / Rules Foundation

P0 建立正式 SRD / Character 地基：Character content、immutable Build、mutable State、rules、Character Sheet、state UI。

### P1 — Character Builder Complete

P1 讓網站可以依 D&D 5e 2014 structural rules 建立／升級角色，並保存 versioned Build。

### M01 — Multi-Source Character Content Expansion

M01 不重做 P0/P1；它把「SRD 可創角」提升成「既有 Builder 可以承載逐步加入的多來源內容」。M01 主要增加：

- Content Pack foundation。
- PHB / SCAG / GoS / VGM / VRGR / TCE 本次已提供角色資料。
- replacement / lineage / Artificer 等為這些內容真正需要的最小通用能力。
- M01-B 真人創角測試 Gate。

M01 正式文件：

```text
docs/M01/實作規格.md
docs/M01/開發設計方針.md
docs/M01/測試指南.md
```

### M02 — Traditional Chinese / English Localization

M02 不加規則內容、不改 mechanics；它把「網站只有單一（且目前中英混用）presentation」提升成「同一份 rules identity 可以用 `zh-TW` / `en` 兩種純語言模式呈現」。M02 主要增加：

- 全站 locale runtime state 與瀏覽器記憶。
- UI copy 與 rules content 的 localization boundary 與 resolver。
- roleplay suggestion identity（取代目前只靠英文原句當身份）。
- D&D 5e 2014 en ↔ zh-TW glossary。
- localized search / sort / error presentation。
- machine-verifiable translation completeness gate。

M02 正式文件：

```text
docs/M02/實作規格.md
docs/M02/開發設計方針.md
docs/M02/測試指南.md
```

---

## P4 已知承接項目

這不是 P4 的提前實作設計，只是 P0 scope cut 的**跨 Phase 承接契約**：

- P4 的第一個 Subphase 命名為 **P4-A**。
- P4-A 必須承接 P0 明確延後的 **SRD 5.1 Monster / Beast stat blocks**。
- P4-A 開工時再依當時 Combat Engine 需求決定 Monster Template schema、actions / attacks / spellcasting representation、validation 與 API。
- P0 / P1 / M01 不為此提前建立 Monster-specific schema / validation / combat data。

---

## 文件分工

| 文件 | 責任 |
|---|---|
| **`AGENTS.md`** | Agent 開工規則、P/M Phase / Subphase 規則、文件查閱方式、修改與驗證守則 |
| **`PROJECT_BRIEF.md`** | 專案總覽、當前 Phase / Subphase、Roadmap、下一步、文件索引 |
| **`規格企劃.md`** | 產品定位、跑團方式、Human / AI 行為、角色、戰鬥、Adventure、UI/UX 與產品單一事實來源 |
| **`技術棧討論.md`** | 暫時性的基礎技術選型討論；不負責各 Phase 的實作設計 |
| **`docs/Px/實作規格.md` / `docs/Mxx/實作規格.md`** | 該 Phase / Subphase 必須做到什麼、驗收意圖 |
| **`docs/Px/開發設計方針.md` / `docs/Mxx/開發設計方針.md`** | 該 Phase / Subphase 實際怎麼做：資料模型、模組、API、資料流與必要技術決策 |
| **`docs/Px/測試指南.md` / `docs/Mxx/測試指南.md`** | 該 Phase / Subphase 的自動／人工驗收流程 |

目前：

```text
docs/
├── P0/
│   ├── 實作規格.md
│   ├── 開發設計方針.md
│   └── 測試指南.md
├── P1/
│   ├── 實作規格.md
│   ├── 開發設計方針.md
│   └── 測試指南.md
├── M01/
│   ├── 實作規格.md
│   ├── 開發設計方針.md
│   ├── 測試指南.md
│   ├── M01-B_CLOSEOUT.md
│   └── M01-B_HUMAN_GATE.md
├── M02/
│   ├── 實作規格.md
│   ├── 開發設計方針.md
│   └── 測試指南.md
└── 暫用規則資訊/
```

---

## Phase 規劃規則

正常 P Phase 準備開工時：

```text
確認產品目標
↓
讀當時真正存在的 codebase
↓
拆 P<n>-A / B / ...
↓
同時寫 docs/P<n>/ 三份對齊文件
↓
使用者明確要求後才 coding
```

M Phase 使用同樣流程，但命名為：

```text
M01 / M02 / ...
↓
M01-A / M01-B / ...
```

M Phase 可以插在 P Phase 之間，**也可以插在另一個 M Phase 的兩個 Subphase 之間**（例如 M02 插在 M01-C 與 M01-D 之間）；**不會把 P2 重新編號，也不代表後續 P Phase 已經設計。**

被插入的 M Phase 保留原本的 Subphase 編號與順序，暫停後照原順序接續，不重新命名。

目前已拆 M01 與 M02；**P2～P8 不提前拆，M03 也不提前拆。**

---

## 開發接手原則

新的 ChatGPT / Claude / Codex Session 或實作者進入專案時：

1. 先讀 `AGENTS.md`。
2. 再讀 `PROJECT_BRIEF.md` 取得目前 Phase、Subphase 與下一步。
3. 按任務讀 `規格企劃.md` 對應章節。
4. M01 實作／驗收依 `docs/M01/`、M02 依 `docs/M02/` 三份文件中的同名 Subphase 取得契約。
5. 不重新討論已定案產品規格。
6. 不為 P2～P8 預先設計具體實作。
7. **未獲使用者明確要求，不開始 coding。**
