# Adventure Table 專案簡報

本文件供新的 ChatGPT / Claude / Codex Session 或實作者快速了解專案全貌；需要產品細節時再深入 `規格企劃.md` 與對應 Phase 文件。

**本檔負責：專案概述、當前進度、大 Phase Roadmap、當前 Phase 的 Subphase 進度、下一步與文件索引。**

最後更新：2026-09-04

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

目前狀態：**P0 — Character Core + SRD / Rules Foundation、P1 — Character Builder Complete 與 M02 — Traditional Chinese / English Localization 均已完成並關門。P1-A～P1-H 全部完成；網站現在能從空白 Builder Draft 建立 Lv1 或高等角色，保存完整 level-by-level progression / Multiclass / Subclass / ASI / Feat / Spellcasting / Starting Equipment，原子建立 Character + immutable Build Version 1 + initial Current State；Existing Character 也能進行 Level Up，建立 immutable Version N+1、reconcile live Current State，並查看 Version History。**

**M01 — Multi-Source Character Content Expansion 已完成 M01-A～M01-M 並關門；M01 尚未 full closeout。** M01-A 建立 Multi-Source Content Pack；M01-B 補 PHB Character Origins / Background 並完成真人創角 Gate；M01-C 已補完 13 個 SCAG + 4 個 GoS Background；M01-D 已導入 Goblin / Hobgoblin / Aasimar；M01-E 已導入四種 SCAG Half-Elf ancestry variant、最小通用 Grant Replacement、movement modes、Drow Magic thresholds / resources 與 versioned Build Edit round-trip；M01-F 已導入 `lineage` StableKind 與 VRGR Dhampir、Ancestral Legacy whitelist 與既有角色的 versioned transformation；M01-G 已導入 TCE Artificer core、Lv1～20 progression、Specialists、prepared spellcasting 與 multiclass half-caster ceil rounding；M01-H 已導入 TCE Artificer Infusions / advanced feature state、Known vs Active Infusion boundary、feature resources、attunement capacity metadata、Armor Model live state、Spell-Storing Item state 與 manual combat-effect boundary；M01-I 已導入 TCE Optional Class Features / Fighting Styles、addition / expanded option pool / replacement / retraining semantics，以及 5 條 mandatory browser/full-stack E2E；M01-J 已導入 PHB / SCAG / XGE / TCE 四來源共 112 個 subclass identity（95 implemented + 17 canonical duplicate / reprint），並把 subclass 內容 materialize 成一般 pack data、移除 registry load 時的 Markdown 解析；M01-K 已導入 PHB 相對 SRD 缺少的 41 個 Feats 與 42 個 Spells，並接上 Feat structural mechanics、repeatable acquisition、prerequisite resolver、static derived values、Spell catalog / Builder integration 與 description localization；M01-L 已導入 VGM remaining 10 個 race 與 SCAG remaining 2 個 subrace，並把 generic Race/Subrace movement grant、signed racial ability modifier、Natural Armor Rules Layer primitive、racial spell canonical multi-rest recharge 與 typed runtime automation classification 補進既有 substrate；M01-M 已導入 `mtf` pack、7 個 MTF planar race identity 與 Tiefling 9/9 血脈，並一次定案 Tiefling replacement contract、race-variant group persistence、conditional movement 與 feature mode 的 Build / State 邊界。現行 enabled content packs 為 `srd5.1`、`phb2014`、`scag`、`gos`、`vgm`、`vrgr`、`tce`、`xge`、`mtf`。

M01 的直接目標：

- 將單一 `srd5.1` Content Registry 升級成 Multi-Source Content Pack。（M01-A ✅）
- 補 PHB 非 SRD Background / race / subrace / Variant Human。（M01-B ✅）
- M01-B 完成後先進行第一輪真人創角測試。（✅ 已執行）
- 補 SCAG / GoS Background。（M01-C ✅）
- 補 VGM race（M01-D ✅）、SCAG Half-Elf variant（M01-E ✅）、VRGR Dhampir（M01-F ✅）、TCE Artificer core（M01-G ✅）、TCE Artificer advanced features / Infusions（M01-H ✅）、TCE Optional Class Features / Fighting Styles（M01-I ✅）、PHB / SCAG / XGE / TCE 2014 Subclass（M01-J ✅）、PHB Feat / Spell Catalog（M01-K ✅）。
- **M01-K 已補 PHB 相對 SRD 缺少的 41 個 Feats 與 42 個 Spells，並把能由現有 substrate 表達的 Feat structural mechanics正式接進 Builder；Spell scope只做到 catalog / access / Builder integration，不提前建立完整 Spell Engine。**
- **M01-L — VGM & SCAG Remaining Race Expansion / Generic Race Mechanics 已完成並關門（2026-09-03）**；**M01-M — MTF Planar Race Expansion & Tiefling Bloodline / Variant System 亦已完成並關門（2026-09-03）**。
- M01-M 之後仍可能新增其他規則 Subphase；**Full M01 Integration & Closeout 暫不固定編號**，只有最終 M01 scope確定後才編號。
- **M01 不必先 full closeout 才能開始 M03。** 目前 M01 保持 open，後續仍可補資料或調整 UI；M03 先行實作。P2 仍須等 M03 closeout 與 M01 final closeout 後才正式開工。

**M03 — Standalone Character Builder Distribution 已正式開工。** M03-A — Content Root Path Abstraction & Enabled-Pack SSOT 目前為 🚧 進行中；正在把 content / rules / localization / database path 收斂到 resolver，並把 enabled pack 清單收斂到 `Settings.enabled_content_packs`。M03 是 P2 前的插入式 Maintenance Phase，目標是把現有 Character Workshop / Builder / Sheet / Level Up / Version History 打包成可離線執行的 standalone 版本，並加入 Character JSON Import / Export。M01 後續內容補充或 UI 調整不需要先 full closeout；只要不破壞 Character Build / State / Version / StableKey / Builder provenance 等 M03 核心契約，即可在 M03 後續繼續追加。

**M02 — Traditional Chinese / English Localization 已於 2026-08-31 closeout（M02-A～M02-H 全部完成）；M01-D～M01-M 亦已完成並關門。M01 尚未 full closeout；M 之後是否還有新 M01 規則 Subphase與 Full M01 Integration & Closeout 的 Subphase ID 仍由使用者後續拍板。**

