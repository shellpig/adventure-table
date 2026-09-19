# Roadmap 歷史進度

最後整理：2026-09-19

本檔保存已關門 Subphase 的進度表與關門摘要，不是開場必讀，也不定義當前工作。當前狀態、下一步與未來 Roadmap 只看 [PROJECT_BRIEF.md](../PROJECT_BRIEF.md)。M01／U01 整體保持 open，其已關門 Subphase 同樣歸入本檔。

查閱時先搜尋 Phase／Subphase 標題，只讀相關段落；歷史記錄中的「尚未」「留給下一步」是當時狀態，不代表目前待辦。實作契約與驗收證據以各 Phase 文件為準，未解問題見 [已知問題.md](../已知問題.md)。

## 關門摘要（2026-09-19）

**P0、P1、P2、P3、M02、M03 已完成並關門；M01-A～M01-O 已逐項關門，M01 仍是長期保持 open 的 Character Content Expansion / Maintenance track；M04-A～M04-C 已於 2026-09-12 關門。P4 開工前置已於 2026-09-13 完成，`P4-A — Monster & Combatant Foundation` 於 2026-09-15 在 branch `p4-a-monster-combatant-foundation` 關門並合併回 `main`（[P4-A closeout](../docs/P4/P4-A_CLOSEOUT.md)，code SHA `19c76b1e`，merge-gate 本機全套 E2E 123 passed / 4 skipped）。`P4-B — Combat Lifecycle, Initiative & Action Economy` 於同日在 branch `p4-b-combat-lifecycle-initiative-action-economy` 關門並合併回 `main`（[P4-B closeout](../docs/P4/P4-B_CLOSEOUT.md)，code SHA `0f369bdd`，merge-gate 本機全套 E2E 123 passed / 4 skipped）。`P4-C — Attack, Damage & Core Action Resolution` 於同日在 branch `p4-c-attack-damage-core-action-resolution` 關門並合併回 `main`（[P4-C closeout](../docs/P4/P4-C_CLOSEOUT.md)，code SHA `c0996b41`，merge-gate 本機全套 E2E 123 passed / 4 skipped）。`P4-D — Spells, Conditions, Concentration & Reactions` 於 2026-09-16 在 branch `feat/p4d-spells-effects-reactions` 關門並合併回 `main`（[P4-D closeout](../docs/P4/P4-D_CLOSEOUT.md)，code SHA `38620d46`，merge-gate 本機全套 E2E 123 passed / 4 skipped）。P4 起每個 Subphase 關門後各自合併回 `main`。**`P4-E — Quick Combat UI, DM Adjudication & AI Tool Surface` 於 2026-09-17 在 branch `feat/p4e-quick-combat-ui-adjudication-ai-tools` 關門（[P4-E closeout](../docs/P4/P4-E_CLOSEOUT.md)，code SHA `08e46b19`，merge-gate 本機全套 E2E 124 passed / 4 skipped，含新 `p4e-quick-combat.spec.ts`；步驟紀錄見 [docs/P4/P4-E實作紀錄.md](../docs/P4/P4-E實作紀錄.md)，worker 流程見 `docs/others/conductor-handbook.md`）並以 `--no-ff` 合併回 `main`（merge `ab576222`）。`P4-F — Full P4 Integration & Closeout` 於 2026-09-19 在 branch `feat/p4f-full-p4-integration-closeout` 關門（[P4-F closeout](../docs/P4/P4-F_CLOSEOUT.md)，code SHA `651a14d0`，merge-gate 本機全套 E2E 125 passed / 4 skipped + disabled-pack 7 passed、全套 backend 1809 passed；F8 真實 ChatGPT Web Combat gate 三場，第一場抓到的 adjudication 分流 / Quick Enemy attack 輸入 / Dodge 缺陷以 F8a～F8c 修正後重跑通過；步驟紀錄見 [docs/P4/P4-F實作紀錄.md](../docs/P4/P4-F實作紀錄.md)）並以 `--no-ff` 合併回 `main`（merge `7ef02d13`）。**P4 Phase 至此全部關門。** **工程優化軌 `U01` 已建立，`U01-A — E2E Database Isolation & Fast Test Foundation` 於 2026-09-14 在 branch `u01-a-e2e-isolation` 關門（`docs/U01/U01-A.md` §14）：E2E 改走獨立 `adventure_table_e2e` + `server-e2e` 8001 / `web-e2e` 5174，reset 有 `current_database()` hard guard，本機 `npm run test:e2e:docker` 不再碰 daily `adventure_table` 也不再重啟 daily `server` / `web`；同機 Playwright 主套件 10.1m → 10.1m 無倒退，wrapper 總 wall-clock 10.6 分成為後續 U01 加速 baseline。U01 整體維持 open，不改寫 P Roadmap，可與 P4 並行。M01 track 下一個未使用字母為 M01-P，尚無已拍板 scope。**