**M02-A — Locale Foundation & Runtime Switch 已完成**：建立 typed `zh-TW` / `en` locale runtime、瀏覽器持久化偏好、全站一鍵切換器、`html` language metadata 與 M02-A regression 覆蓋（Vitest + Playwright spec）。locale 仍只是 presentation state，未寫入 Draft / Character domain。

**M02-B — Full UI Copy Localization 已完成**：既有 frontend-owned UI copy 已集中到 typed `zh-TW` / `en` localization resources；Landing、Character Workshop、Builder 七個具名 step、Review / Confirm、Character Sheet、Version History、LocaleSwitcher 與 SearchableSelect 均可即時切換，accessibility name / form label / placeholder / helper / loading / empty / confirmation copy 同步 locale；另加入 surface inventory、兩語 key parity、hardcoded presentation copy regression 與 real-browser 雙語 smoke。Rules/content DTO presentation 明確留給 M02-C～M02-F。

**M02-C — Localized Content Model & Terminology Contract 已完成**：canonical mechanics 與 presentation overlay 邊界確立，StableKey / refs / choice id 維持 locale-neutral；`ContentLocalizationCatalog` 依 StableKey + field path + locale 解析呈現文字；machine-readable field-level policy 落在 `data/localization/localizable-fields.json`，required 與 deferred 覆蓋範圍可枚舉可測；D&D 5e 2014 繁中術語 SSOT 落在 `data/localization/dnd5e-2014-glossary.json`；Background roleplay suggestion 採 deterministic locale-neutral identity，使用者自填文字維持原樣。詳見 `docs/M02/M02-C_CLOSEOUT.md`。

**M02-D — SRD 5.1 Names & Structured Text 已完成**：`srd5.1` policy-required name 欄位的 `zh-TW` overlay 已以 per-kind human-review shard 形式進 `data/srd5.1/locales/zh-TW/`，runtime 優先讀 shard；Builder 進程／裝備／法術／Character Sheet / Character Workshop 均改為以 StableKey 解析 locale presentation。1,635 個 StableKey／1,662 個 presentation field 的 completeness 與 zh-TW 名稱語言 gate 全綠，人工術語 review 已由專案 owner 接受；Docker server image 已正式封裝 localization data，authoring regression tests 也已接入 CI。非 SRD pack 的 zh-TW 覆蓋屬 M02-F scope。詳見 `docs/M02/M02-D_CLOSEOUT.md`。

**M02-E — SRD 5.1 Description Localization 已完成**：SRD 5.1 的 spell / feature / condition canonical `data.desc.*` 已以 StableKey + field path 的 zh-TW shards 全量 author；新增 canonical-driven exact coverage、English leakage、mechanics-sensitive token 與 Markdown table structure gates。這是依使用者明確要求提前完成高價值 SRD rules description corpus，**不改變** field policy 的 `currently_user_visible`，也不把 hidden item / background long-form corpus 拉入 M02-E。GitHub Actions 目前仍在 workflow step 執行前失敗，因此本分支不宣稱 full regression 已跑綠；詳見 `docs/M02/M02-E_CLOSEOUT.md`。

**M02-F — PHB / SCAG / GoS Localization 已完成**：`phb2014` / `scag` / `gos` 依 M02-C policy 的 required 欄位已全數 `zh-TW` 覆蓋（475 個 presentation field），四個 enabled pack 在 `zh-TW` / `en` 下的 required completeness issues 皆為 0。PHB variant 與 SCAG 的 roleplay inheritance 只重用譯文、保留各自 suggestion identity；GoS optional flavor 翻譯後仍為 optional。另修正 Review 授予項目中 background feature 名稱無法在地化的 DTO 缺口（grant 新增 `presentation_field`），涵蓋全部 36 個 background。Playwright spec 已建立但尚未執行，shard `review_status` 仍為 `draft-human-review-required`；詳見 `docs/M02/M02-F_CLOSEOUT.md`。

**同批合併的非 localization 工作**：依使用者明確決定，`m02-f-non-srd-localization` 一併完成「Build Edit / Correction 按鈕合併」與「角色 Archive / 永久刪除」，未另開 M Phase。前者收斂為單一「編輯角色配置」，新版本一律記 `build_edit`；後者新增 `characters.archived_at`（migration `0006_character_archive`）、archive / unarchive / delete 端點、封存後可讀不可寫的守衛，以及 Workshop「封存角色」區塊與打字確認的永久刪除。

**M02-G — Localized Search, Errors & Completeness Gates 已完成**：rules-content selector 以目前 locale 顯示與搜尋，另一 supported locale 的名稱作為隱藏 search alias（繁中搜 `fireball` 命中「火球術」且清單仍只有繁中）；名稱排序改依目前 locale 的 `Intl.Collator`，純數值選單維持設定順序。system-owned 錯誤訊息改以語言中立 machine code 對應在地化字串，server 送出的 43 個 builder issue code 已全數具備 `zh-TW` / `en` 對應，`zh-TW` fallback 一律純中文、不串接英文原文；訊息於 render 時解析 locale，切換語言即時更新且不觸發 Draft mutation。新增 policy × enabled packs × locales 的 completeness gate 與 orphan StableKey / orphan field path / duplicate definition / unsupported locale 四道結構 gate，並藉此刪除 `srd5.1` zh-TW overlay 中 26 筆 Acolyte roleplay orphan 譯文（`phb2014` 已擁有同樣內容，無譯文遺失）。**已知未竟**：server 尚未為 disabled reason 送出 machine code，因此繁中每個 disabled 選項只顯示通用句，依使用者決定延至 M02-H；詳見 `docs/M02/M02-G_CLOSEOUT.md` 與 `docs/M02/M02-H_TODO.md`。

**M02-H — Full M02 Integration & Closeout 已完成**：補完 M02-G 遺留的 structured system-message 契約——server 改送語言中立的 `disabled_reason_code` + `disabled_reason_params` 與 issue `message_params`，multiclass / feat prerequisite 以 ability + minimum score 結構表示、content identity 用 StableKey，前端直接格式化 `code + params`，不再 regex-match server 英文句子；繁中 disabled 選項因此顯示具體原因。新增雙語全站 crawl + overflow gate 與 localization state integrity E2E（Draft 四次切換不增 revision、Character live state 跨切換與 reload 不變）。同步關閉專案 SSOT：`AGENTS.md` / `PROJECT_BRIEF.md` 切回 M01-D 並加入永久 supported-locale 交付守則、`規格企劃.md` 產品基線改為兩種語言、`data/srd5.1/NOTICE.md` 補 CC BY 4.0 繁中 translation/adaptation 聲明。詳見 `docs/M02/M02-H_CLOSEOUT.md`。