## Subphase 進度

以下每個 Subphase 各列一項；✅ 代表該項已關門，🟡 代表實作與自動化 gate 完成但仍有明確延期的驗收項，⬜ 代表正式規格已存在但尚未實作。未結清的驗收限制見 [已知問題.md](../已知問題.md)；Phase 關門不表示所有限制已消失。詳細規格、設計與證據由各 Phase 文件承擔。

### P0

| Subphase | 狀態 | 重點 |
|---|---|---|
| **P0-A — Project Foundation** | ✅ | Project / DB / tests / CI baseline |
| **P0-B — Character-Relevant SRD Foundation** | ✅ | Character-relevant SRD / ContentRegistry / validation |
| **P0-C — Character Core & Persistence** | ✅ | Build Version / Current State / persistence / fixture |
| **P0-D — Character Rules & Backend API** | ✅ | Character rules / DTO / APIs / overrides |
| **P0-E — Character Sheet & State UI** | ✅ | 三頁 Character Sheet / state UI / E2E |
| **P0-F — Full P0 Integration & Closeout** | ✅ | Full regression / persistence / smoke / closeout |

### P1

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

### M01

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
| **M01-N — Character Sheet HTML Export** | ✅ | 角色卡輸出成單向、只給人看的自足 HTML；使用者自選「角色配置」／「當前快照」，含 A4 列印樣式與匯出專屬物品閱讀順序；client-side、不新增 endpoint、永不可 Import |
| **M01-O — XGE & TCE Feat Expansion** | ✅ | XGE 15 個 Racial Feats + TCE 15 個 Feats；沿用 M01-K Feat acquisition / prerequisite / nested-choice 地基，補 ancestry/size prerequisite、canonical Fighting Style / Invocation / Metamagic option-pool reuse、Feat-granted spells、retraining、Metamagic Adept restricted Sorcery Points、雙語與 focused E2E；Combat/Reaction/Roll 效果不偷跑 P4 |

> **M01 保持 open。** A～O 是目前已交付的 baseline。下一個未使用字母是 **M01-P**，沒有預留給「Full M01 Closeout」的字母。

### M02

| Subphase | 狀態 | 重點 |
|---|---|---|
| **M02-A — Locale Foundation & Runtime Switch** | ✅ | 全站單一 locale state、一鍵切換、browser 記憶、不動 Draft / Character domain state |
| **M02-B — Full UI Copy Localization** | ✅ | 既有 frontend UI copy 全部進 localization resources，含 accessibility text；Builder 七個具名 step 全覆蓋 |
| **M02-C — Localized Content Model & Terminology Contract** | ✅ | canonical / overlay 邊界、localized resolver、field-level localizable policy、roleplay suggestion identity、glossary 定稿 |
| **M02-D — SRD 5.1 Names & Structured Text** | ✅ | 依 policy 完成目前 user-visible SRD names / labels / structured text 雙語覆蓋 |
| **M02-E — SRD 5.1 User-Visible Descriptions** | ✅ | SRD spell / feature / condition `data.desc.*` zh-TW authoring；canonical-driven coverage / leakage / mechanics / Markdown gates；item / background hidden long-form 延後 |
| **M02-F — PHB / SCAG / GoS Localization** | ✅ | 依 policy 完成 M01-B / M01-C current-surface non-SRD content；既有繁中 reference 作 priority input |
| **M02-G — Localized Search, Errors & Completeness Gates** | ✅ | localized search / alias / sort、error code + localized message、policy-driven completeness / orphan guard |
| **M02-H — Full M02 Integration & Closeout** | ✅ | structured disabled-reason / issue params、全站雙語 crawl + overflow gate、Draft / Character state integrity、translation evidence彙整、doc-sync / CC BY NOTICE |

### M03

| Subphase | 狀態 | 重點 |
|---|---|---|
| **M03-A — Content Root Path Abstraction & Enabled-Pack SSOT** | ✅ | Content / Rules / Localization / DB path resolver、frozen/repo fallback、`Settings.enabled_content_packs` SSOT、consumer 接線、legacy path static guard、subset unresolved 語意收窄 |
| **M03-B — Character JSON Schema, Export & Builder Provenance** | ✅ | Character export envelope、完整 version chain / current state、`builder_provenance` migration 與 versioned draft seed SSOT |
| **M03-C — Character JSON Import via Builder Draft** | ✅ | JSON preview / validation、StableKey unresolved 分析、new identity import、`draft` / `draft_with_history_loss` landing mode |
| **M03-D — SQLite Migration Chain Gate & FK PRAGMA** | ✅ | SQLite migration chain、foreign key enforcement、standalone DB lifecycle 與 migration compatibility gate |
| **M03-E — Standalone Packaging & Launcher** | ✅ | `app.standalone` entry、capability endpoint、SPA fallback、PyInstaller、browser launcher、SQLite beside executable |
| **M03-F — Windows CI Build, Release & Import Boundary Test** | ✅ | Windows frozen build、artifact flow（本機發版，CI 不建 GitHub Release）、standalone import boundary 與未來 P2 dependency leakage gate |
| **M03-G — Full M03 Integration & Closeout** | ✅ | web ↔ standalone ↔ standalone JSON round-trip、frozen runtime smoke、雙語 / persistence / migration / capability 全整合 closeout；E.9 乾淨 Windows 11 冷啟動已於 2026-09-06 後續補驗完成 |

### P2

| Subphase | 狀態 | 重點 |
|---|---|---|
| **P2-A — Room Foundation & Web Entry** | ✅ | Room access / Room-first Web landing、Character JSON v1 lock、Alembic shared-vs-web branch split、standalone boundary |
| **P2-B — Room Character Workspace** | ✅ | Character / Draft Room scope、atomic workspace association、legacy global data claim、Web global Character route收口、Standalone維持 Room-less |
| **P2-C — Campaign & Party Roster** | ✅ | Campaign lifecycle Owner-only、Room `active_campaign_id` 與 campaign status 分離、same-Room Roster（idempotent add）、same Character multi-Campaign 共用同一份 Current State、Roster reference 擋 Character permanent delete |
| **P2-D — Seat, Controller & Lobby** | ✅ | Room authority vs Seat Role vs Controller、DM Seat assignment Owner-only、Human / None controller、Lobby 綁 Room 目前 active Campaign、Player Seat 選角只收 `active` / `inactive` Roster、選角收斂只發生在寫入路徑、presence 沿用 P2-A heartbeat；AI shape only，不提前接 P3 |
| **P2-E — Session Lifecycle & Late Join** | ✅ | Start / End / Abandon、Owner-assigned DM Seat controller 才能 Start、fixed DM Controller（Owner 只能 Abandon 不能接管）、immutable Active Character、Late Join、`active_character_session_leases` 全域併發保證、active Session 期間的 Character / Builder write scope、Seat / Campaign / Character 的 Session history guard、Resume 只組合既有 truth 不建第二份 snapshot |
| **P2-F — Full P2 Integration & Closeout** | ✅ | Journey 5／6／7／8 browser 證據、Seat 選角併發的真 PostgreSQL 測試、完整 dataset restart 整合、`P2 Non-E2E` 補上 `windows-standalone` 與 `test_m03c_migration.py`；修掉 Web 從未宣告 `session` capability 而讓 Session 頁全數被 boundary 擋死的缺陷 |

### P3