**M01-F — VRGR Lineage & Dhampir 已完成**：新增 `lineage` StableKind 與 `vrgr` Content Pack，Dhampir 以獨立 Lineage identity 存在而非 subrace；`CharacterBuild` 取得 typed `lineage_ref` / `ancestral_origin_ref` / `ancestral_legacy`。Direct Create 依 ability branch / size / language / 2 個自選 Skill 規則建立，Existing Character 重用 P1-G `BUILD_EDIT` 轉換並產生 immutable Version N+1。Ancestral Legacy whitelist 只放行原 Race 來源的 Skill proficiencies 與 climb / fly / swim speeds，其餘六類（ability bonus、weapon / armor proficiency、racial spell、racial trait、walking speed）不出現在 options 且 server 端拒絕偽造 payload。Transformation 保留 damage delta / Temp HP / Conditions / Inventory / prepared spells 且不重建 Starting Equipment。另修正既有 Playwright 平行度缺陷（`workers: 1`）。詳見 `docs/M01/M01-F_CLOSEOUT.md`。

**M01-G — TCE Artificer Core 已完成**：新增 `tce` Content Pack 並啟用 Artificer class core；Lv1～20 progression、ASI markers、spell slots、Infusions Known / Infused Items Max metadata 與四個 Specialists（Alchemist / Armorer / Artillerist / Battle Smith）已進 Builder / Review / Confirm / Sheet。Spellcasting 延續 P1 framework，prepared formula 與 multiclass slot contribution 的 floor / ceil rounding 已拆開；Artificer half-caster multiclass 使用 ceil，Paladin / Ranger 維持 floor，Warlock Pact Magic 保持隔離。Artificer spell list 僅引用 installed spell entries，缺 supplied source 的 spell gap 不 fake、不 dangling。Real-backend M01-G E2E 與完整 Playwright suite 已通過。詳見 `docs/M01/M01-G_CLOSEOUT.md`。

**M01-H — TCE Artificer Advanced Features & Infusions 已完成**：`infusion` 成為 first-class content kind，已導入 H scope 需要的 16 個 TCE Infusions 並同步 `zh-TW` / `en` presentation；Known Infusions 屬 immutable Build，Active Infusions / Armor Model / Spell-Storing Item 屬 Current State。Rules Layer derive Infusion Known / Active capacity、Armor Modifications capacity bonus、Artificer attunement capacity與 Magic Item Savant restriction-bypass metadata；Flash of Genius、Defensive Field、Arcane Jolt、Spell-Storing Item 等 limited-use feature resources 可追蹤。Build Edit / Level Up reconciliation 不 silent delete live state，移除仍 active 的 Known Infusion 會形成 blocking conflict。Experimental Elixir、Eldritch Cannon、Steel Defender、combat triggers、Rest recharge 與 generic Attunement workflow 保持 metadata / manual boundary。Backend / frontend / localization / migration / full-stack Playwright 均已驗證通過。詳見 `docs/M01/M01-H_CLOSEOUT.md`。

**M01-I — TCE Optional Class Features & Fighting Styles 已完成**：TCE Optional Class Features 以 typed / data-driven semantics 接入 Builder / Build / Level Up，支援 addition、expanded option pool、replacement 與 retraining / versatility；Fighter / Paladin / Ranger TCE Fighting Styles 使用單一 mechanical StableKey identity 跨職業引用；Blessed Warrior / Druidic Warrior / Superior Technique nested choices、Ranger Deft Explorer / Favored Foe / Primal Awareness / Nature's Veil replacement chain、expanded spell access isolation、legacy fighting style retraining 與 Version History 均已由 backend tests 與 browser/full-stack E2E 驗收。詳見 `docs/M01/M01-I_CLOSEOUT.md`。

**M01-J — 2014 Class Subclass Expansion 已完成**：PHB / SCAG / XGE / TCE 四來源共 112 個 subclass identity 全部 accounted for（95 implemented + 17 canonical duplicate / reprint），`xge` 成為正式 enabled pack。Subclass 內容改為一般 pack data——原本在 registry load 時以 regex 解析 `docs/暫用規則資訊/子職業_*.md` 的 9 個模組（3,655 行）已移除，改由一次性 authoring script 產出 780 個 entry 與 402 個 zh-TW presentation field 進 `data/<pack>/`；vendored `srd5.1` 語料維持原狀，其 11 筆加欄位 patch 走獨立 override 檔。Subclass 取得與 feature progression 依 class level，reprint 採 deterministic canonical identity，persistent choice / granted spell / resource capacity 沿用既有 generic 模型。12 個 PHB class 各一條完整瀏覽器流程與四來源矩陣已驗收。關門過程中另修復 7 項既有缺陷，包含 server image 無法啟動、22 個中文 canonical 名稱、30 個異常 StableKey、紫龍騎士專精缺等級 gate，以及 Level Up 無法儲存子職業選項的 HTTP 422。詳見 `docs/M01/M01-J_CLOSEOUT.md`；兩項已知問題見根目錄 `已知問題.md`。

**M01-K — PHB Feat & Spell Catalog Expansion 已完成**：PHB 2014 相對 SRD Grappler 以外的 41 個 Feats 與 PHB relative-to-SRD missing 42 個 Spells 已全部進入 `phb2014` runtime catalog。Feat acquisition 取得 acquisition-level persistence，Variant Human / ASI 共用同一 Feat pool 與 prerequisite / repeatability resolver；Elemental Adept repeatable acquisition、Martial Adept maneuver entitlement / superiority-die resource、Tough / Observant static derived modifiers、Magic Initiate / Ritual Caster / Spell Sniper spell choices與 four-shape prerequisite matrix均已驗收。Spell metadata / class access / cross-source provenance / Known-Spellbook-Prepared integration 已補齊，M01-I/J provisional spell identities 被 reuse / enrich。`phb2014` Feat / Spell `data.desc.*` 已納入 M02 localization policy並完成 `zh-TW` / `en` required coverage。詳見 `docs/M01/M01-K_CLOSEOUT.md`。