| Subphase | 狀態 | 重點 |
|---|---|---|
| **P3-A — Session Table Runtime & Event Stream** | ✅ | durable per-Session runtime、ordered event cursor、Server-side audience filter、initial Resume + incremental sync、restart persistence、async/no-DB-hold event wait與waiter starvation gate、避免P2 Resume N+1變高頻同步 |
| **P3-B — Exploration, Chat & Actions** | ✅ | Main Stage text/image、最小Room-scoped Stage upload、Dialogue / Action / OOC / Whisper DM / Narration、slash command 收斂成同一 typed input、DM proxy 保存 acting/subject、Whisper Server 過濾、Stage與Chat分離、不建立Scene/Asset Library |
| **P3-C — Roll, Check & PendingAction** | ✅ | RollGroup / RollRequest / Result、Server RNG、Group / Secret / physical / quick roll、PendingAction、formal roll idempotency、actor-neutral Character State + event atomic boundary；AI resolver留P3-D接線 |
| **P3-D — AI Controller, Scoped Token & Handoff** | ✅ | typed TableActorContext、P2 Human-only Session/live-write授權入口migration、hashed scoped AI Join Token、Seat current grant + controller_epoch SSOT、Session/Participant grant-generation snapshots與三條CHECK migration、finite-TTL pre-session AI DM grant、origin-only Take Back + Owner/DM admin recovery、Player Human ↔ AI handoff、AI DM可作新Session固定DM Controller |
| **P3-E — AI Tool Surface & Event Delivery** | ✅ | MCP `2026-07-28` stateless Streamable HTTP入口、shared application services、structured tools/errors、`get_pending_events` / `wait_for_event`沿用P3-A async wait、standalone 不掛 `/mcp`；真 external MCP client HTTPS E1 於 P3-F closeout 由 Claude Code 2.1.260 經 Tailscale HTTPS 執行通過 |
| **P3-F — Full P3 Integration & Closeout** | ✅ | Human/AI Exploration journeys、secret/group roll、Late Join、AI handoff、AI DM、grant TTL/epoch/Take Back authorization、restart、cross-scope matrix、PostgreSQL concurrency、waiter resource safety、P2 caller regression、standalone / bilingual / full regression closeout；`P3 Full-Stack E2E` CI run `34587347309` 全綠 |

### M04

| Subphase | 狀態 | 重點 |
|---|---|---|
| **M04-A — Web Chat MCP Preflight** | ✅ | 獨立極小 HTTPS 測試 server（`tools/m04a-webchat-preflight/`，管理 endpoint 只監聽 loopback、request／response 同等遮罩）；2026-09-12 以真實 ChatGPT Web Plus 經 Tailscale Funnel 實測 OAuth/DCR、`2026-07-28` `server/discover → tools/list → tools/call`、read/write、role-scoped catalog、Refresh + 新對話的 catalog 更新規則、revoke/reconnect、120 秒 long-poll；目標平台判定 ChatGPT Web Plus，Claude chat 階梯未觸發；結論見 `M04-A_PREFLIGHT.md` A.7；Closeout CI run `34663200995`，Merge Gate E2E `34663806640` |
| **M04-B — Adventure Table Web Chat Integration** | ✅ | web migration `0021_m04b_ai_oauth`（四張 `ai_oauth_*` 表，standalone 不建）；`/.well-known/oauth-*`、`/mcp/oauth/{register,authorize,token,revoke}`；authorize 頁雙語、只貼 AI Join Token；一張 grant 一個 active family，`client_id` 非授權識別；access／refresh 都重驗 P3-D authority，grant revoke／Take Back／Session End／Abandon 同 transaction 撤 family；`ADVENTURE_TABLE_MCP_PUBLIC_ORIGIN` 供 TLS 入口廣播公網 origin；不需相容層、catalog 沿用 P3 role-scoped、`wait_for_event` 上限維持 60s；2026-09-12 真實 ChatGPT Web Plus 經 Tailscale Funnel 完成 DM 場（narration → wait → Human action → AI 回應 → Abandon → 401 + refresh 400）與 Player 場（handoff → reconnect 同 client_id 新 family → dialogue → request_check → `roll_pending` → Take Back → 401 + refresh 400）；證據見 [M04-B_CLOSEOUT.md](../docs/M04/M04-B_CLOSEOUT.md)；CI `M04-B Non-E2E Regression` run `34673796557` |
| **M04-C — AI Join Kit, Server-hosted Guide & Other Client Compatibility** | ✅ | `GET /mcp/guide`（雙語、無需認證、不碰 DB、standalone 不掛）；tool description 由 catalog 同源產生且寫明何時被接受，DM catalog 在 `start_session` 前後相同；`get_session_context.briefing` 改為強制逐步迴圈（stage → narration → `wait_for_event` 120 秒 × 最多 5 次）並帶 MCP 呼叫判定規則，`stage_unset`／`next_required_action` 機器可讀提示；`server/discover.instructions` 指向 guide；Lobby／Session 面板產出本機／公網雙 URL 的可複製／下載 AI Join Kit，`GET /api/mcp/public-origin`；`wait_for_event` 上限 60 → 120 秒；2026-09-12 真實 ChatGPT Web Plus 憑 kit 進桌（使用者人工），同日回填 `request_check` 友善 ref normalize（`0bbb9fa`）、擲骰提示進 Chat（`6890811`）、E2E reset 改 TRUNCATE CASCADE（`e9c310b`）；**Bearer／純 HTTP 路徑與 C.9 相容記錄依使用者拍板延後**；證據見 [M04-C_CLOSEOUT.md](../docs/M04/M04-C_CLOSEOUT.md)；CI `M04-C Non-E2E Regression` run `34701747258`，`P3 Full-Stack E2E` run `34703269124` |