**M01-L — VGM & SCAG Remaining Race Expansion / Generic Race Mechanics 已完成**：VGM remaining 10 個 full race（Bugbear / Firbolg / Goliath / Kenku / Kobold / Lizardfolk / Orc / Tabaxi / Triton / Yuan-ti Pureblood）與 SCAG remaining 2 個 subrace（Ghostwise Halfling / Deep Gnome）已 materialize 成正式 pack data，12 個 identity 由 registry load 時的 exact inventory gate 逐 key 守住，M01-D / M01-E 既有身分未被重做。generic Race/Subrace movement grant 讓 Lizardfolk / Triton swim 30 與 Tabaxi climb 20 不需 race name hardcode；signed racial ability modifier 讓 Kobold STR −2 / Orc INT −2 正確落在 Point Buy base legality 之後（合法 base 8 + racial −2 得 effective 6）；Natural Armor 成為 Rules Layer primitive，與 worn armor / shield / Numeric Override 的優先序明確；racial spell 取得 canonical 多值 `recharge_types`，Firbolg 的「short or long rest」無損保存，legacy 單值 `rest_type` 僅作載入舊資料的 normalize input。`runtime_execution` 收斂為封閉 Literal，12 scope features 的 automation boundary 可 machine-check，deferred 效果不被宣稱為自動執行。Runtime 完全不依賴 `docs/暫用規則資訊/`，server image 不含 `docs/` 仍完成 registry load 與 Builder flow。關門過程中另修復 3 項既有缺陷：Deep Gnome inventory 名稱與 runtime canonical 不符導致 registry load 直接失敗、三個 SCAG Half-Elf feature 的 orphan zh-TW overlay，以及四個 automatic feature 缺 runtime classification。詳見 `docs/M01/M01-L_CLOSEOUT.md`。

**M01-L — VGM & SCAG Remaining Race Expansion / Generic Race Mechanics 已完成**：VGM remaining 10 個 full race 與 SCAG remaining 2 個 subrace 已 materialize 成正式 pack data，12 個 identity 由 registry load 時的 exact inventory gate 守住。generic Race/Subrace movement grant、signed racial ability modifier（Point Buy base legality 先於種族修正）、Natural Armor Rules Layer primitive 與 racial spell canonical multi-rest recharge 均進既有 substrate，沒有 race name hardcode 也沒有第二套 persistence。`runtime_execution` 收斂為封閉 Literal，12 scope features 的 automation boundary 可 machine-check。Runtime 不依賴 authoring Markdown，server image 不含 `docs/` 仍完整成立。Tiefling 與 MTF 全部留給 M01-M。詳見 `docs/M01/M01-L_CLOSEOUT.md`。

**M01-M — MTF Planar Race Expansion & Tiefling Bloodline / Variant System 已完成**：新增 `mtf` pack，7 個 MTF planar race identity 與 Tiefling 九獄大魔血脈 9 / 9 accounted（Asmodeus canonical map 既有 `srd5.1:race:tiefling` + 8 個新 bloodline variant，duplicate identity 為 0，既有 Tiefling 不 migration 也不換 key）。8 個 bloodline 同時替換 ability package 與 Infernal Legacy；SCAG 的 Feral 與 Legacy 兩個 replacement group 正交，8 種合法組合成立，MTF bloodline 與 SCAG variant 的交叉組合由 server 全數阻擋且 zero side effect。Race-variant group selection 進 immutable Build Version 並可 deterministic 還原 Build Edit seed，M01-E 舊 Build 無此欄位仍可讀。Winged 的 fly 30 是 Current State 推導（Build `fly_speed` 為 `None`），Eladrin season 用 `feature_modes` + `initial_state_seed`，兩者切換都不產生 Build Version。Feature mode 驗證改為 default-deny，Armor Model / Eldritch Cannon 一併改走同一個 generic validator。關門過程中另修復 5 項既有缺陷，包含 `build_version_summary()` 被誤刪導致 server 無法 import、`data/mtf` 未進 server image 導致容器起不來，以及 conditional movement 被寫進 immutable Build。詳見 `docs/M01/M01-M_CLOSEOUT.md`。

> **M01-M 已 closeout，但 M01 不是 full closeout。M 之後是否還有新 M01 規則 Subphase、以及 Full M01 Integration & Closeout 的 Subphase ID 目前 TBD。M03 已由使用者明確拍板並正式開工，M01 可保持 open；P2 — Room / Campaign / Session / Seat 仍不得提前開工，需等 M03 closeout 與 M01 final closeout。不得因 M01 / M02 / M03 提前拆 P2～P8。**

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
- 全專案規則：**每個 Phase 在 coding 前必須拆成可獨立實作、驗證、commit 的 Subphases；只拆當前 Phase，不提前拆後續 Phase。已明確拍板且插入點確定的 M Phase 是唯一可提前完成三份文件的例外。**
- M Phase 可插在正常 P Phase 之間，也可插在另一個 M Phase 的兩個 Subphase 之間；不改寫正常 P Roadmap。
- 目前已拍板 M01-A～M01-M 三份正式文件已完成，且 M01-A～M01-M 均已關門；M 後內容 Subphase與 final closeout字母待後續需求確定。
- M02-A～M02-H 三份正式文件已完成。
- **M03-A～M03-G 三份正式文件已完成拆分；M03-A 已正式開工。**
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
- Character JSON Import / Export 已由後續 M03 提前承接；Builder MCP / AI transport 仍留後續對應 Phase。
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
- Build spell resource capacity 與 live resource usage 分離。

### P1-F — Equipment, Review & Character Creation

- Starting Equipment 支援 automatic grants、A/B branch、nested choices、equipment category 與 quantity。
- Starting Equipment 只從 starting class + background 規則取得；Starting Gold 不建立購物流程。
- Create Confirm 原子建立 Character + immutable Version 1 + initial Current State；double-submit idempotent。
- initial Current State 包含 HP、Temp HP、Conditions、Hit Dice、Prepared、Spell Resources、Starting Inventory。
- Starting Inventory 只初始化一次，後續不從 Build 重建覆蓋 live Inventory。
- Review / Confirm 與 Character Sheet real-browser flow 已完成。

### P1-G — Level Up & Character Versions

- Existing Character 可建立 versioned Builder Draft，綁定 `base_version_id`。
- Level Up Confirm append immutable Version N+1，不覆寫 Version 1。
- stale base version 由 server 阻擋。
- Current State reconciliation 保留 damage delta、Temp HP、Conditions、Inventory、合法 Prepared 與既有資源消耗語意。
- Character Workshop 提供 Level Up / Edit Build / Correct Build / Version History。
- real-backend Playwright 覆蓋 Lv1 Barbarian → Lv2 與 Version 1 / 2 history。

### P1-H — Full P1 Integration & Closeout

- CI 升級為 P1 Full Regression：backend pytest、migration、frontend build / Vitest、Docker full stack、Playwright、restart persistence。
- P0 → P1 migration 驗 legacy Character / Build / State 不被破壞。
- real-backend E2E 覆蓋 Lv1 Create、高等 Create、Multiclass、Caster、Level Up、Version History。
- server restart 覆蓋 Character State、active Draft、Level-Up Character 與 Version History persistence。
- P1-H 不新增 P2 system；P1 已正式關門。

---

## M01 規劃與共通契約

M01 正式文件：

- `docs/M01/實作規格.md`
- `docs/M01/開發設計方針.md`
- `docs/M01/測試指南.md`

M01 共通原則：

- M Phase 專門承接資料補完、既有架構加強與 migration，不改寫正常產品 Phase 編號。
- `docs/暫用規則資訊/` 是 human / maintainer reference，不是 runtime data source；**reference 內的規則描述文字可在 authoring/materialization 階段直接搬進正式 runtime data / localization，但 server不得 runtime parse Markdown。**
- 正式 runtime 內容進 `data/<pack>/`，由 Content Registry 驗證與載入。
- Reference 若混入後來來源新增的規則 access，materialization 時必須保留 source provenance，不得因同一 Markdown 而污染原始 pack canonical semantics。
- StableKey 維持 `<pack_id>:<kind>:<index>`；`srd5.1:*` 舊 key 不改名。
- `content_sources` 是 server-derived Build provenance，不是 Builder allowlist。
- 不為 SCAG / Dhampir / Artificer / PHB Feat 各做一套 Builder；優先延伸既有 generic choice / progression / rules 模型。
- 複雜 runtime effect 若需要未來 Combat / Rest / Roll context，可以明確標為 manual/deferred，但 structural rule / capacity / identity 必須先正確。
- M01-B 是第一個真人創角 Gate；Gate blocker 已完成修正並關門。
- **M01-C 後插入的 M02 已 closeout；M01-D～M01-L 亦已完成並關門，M01 尚未 full closeout。**
- **M01-D 起所有後續 M01 Subphase 遵守 M02 localization 永久規則：新增／修改／首次 expose user-visible system / rules content 必須同一 Subphase 同步 `zh-TW` / `en`。**
- **M01-M 已 closeout，但不是 M01 full closeout。** M 後仍可能再新增規則 Subphase。原 Full M01 Integration & Closeout scope保留，但 Subphase ID TBD，不先假設為 N。

---

## M01 Subphase 進度

狀態：📐 規格可實作；⬜ 尚未開工；🚧 進行中；✅ 完成。

| Subphase | 狀態 | 重點 |
|---|---|---|
| **M01-A — Multi-Source Content Pack Foundation** | ✅ | 泛化 Content Pack / StableKey / registry / cross-reference / `content_sources`，維持 SRD compatibility |
| **M01-B — PHB Character Origins & Background Expansion** | ✅ | PHB Background、PHB 非 SRD subrace、Variant Human；真人創角 Gate 已執行並關門 |
| **M01-C — SCAG / GoS Background Expansion** | ✅ | 13 SCAG + 4 GoS Background、source collision、roleplay-only table reuse / background variant、equipment / E2E regression |
| **M01-D — VGM Race Expansion** | ✅ | Goblin / Hobgoblin / Aasimar、level-gated racial features / resource metadata；雙語與 E2E 已驗收 |
| **M01-E — SCAG Half-Elf Variant & Grant Replacement** | ✅ | Half-Elf ancestry variants、最小通用 Grant Replacement、stale branch isolation、movement modes、Drow Magic resources；雙語與 E2E 已驗收 |
| **M01-F — VRGR Lineage & Dhampir** | ✅ | `lineage` StableKind、`vrgr` pack、Dhampir、Ancestral Legacy whitelist、既有角色 versioned transformation；雙語與 E2E 已驗收 |
| **M01-G — TCE Artificer Core** | ✅ | Artificer progression / spellcasting / subclass；multiclass half-caster ceil rounding；雙語與 E2E 已驗收 |
| **M01-H — TCE Artificer Advanced Features & Infusions** | ✅ | Infusion known vs active state、feature resources、attunement capacity、advanced feature boundary；同步雙語與 E2E 已驗收 |
| **M01-I — TCE Optional Class Features & Fighting Styles** | ✅ | addition / expanded option pool / replacement / retraining，並補 TCE Fighting Styles；同步雙語與 E2E 已驗收 |
| **M01-J — 2014 Class Subclass Expansion** | ✅ | PHB / SCAG / XGE / TCE 112 個 subclass identity、`xge` pack、內容 materialize 進 `data/`、class-level gate、reprint canonicalization；雙語與 12 職業 E2E 已驗收 |
| **M01-K — PHB Feat & Spell Catalog Expansion** | ✅ | PHB non-SRD Feats 41/41、Spells 42/42；Feat structural mechanics / prerequisite / nested choices、Spell catalog/access、既有 M01-I/J spell reconcile、跨來源 provenance、雙語與 focused E2E 已驗收 |
| **M01-L — VGM & SCAG Remaining Race Expansion / Generic Race Mechanics** | ✅ | VGM remaining 10 races + SCAG remaining 2 subraces；generic Race/Subrace movement grant、signed racial modifier compatibility、Natural Armor Rules Layer primitive、racial spell canonical multi-rest recharge、typed runtime automation classification、no-docs runtime gate；雙語與 FC-E2E-21 已驗收 |
| **M01-M — MTF Planar Race Expansion & Tiefling Bloodline / Variant System** | ✅ | `mtf` pack、7 個 MTF planar race、Tiefling 9/9 血脈（Asmodeus canonical map + 8 new variants）、SCAG 保守相容、replacement group persistence、Winged conditional movement、Eladrin season State ownership、feature mode default-deny；雙語與 M-E2E-01～05 已驗收 |

**M01-A～M01-M 已完成並關門。M01 尚未 full closeout；M 後 Subphase 尚未拍板，Full M01 Integration & Closeout 的 Subphase ID 目前 TBD。**

---

## M02 規劃與共通契約

M02 正式文件：

- `docs/M02/實作規格.md`
- `docs/M02/開發設計方針.md`
- `docs/M02/測試指南.md`

M02 插入時點：**M01-C closeout 後暫停 M01；M02 已於 2026-08-31 closeout，M01-D 亦已完成並關門。**

M02 共通原則：