### U01

| Subphase | 狀態 | 重點 |
|---|---|---|
| **U01-A — E2E Database Isolation & Fast Test Foundation** | ✅ | 2026-09-14 關門：`adventure_table_e2e`、`server-e2e` 8001 / `web-e2e` 5174、wrong-DB hard guard、`p3-e2e.yml` 改走同一支 `test:e2e:docker`（CI 補上 xge-less 第二輪）、歷史 E2E workflow deprecated；CI run `34800987506` 全綠，同機主套件 10.1m → 10.1m |

> **U01 保持 open。** U 類是 Test / Development Efficiency Optimization 長期優化軌，不改寫 P Roadmap；每個 Subphase 使用 `docs/Uxx/` 單檔格式，各自關門並留下證據。

### P4

| Subphase | 狀態 | 重點 |
|---|---|---|
| **P4-A — Monster & Combatant Foundation** | ✅ | pinned SRD 5.1 Monster corpus 334 / Beast 87（blob sha 鎖進 manifest）、Monster Template / Instance / Combatant、Quick Enemy、canonical `MonsterAction` + `automation_level`、1837 個 zh-TW label、enemy secrecy projector、真 PostgreSQL migration gate、Standalone Template content / multiplayer Instance boundary；[closeout](../docs/P4/P4-A_CLOSEOUT.md) |
| **P4-B — Combat Lifecycle, Initiative & Action Economy** | ✅ | Campaign-scoped durable Combat（migration `0023` / `0024`）、one-active-combat 真 PostgreSQL 併發 gate、P3-C formal-roll initiative（PC / monster group / adv-dis / tie / entrant）、Server authoritative turn advance 與 Action / Bonus / Reaction / Extra Attack / surprise economy、跨 Session resume 與 controller rebinding、withdraw / remove / no-hostile warning、End Combat cleanup、16 條 Human HTTP route；[closeout](../docs/P4/P4-B_CLOSEOUT.md) |
| **P4-C — Attack, Damage & Core Action Resolution** | ✅ | migration `0025`（death-save 欄位、`combat_actions` resolution 欄位）、`ResolvedAttack` normalization、P3-C formal-roll attack / save / death save、Nat 20 / Nat 1、semantic `apply_damage` / `apply_healing` boundary（Temp HP、Monster affinity、0 HP / massive damage / death saves、DM correction path）、`dm_adjudication_required` geometry gate、Grapple / Shove、真 PostgreSQL 併發與 rollback 證據、13 條 Human HTTP route、14 個 `combat_*` MCP tool；[closeout](../docs/P4/P4-C_CLOSEOUT.md) |
| **P4-D — Spells, Conditions, Concentration & Reactions** | ✅ | 無 migration（Character State additive JSON）、`authorize_character_spell` / `spend_character_spell` 單一資源來源、Monster stat-block casting source、單體 `cast_character_spell` 與 AoE propose / resolve durable transaction、14 個 2014 Conditions + Exhaustion typed semantics 與 zh-TW、Temporary Effects、Concentration canonical state + CON save + cross-combatant linked-effect cleanup、durable ReactionWindow / Ready / DM-only OA / Legendary、JSON v1 與 Web↔Standalone roundtrip 證據；[closeout](../docs/P4/P4-D_CLOSEOUT.md) |
| **P4-E — Quick Combat UI, DM Adjudication & AI Tool Surface** | ✅ | migration `0026`（Monster concentration）、Monster persisted cast、Concentration roll routing、audience-projected `GET .../combat/detail` 與 Player-safe event payload、spell / reaction / concentration / adjudication / Monster Instance REST、38 個 role-scoped `combat_*` MCP tool + `get_session_context` combat context 與雙語 briefing、Session table Quick Combat Stage / DM 控制 / Quick Action Bar / adjudication panel、compact bilingual Combat Log、Combat REST error code 雙語、Playwright `p4e-quick-combat.spec.ts`；[closeout](../docs/P4/P4-E_CLOSEOUT.md) |
| **P4-F — Full P4 Integration & Closeout** | ✅ | migration `0027`～`0030`、Monster outcome / bookkeeping / reveal、escape_grapple、state PATCH P4-D 欄位、真 PostgreSQL restart、full browser journey + Session boundary + 真 process restart、conditions / exhaustion / Dodge → attack / save modifier 與 auto-fail、adjudication 工具分流 + `advance_turn` hint + `table_conflict` detail、Quick Enemy attack 輸入正規化、真實 ChatGPT Web Combat gate 三場（F8）；[closeout](../docs/P4/P4-F_CLOSEOUT.md) |