- 第一版只支援兩個 locale：`zh-TW`、`en`；無既存偏好時預設 `zh-TW`。
- 兩者都是純語言模式，正常流程不得出現可避免的中英混合 system / rules presentation。
- locale 是 browser presentation preference，**不得寫入 Draft / CharacterBuild / CharacterState / Version metadata**。
- 切換語言即時 rerender，不 reload、不 navigation、不觸發任何 Draft / Character mutation。
- Rules identity（StableKey / refs / choice id / provenance）永遠不因翻譯改變；Display Name 不是 foreign key。
- Localization 是 presentation overlay，不得複製出第二套會各自演化的 mechanics content。
- **翻譯 scope 採 field-level visibility policy：M02-C 決定哪些 field 在 M02 closeout 當下真的 user-visible；D / E / F / G completeness 全部共用同一 policy。**
- 例如目前 Inventory selector 已顯示的 SRD magic item `name` 要翻；若完整 `desc` 尚無 product surface，就不因 item category 已存在而提前翻。
- **M02-E 特例**：依使用者明確要求，額外提前 author SRD spell / feature / condition 的 `data.desc.*`；這不改變 `currently_user_visible`，也不擴張 item / background hidden long-form corpus。
- `docs/暫用規則資訊/` 既有繁中譯名是 glossary 的 priority reference input；M02-C glossary 才是正式 terminology SSOT。
- 大量翻譯允許外部 AI session 協助產 draft，但 runtime 不接 LLM；依 category 分批 author / review / commit，**batch 完成不等於 Subphase closeout**。
- 缺 required translation 不得以 silent fallback 當成完成；completeness gate 必須讓 CI 失敗。
- 使用者自行輸入的自由文字不翻譯、不因切換語言被改寫。
- M02 closeout enabled packs：`srd5.1`、`phb2014`、`scag`、`gos`；required coverage = enabled packs × policy-required fields × supported locales。
- **已成為永久規則（M02-H closeout 生效，見 `AGENTS.md` 工程實作守則第 6 條）：後續 Subphase 新增、修改，或因新畫面而首次 expose user-visible system / rules content，必須同步提供所有正式 supported locale，缺一語即視為該 Subphase 未完成。**

---

## M02 Subphase 進度

狀態：📐 規格可實作；⬜ 尚未開工；🚧 進行中；✅ 完成。

| Subphase | 狀態 | 重點 |
|---|---|---|
| **M02-A — Locale Foundation & Runtime Switch** | ✅ | 全站單一 locale state、一鍵切換、browser 記憶、不動 Draft / Character domain state |
| **M02-B — Full UI Copy Localization** | ✅ | 既有 frontend UI copy 全部進 localization resources，含 accessibility text；Builder 七個具名 step 全覆蓋 |
| **M02-C — Localized Content Model & Terminology Contract** | ✅ | canonical / overlay 邊界、localized resolver、field-level localizable policy、roleplay suggestion identity、glossary 定稿 |
| **M02-D — SRD 5.1 Names & Structured Text** | ✅ | 依 policy 完成目前 user-visible SRD names / labels / structured text 雙語覆蓋 |
| **M02-E — SRD 5.1 User-Visible Descriptions** | ✅ | SRD spell / feature / condition `data.desc.*` zh-TW authoring；canonical-driven coverage / leakage / mechanics / Markdown gates；item / background hidden long-form 延後 |
| **M02-F — PHB / SCAG / GoS Localization** | ✅ | 依 policy 完成 M01-B / M01-C current-surface non-SRD content；既有繁中 reference 作 priority input |
| **M02-G — Localized Search, Errors & Completeness Gates** | ✅ | localized search / alias / sort、error code + localized message、policy-driven completeness / orphan guard |
| **M02-H — Full M02 Integration & Closeout** | ✅ | structured disabled-reason / issue params、全站雙語 crawl + overflow gate、Draft / Character state integrity、translation evidence 彙整、doc-sync / CC BY NOTICE |

**M02-A～M02-H 全部完成，M02 已關門；M01-D～M01-M 亦已完成並關門。M01 尚未 full closeout；M 後是否新增 M01 Subphase 與 Full M01 Integration & Closeout 的 Subphase ID 仍待後續拍板。**

---

## M03 規劃與共通契約

M03 正式文件：

- `docs/M03/實作規格.md`
- `docs/M03/開發設計方針.md`
- `docs/M03/測試指南.md`

M03 定位：**Standalone Character Builder Distribution**。它不重做 P0 / P1 / M01 / M02，而是把目前已完成的角色能力包成可下載、離線執行的單機版，並建立 P2 之後仍必須守住的 Character standalone boundary。

M03 共通原則：

- 線上版與單機版共用同一份 codebase、domain、rules 與 frontend build；不 fork 第二套專案。
- web entry 維持 PostgreSQL；standalone entry 使用本機 SQLite，並由 PyInstaller 打包與 launcher 自動開瀏覽器。
- 單機版只承載 Landing / Character Workshop / Builder / Character Sheet / Level Up / Version History / Archive / Delete / `zh-TW` / `en` / Character JSON Import / Export。
- Room / Campaign / Session / Seat / Combat / Timeline / AI Actor / DM tools / account system 不進 standalone；由 capability contract + backend router mounting 雙重限制。
- Character JSON Import / Export 由 M03-B / C 提前承接，不再等 P7；P7 保留 broader Snapshot / Archive / Import / Export lifecycle。
- M01 可以保持 open 並在後續追加資料或 UI；M03 不以 M01 Full Closeout 作為開工前置條件。若未來 M01 改動 Character Build / State / Version / StableKey / Builder provenance 等 M03 核心契約，則需同步做 M03 compatibility review。
- **P2 仍須等 M03 closeout 與 M01 final closeout 後才正式開工。**

---

## M03 Subphase 進度

狀態：📐 規格可實作；⬜ 尚未開工；🚧 進行中；✅ 完成。