## 已解限制的歷史記錄

| 項目 | 當時結論 | 證據 |
|---|---|---|
| ~~`test:e2e:docker` 只 rebuild `web`~~ | **P3-B 已收斂。** `apps/web/scripts/e2e-docker.mjs` 改成 `docker compose up -d --build server web`，`e2eDockerScript.test.ts` 釘住這個行為，stale backend image 不再是操作者責任 | [P3-B closeout](../docs/P3/P3-B_CLOSEOUT.md)「Verification evidence」 |

## 已交付 Phase 文件索引

長期 open 的 M01 此處指已交付 baseline；當前工作仍看簡報。

| Phase | 實作規格 | 開發設計方針 | 測試指南 |
|---|---|---|---|
| P0 | [規格](P0/實作規格.md) | [設計](P0/開發設計方針.md) | [測試](P0/測試指南.md) |
| P1 | [規格](P1/實作規格.md) | [設計](P1/開發設計方針.md) | [測試](P1/測試指南.md) |
| M01 | [規格](M01/實作規格.md) | [設計](M01/開發設計方針.md) | [測試](M01/測試指南.md) |
| M02 | [規格](M02/實作規格.md) | [設計](M02/開發設計方針.md) | [測試](M02/測試指南.md) |
| M03 | [規格](M03/實作規格.md) | [設計](M03/開發設計方針.md) | [測試](M03/測試指南.md) |
| P2 | [規格](P2/實作規格.md) | [設計](P2/開發設計方針.md) | [測試](P2/測試指南.md) |
| P3 | [規格](P3/實作規格.md) | [設計](P3/開發設計方針.md) | [測試](P3/測試指南.md) |
| M04 | [規格](M04/實作規格.md) | [設計](M04/開發設計方針.md) | [測試](M04/測試指南.md) |
| P4 | [規格](P4/實作規格.md) | [設計](P4/開發設計方針.md) | [測試](P4/測試指南.md) |