| Subphase | 狀態 | 重點 |
|---|---|---|
| **M03-A — Content Root Path Abstraction & Enabled-Pack SSOT** | 🚧 | Content / Rules / Localization / DB path resolver、frozen/repo fallback、`Settings.enabled_content_packs` SSOT、consumer 接線、legacy path static guard、subset loading contract；目前進行實作與 non-E2E regression 驗證 |
| **M03-B — Character JSON Schema, Export & Builder Provenance** | ⬜ | Character export envelope、完整 version chain / current state、`builder_provenance` migration 與 versioned draft seed SSOT |
| **M03-C — Character JSON Import via Builder Draft** | ⬜ | JSON preview / validation、StableKey unresolved 分析、new identity import、`draft` / `draft_with_history_loss` landing mode |
| **M03-D — SQLite Migration Chain Gate & FK PRAGMA** | ⬜ | SQLite migration chain、foreign key enforcement、standalone DB lifecycle 與 migration compatibility gate |
| **M03-E — Standalone Packaging & Launcher** | ⬜ | `app.standalone` entry、capability endpoint、SPA fallback、PyInstaller、browser launcher、SQLite beside executable |
| **M03-F — Windows CI Build, Release & Import Boundary Test** | ⬜ | Windows frozen build、artifact/release flow、standalone import boundary 與未來 P2 dependency leakage gate |
| **M03-G — Full M03 Integration & Closeout** | ⬜ | web ↔ standalone ↔ standalone JSON round-trip、frozen runtime smoke、雙語 / persistence / migration / capability 全整合 closeout |

**M03 已完成 A～G 正式拆分；目前 M03-A 進行中。M01 同時保持 open，不因 M03 開工而宣告 full closeout。**

---

## Phase Roadmap

> 原則：先把角色與規則資料做完整，再把角色帶進桌內；每個 Phase 準備開工時才設計該 Phase 的細節。

| Phase | 主題 | 重點 |
|---|---|---|
| **P0** | **Character Core + SRD / Rules Foundation** | 導入角色真正需要的 SRD 5.1 reference content；建立 Character 核心資料、角色卡與角色相關規則計算基礎。**不導入 Monster / Beast stat blocks。** |
| **P1** | **Character Builder Complete** | 完整創角、高等角色建立、Level-by-level progression、Subclass、Multiclass、ASI / Feat、Spell progression、Level Up、Character Version |
| **M01** | **Multi-Source Character Content Expansion** | 插入式 Maintenance Phase：多來源 Content Pack、PHB/SCAG/GoS/VGM/VRGR/XGE/TCE/MTF 角色內容與既有 Character 系統強化；C 後插 M02，再由 D 接續；K 補 PHB Feats/Spells，L 補 VGM/SCAG remaining race 與通用 race mechanics，M 補 MTF planar race 與 Tiefling bloodline system。M01 目前保持 open，後續仍可補資料/UI，final closeout 於 P2 前完成 |
| **M02** | **Traditional Chinese / English Localization** | 插入於 M01-C 與 M01-D 之間：`zh-TW` / `en` 雙語 foundation、field-level current-surface localization、translation workflow、completeness gate；完成後回 M01-D |
| **M03** | **Standalone Character Builder Distribution** | P2 前的插入式 Maintenance Phase：同 codebase 單機創角、SQLite、Character JSON Import / Export、capability contract、PyInstaller / Windows release 與 standalone import boundary；目前 M03-A 進行中 |
| **P2** | **Room / Campaign / Session / Seat** | 把已建立的角色真正放進桌內；建立 Room、Campaign、Party Roster、Player Seat、Controller 與 Session lifecycle |
| **P3** | **Exploration + Roll + AI** | 建立 Exploration、Chat / Action / Check、正式骰子與 PendingAction；Human / AI 開始能在同一桌真正跑團 |
| **P4** | **Quick Combat** | 第一個完整可玩的 Combat MVP；**P4-A 必須先承接 P0 延後的 SRD Monster / Beast stat blocks。** |
| **P5** | **Tactical Combat** | 在同一 Combat Engine 上增加 Grid、Battle Map、Movement、Range、AoE、Wall / Door / Terrain、Automatic OA 等空間系統 |
| **P6** | **Adventure + AI DM Runtime** | Adventure Definition / Importer、Campaign Runtime、World State、NPC / Scene / Fact、AI DM context 與 write-back |
| **P7** | **Snapshot / Export** | Timeline、Snapshot / Restore、broader Archive / Import / Export lifecycle；Character 基礎 JSON exchange 已由 M03 先行，不做 Undo 機制 |
| **P8** | **QA / Polish** | 全流程整合測試、權限與 AI reconnect、錯誤處理、效能、Responsive UI、UX polish 與第一版收尾 |

P0/P1 已完成；**目前已拆 M01、M02 與 M03；M03-A 已開工。P2～P8 仍維持大 Phase，不提前拆。**

實際執行順序：

```text
M01-A ✅ → M01-B ✅ → M01-C ✅ → M02-A ✅ → M02-B ✅ → M02-C ✅ → M02-D ✅ → M02-E ✅ → M02-F ✅ → M02-G ✅ → M02-H ✅ → M01-D ✅ → M01-E ✅ → M01-F ✅ → M01-G ✅ → M01-H ✅ → M01-I ✅ → M01-J ✅ → M01-K ✅ → M01-L ✅ → M01-M ✅ → M03-A 🚧 → M03-B → M03-C → M03-D → M03-E → M03-F → M03-G → M03 closeout → Future M01 Subphase(s) TBD → Full M01 Integration & Closeout (Subphase ID TBD) → P2
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

## P0 / P1 / M01 / M02 / M03 邊界

### P0 — Character Core + SRD / Rules Foundation

P0 建立正式 SRD / Character 地基：Character content、immutable Build、mutable State、rules、Character Sheet、state UI。

### P1 — Character Builder Complete

P1 讓網站可以依 D&D 5e 2014 structural rules 建立／升級角色，並保存 versioned Build。

### M01 — Multi-Source Character Content Expansion

M01 不重做 P0/P1；它把「SRD 可創角」提升成「既有 Builder 可以承載逐步加入的多來源內容」。M01 主要增加：

- Content Pack foundation。
- PHB / SCAG / GoS / VGM / VRGR / XGE / TCE 本次已提供角色資料。
- replacement / lineage / Artificer / Optional Class Feature / subclass / PHB Feat 等為這些內容真正需要的最小通用能力。
- PHB 相對 SRD 缺少的 Feat / Spell runtime catalog（M01-K）。
- Reference Markdown只作 human/maintainer authoring input；描述文字可搬入 runtime/localization，但 runtime不得直接解析 `docs/`。
- M01-B 真人創角測試 Gate。
- M01-C SCAG / GoS Background expansion 已 closeout。
- M01-D～M01-L 已 closeout。
- M01-D 起承接 M02 已建立的 localization Definition of Done。
- VGM / SCAG remaining race 與 generic race mechanics（M01-L）、MTF planar race 與 Tiefling bloodline / variant system（M01-M）均已完成並關門。
- M01-M 之後仍可依實際規則需求拆新的 M01 Subphase；Full M01 Integration & Closeout 的字母目前不預先決定。

M01 正式文件：

```text
docs/M01/實作規格.md
docs/M01/開發設計方針.md
docs/M01/測試指南.md
```

### M02 — Traditional Chinese / English Localization

M02 不改 mechanics；它把「網站中英混用 presentation」提升成「同一份 rules identity 可用 `zh-TW` / `en` 兩種純語言模式呈現」。M02 主要增加：

- 全站 locale runtime state 與瀏覽器記憶。
- UI copy 與 rules content localization boundary / resolver。
- field-level localizable policy，避免提前翻尚無 UI surface 的大量長文。
- roleplay suggestion identity。
- D&D 5e 2014 en ↔ zh-TW glossary，既有暫用規則文件作 priority reference input。
- 外部 AI-assisted / human translation authoring、review、batch evidence 流程。
- localized search / sort / error presentation。
- machine-verifiable translation completeness / orphan gate。
- M02-H doc-sync 與 SRD CC BY 4.0 translation/adaptation NOTICE closeout。（✅ 已完成）

M02 正式文件：

```text
docs/M02/實作規格.md
docs/M02/開發設計方針.md
docs/M02/測試指南.md
```

### M03 — Standalone Character Builder Distribution

M03 把既有角色功能包成離線 standalone distribution，並提前建立 Character JSON exchange 與 P2 之後必須維持的 standalone boundary。M03 不把 Room / Campaign / Session / Seat 等多人 domain 帶進單機版。M01 可在 M03 期間保持 open；P2 仍等 M03 closeout 與 M01 final closeout。

M03 正式文件：

```text
docs/M03/實作規格.md
docs/M03/開發設計方針.md
docs/M03/測試指南.md
```

---

## P4 已知承接項目

這不是 P4 的提前實作設計，只是 P0 scope cut 的**跨 Phase 承接契約**：

- P4 的第一個 Subphase 命名為 **P4-A**。
- P4-A 必須承接 P0 明確延後的 **SRD 5.1 Monster / Beast stat blocks**。
- P4-A 開工時再依當時 Combat Engine 需求決定 Monster Template schema、actions / attacks / spellcasting representation、validation 與 API。
- P0 / P1 / M01 / M02 / M03 不為此提前建立 Monster-specific schema / translation / combat data。

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
| **`已知問題.md`** | 已確認、但決定暫不處理的問題：症狀、根因、影響範圍、暫時處置與重啟條件 |

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
│   ├── M01-B_HUMAN_GATE.md
│   ├── M01-C_AUTOMATED_STATUS.md
│   ├── M01-C_CLOSEOUT.md
│   ├── M01-D_CLOSEOUT.md
│   ├── M01-E_CLOSEOUT.md
│   ├── M01-F_CLOSEOUT.md
│   ├── M01-G_CLOSEOUT.md
│   ├── M01-H_CLOSEOUT.md
│   ├── M01-I_CLOSEOUT.md
│   ├── M01-J_CLOSEOUT.md
│   ├── M01-K_CLOSEOUT.md
│   ├── M01-L_CLOSEOUT.md
│   └── M01-M_CLOSEOUT.md
├── M02/
│   ├── 實作規格.md
│   ├── 開發設計方針.md
│   ├── 測試指南.md
│   ├── M02-C_CLOSEOUT.md
│   ├── M02-D_CLOSEOUT.md
│   ├── M02-E_CLOSEOUT.md
│   ├── M02-F_CLOSEOUT.md
│   ├── M02-G_CLOSEOUT.md
│   ├── M02-H_TODO.md
│   └── M02-H_CLOSEOUT.md
├── M03/
│   ├── 實作規格.md
│   ├── 開發設計方針.md
│   └── 測試指南.md
└── 暫用規則資訊/
```

`docs/暫用規則資訊/` 目前另包含 M01-K supplied authoring reference：

```text
專長_PHB_非SRD內容.md
法術_PHB_非SRD內容.md
```

M01-L / M01-M 的 supplied authoring reference：

```text
種族_VGM.md     # M01-L remaining 10 full races
種族_SCAG.md    # M01-L remaining 2 subraces；M01-M Tiefling variants
種族_MTF.md     # M01-M planar races 與九獄大魔血脈
```

這三份只作 authoring / review input；runtime 不得解析或依路徑讀取。

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

被插入的 M Phase 保留既有已拍板 Subphase 編號與順序，暫停後照原順序接續，不重新命名。尚未拍板的未來 Subphase則不提前編號；例如目前 Full M01 Integration & Closeout 只保留 scope，實際字母 ID TBD。

原則上只拆正在準備開工的 Phase；**唯一例外是使用者已明確拍板且插入點已確定的 M Phase，可在插入點到達前先完成三份文件。** M02 就是此例。

目前已拆 M01、M02 與 M03；**M03-A～M03-G 已拍板，且 M03-A 已正式開工。P2～P8 不提前拆。**

---

## 開發接手原則

新的 ChatGPT / Claude / Codex Session 或實作者進入專案時：

1. 先讀 `AGENTS.md`。
2. 再讀 `PROJECT_BRIEF.md` 取得目前 Phase、Subphase 與下一步。
3. 按任務讀 `規格企劃.md` 對應章節。
4. M01 實作／驗收依 `docs/M01/`、M02 依 `docs/M02/`、M03 依 `docs/M03/` 三份文件中的同名 Subphase 取得契約。
5. M02 已 closeout（A～H 全部完成）；M01-D～M01-M 亦已完成並關門，但 M01 尚未 full closeout。M03 已拆成 A～G，**目前 M03-A 進行中**。
6. M01 可以保持 open 並在後續補資料/UI；不要因 M03 開工而自動宣布 M01 full closeout。也不要提前切到 P2：P2 須等 M03 closeout 與 M01 final closeout，Full M01 Integration & Closeout 的 Subphase ID 目前仍 TBD。
7. M02-D / E / F 的 translation batch 可以分批 commit，但不能分批關閉 Subphase。
8. M01-D 起，新增／修改／首次 expose user-visible content 必須同步維護所有 supported locales（`zh-TW` / `en`）；缺任一語言視同該 Subphase regression。
9. 不重新討論已定案產品規格。
10. 不為 P2～P8 預先設計具體實作。
11. **未獲使用者明確要求，不開始 coding。**
