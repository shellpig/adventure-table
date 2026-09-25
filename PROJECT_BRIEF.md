# Adventure Table 專案簡報

最後更新：2026-09-24

本檔是**當前進度、下一步、Roadmap 與索引的單一事實來源**，上限 **16,000 UTF-8 bytes**。歷史進度見 [ROADMAP_HISTORY](docs/ROADMAP_HISTORY.md)，未解問題見 [已知問題](已知問題.md)；不在本檔累加歷史過程、測試數字或決策全文。

## 專案定位與目前能力

朋友間私人使用的輕量 **D&D 5e 2014 Web VTT**。真人 DM 主要靠口頭敘事；網站負責共享、同步、計算、保存、權限及外部 AI 接入。不是 CRPG，不做全能平台，網站本身不接 LLM API。

已交付角色創建／角色卡／升等／版本、Room／Campaign／Seat／Session、Exploration、正式擲骰、Human／AI 交接、MCP／OAuth／AI Join Kit、Quick Combat，以及 Windows 離線創角與 Character JSON exchange。支援 `zh-TW`／`en`；內容由 SRD 5.1 起擴充。

技術基礎：React／TypeScript／Vite、Python／FastAPI／Pydantic、SQLAlchemy／Alembic；Web PostgreSQL、Standalone SQLite。啟動與發版見 [README](README.md)；產品行為以 [規格企劃](規格企劃.md) 為準，不以本摘要取代契約。

## 當前狀態與下一步

- **P4 已全部關門並合併回 `main`**：P4-F code `651a14d0`，merge `7ef02d13`；證據見 [P4-F closeout](docs/P4/P4-F_CLOSEOUT.md)。歷史步驟不再作開場必讀。
- **M05（Session History Continuity & Owner End for AI DM Sessions）已於 2026-09-20 當日開工並全部關門、合併回 `main`**：M05-A Owner 可正常 End AI DM 的 Session；M05-B 聊天串向上翻頁越過 Session 邊界（專用 history read scope，不擴大 gameplay actor）。證據見 [M05-A closeout](docs/M05/M05-A_CLOSEOUT.md)、[M05-B closeout](docs/M05/M05-B_CLOSEOUT.md)；逐項表已移至 ROADMAP_HISTORY。
- **P6-A～P6-E 已關門並合併回 `main`**：Adventure authoring／Room asset、Campaign Runtime、AI context／write-back、Import Source／Draft 已交付；證據見各 [closeout](docs/P6/P6-E_CLOSEOUT.md) 與 [歷史進度](docs/ROADMAP_HISTORY.md)。**P6-F 已通過關門驗證，待合併回 `main`**（[closeout](docs/P6/P6-F_CLOSEOUT.md)）。**P6-G 的 G1～G4 已在依賴 F 的 `codex/p6g-integration` 分支完成**（G4 真實網頁版 AI agent：ChatGPT Web journey＋Claude 網頁版跨 Session 讀回）；剩 G5 Phase closeout。合併順序仍為 F 後 G，P6 關門後先做 M06，再回 P5 Tactical Combat。
- **P6 契約固定 A～G**；P6-G 接手讀 [實作規格](docs/P6/實作規格.md)、[開發設計方針](docs/P6/開發設計方針.md)、[測試指南](docs/P6/測試指南.md) 的 P6-G 與 [實作紀錄](docs/P6/P6-G實作紀錄.md)。既有技術決策與驗證證據住各 Subphase closeout，不在本簡報重複。列出下一步不代表 merge 授權。
- **M01／U01 保持 open，不阻塞 P Roadmap**。M01-A～O、U01-A 已關門；下一個未使用字母分別為 M01-P、U01-B，兩者下一項 scope 均未拍板，不建立虛構的待辦 Subphase。
- **M06（AI Long-Session Hosting Efficiency）契約已定、待開工**：插在 P6 關門後、P5-A 前；M06-A `wait_for_event` 實際等待上限對齊 120 秒、M06-B 自己寫入的 echo 不喚醒 wait、M06-C MCP `roll.resolved` 精簡投影。
- **P5 已有完整契約但暫後移；P7～P8 保持大 Phase**，不提前拆分或設計 schema／API／module。

### P6 Subphase 進度

✅＝已關門並合併；☑️＝關門驗證通過、待合併；🟡＝進行中；⬜＝正式契約已存在、尚未實作。當前 Phase 一列一個 Subphase；完成的 step 狀態只住該 Subphase 實作紀錄，不寫進本檔。

| Subphase | 狀態 |
|---|---|
| P6-A — Adventure Definition & Campaign Attachment | ✅ 2026-09-20 |
| P6-B — Campaign Runtime World State | ✅ 2026-09-21 |
| P6-C — AI Context & Retrieval | ✅ 2026-09-21 |
| P6-D — AI DM Write-back & Exploration Integration | ✅ 2026-09-22 |
| P6-E — Adventure Source & Import Draft | ✅ 2026-09-22 |
| P6-F — Import Review, Finalization & Importer MCP | ☑️ 2026-09-23，待合併 |
| P6-G — Full P6 Integration & Closeout | 🟡 G1～G4 已完成，G5 待做；依賴 P6-F 分支 |

## Phase Roadmap

Phase 編號維持原產品分工；2026-09-19 起目前執行順序調整為 **P0→P4 → M05 → P6 → M06 → P5 → P7 → P8**。這不是重編 Phase：P5 仍是 Tactical Combat、P6 仍是 Adventure / Campaign Runtime。M 為插入式維護／內容擴充，U 為測試／開發效率優化，兩者均可長期 open。

| Phase | 主題／狀態 |
|---|---|
| P0／P1 | Character Core／Builder；已關門 |
| M01 | Character Content Expansion／Maintenance；長期 open，已完成項見歷史表 |
| M02／M03 | 雙語／Standalone；已關門（含乾淨 Windows 11 冷啟動補驗） |
| P2／P3 | Room／Campaign／Session／Seat、Exploration／Roll／AI；已關門 |
| M04 | Web Chat MCP／OAuth／AI Join Kit；已關門，目標平台為 ChatGPT Web Plus |
| U01 | Test / Development Efficiency；長期 open |
| P4 | Quick Combat；已關門 |
| M05 | Session History Continuity／Owner End for AI DM；已關門（2026-09-20），插在 P4 與 P6-A 之間 |
| M06 | AI Long-Session Hosting Efficiency；契約已定，插在 P6 關門後、P5-A 前 |
| P5 | Tactical Combat；契約已定案，依使用者決定延至 P6 與 M06 之後實作 |
| P6 | Adventure Definition／Importer、Campaign Runtime、AI DM context／write-back；**當前 Phase，P6-F 待合併，P6-G 工作分支已開工** |
| P7 | Timeline、Snapshot／Restore、broader Archive／Import／Export；角色 JSON 已由 M03 先行，不做 gameplay Undo |
| P8 | 全流程 QA／Polish、權限、reconnect、效能、Responsive UI |

已關門的逐項表與關門摘要只住 [ROADMAP_HISTORY](docs/ROADMAP_HISTORY.md)；查歷史時按 Phase／Subphase 定位，不整份讀。

## 接手時必須保留的跨 Phase 約束

修改相關模組時須查下列正式契約。

- **產品硬原則**：Server authoritative；Human UI／MCP／future Site Tools 共用 backend logic；秘密由 Server projection 過濾；敘事輔助資料 optional 不變 mandatory；不接 LLM API、不保存外部模型 API key。新增或首次 expose 的內容須同時交付 `zh-TW`／`en`，locale 不改 canonical gameplay data。見 [AGENTS](AGENTS.md) 產品／工程守則。
- **Character／多人邊界**：Web Room-first、Standalone Character-first；Character／Draft 屬 Room，同 identity 不跨 Room（用 export／import／copy-as-new）。同 Room 多 Campaign 可 reference 同一 Character、共用 Current State，但同 Character 不可同時進兩場 active Session。見 [P2 設計](docs/P2/開發設計方針.md)。
- **Standalone／migration**：Character Core／Builder／Interop／`app.standalone` 不得反向依賴多人層或 `app.main`。新增多人 module／table／route 時同步檢查 `test_m03_import_boundary.py`、`test_m03d_schema_parity.py`；shared Character migration 走 `character` track，Standalone 只升 `character@head`。修改共享 Character contract 的 M 工作須驗證所有直接受影響的已交付 P Phase 與 Web↔Standalone exchange。
- **Character JSON v1**：`schema_version="1"`、`schema_status="locked"`、`export_type="character"`；仍接受 M03 legacy `unstable` 並 normalize。不得塞入 Room／Campaign／Seat／Session identity。見 [M03 設計](docs/M03/開發設計方針.md)、[P2 設計](docs/P2/開發設計方針.md)。
- **Human／AI 授權**：沿用 `TableActorContext` 與 `live_character_write_scope()`，不建 AI-specific bypass。每次 AI request 重驗 Seat current grant binding＋單調 `controller_epoch`；grant／Session／Participant generation 是 snapshot，不能取代 current authority；歷史 migration `0013`／`0014` 不改寫。見 [P3-D 設計](docs/P3/開發設計方針.md)。
- **AI lifecycle／Take Back**：pre-session DM grant 有限 TTL、只可最小 context＋Start；Seat／Campaign／Room active Campaign／Owner revoke 等失效條件沿用 P3-D，Start 後綁 Session，End／Abandon 原子撤銷；M05-A 起 Owner 可對 **AI DM** 的 active Session 正常 End（Human DM 場仍只有 Abandon），不構成接管。Player self-service Take Back 只認原 `handoff_return_access_session_id`；遺失時由 Owner／DM reassignment＋revoke＋epoch＋audit，不能以姓名／新 access session 冒充同一人；DM controller 一場固定。見 [P3-D 規格](docs/P3/實作規格.md)。
- **OAuth 不另造授權**：access／refresh 均重驗同一 P3-D authority；一張 grant 一個 active token family，`client_id` 不是 Seat 身分，OAuth 不寫 Seat／Session／Participant。Guide／briefing 只講操作守則，Adventure context 留 P6。見 [M04 設計](docs/M04/開發設計方針.md)。
- **事件與 wait**：durable event＋DB cursor 是真值；HTTP wait async，await 不持有 DB connection／transaction、不長占 sync worker，wake／timeout 後重查 cursor，保留 waiter 不餓死一般 request 的證據。P3 event 不等於 P7 跨 Session Timeline／Snapshot。見 [P3 設計](docs/P3/開發設計方針.md)。
- **Combat／Standalone**：Combat 以 Campaign 為 root，可跨 Session End／Abandon 延續；entry identity 是 Character／Monster Instance。Monster Template 可共用於 Standalone，Instance／Combat schema 不可。Monster 長文 `desc` 首次 expose 時須補齊 zh-TW；來源與 count 以 P4-A pinned manifest 為準。見 [P4 設計](docs/P4/開發設計方針.md)。
- **Combat 共用寫入邊界**：active Combat HP 只經 semantic damage／healing，Player raw patch 被拒、DM absolute set 要 `correction_reason`；Concentration／Exhaustion／Death Save／Temporary Effects 住 shared Character Current State。Spell cast 沿用 `authorize_character_spell` → `spend_character_spell`，Character／Monster casting source 都合法；Concentration CON save 由 `CombatConcentrationRepository.complete_check` 消費。敵人精確 HP／AC／hidden resources 不送 Player。Combat mutation 須呼叫 `TableEventService.notifier`，前端把帶 `combat_id` 的 `roll.*` 視為 Combat 變更。見 P4-C～E 正式契約。
- **M05 歷史讀取邊界**：已結束 Session 的事件唯讀；讀者 scope 以目前 Human 控制的 Campaign Seat 為單位，DM 層跟該場 `dm_seat_id`；舊事件只進聊天串、不進本場 seq-based 投影；MCP `get_session_context` 與 Resume 仍只含本場。P7 Timeline 疊在 M05-B 的讀取入口上。見 [M05 設計](docs/M05/開發設計方針.md)。
- **P6 先於 P5 的邊界**：P6 必須在沒有 Tactical geometry 的情況下完整運作；Adventure 是可附加的世界／冒險資料包，Campaign 可零或多個 Adventure，真正 mutable truth 在 Campaign Runtime。Current Scene／Situation optional；P6 map/image 只作 Stage／世界素材；AI DM 重要世界變化需 write-back，Player projection 不得含 secret。見 [P6 規格](docs/P6/實作規格.md)。
- **P5 承接 P4＋P6**：Quick 不依賴 Tactical geometry；Tactical 以 2D ground spatial facts 接入既有 P4 resolution，不另造戰鬥／施法／Reaction／RNG／secrecy。P5 Combat board runtime 不自動升格成 P6 Campaign world truth；需要永久世界改變時走 P6 world service。見 [P5 規格 §3、§4](docs/P5/實作規格.md)。
- **U01 隔離與 M／U 範圍**：加速不得犧牲 correctness、資料隔離或既有行為。U01-A 的 E2E 只使用 `adventure_table_e2e`＋獨立服務（8001／5174），不碰 daily DB。M 插入不重編既有順序；每個已拍板 Subphase 各自關門，完整規則見 AGENTS。

## 未結清事項與驗收限制

完整索引見 [已知問題](已知問題.md#跨-phase-限制與驗收索引)。未解項目不因 Phase 關門而完成；舊驗收缺口先核對後續 closeout，不直接當成目前缺陷。

- **P6-G 接手**：G1～G4 已完成（empty Campaign／Adventure-driven journey、restart／next Session、secrecy、Quick Combat、Standalone boundary、真實網頁版 AI agent gate 的證據都在各 step 檔），不重驗。G5 只剩全套 Docker E2E、依 G.8 的靜態審核與 P6 closeout；見 [G5](docs/P6/P6-G_steps/G5.md)。P6 不放寬 P3-D pre-session AI grant，也不提前做 P5 geometry 或 P7 Timeline／Snapshot。
- **後續 P5 接手**：Quick range 裁定、Dodge「能看見攻擊者」、frightened 來源可見性，依 [P4-F closeout](docs/P4/P4-F_CLOSEOUT.md) 已知限制與 P5 契約處理。
- **後續 M、尚未拍板**：spell save 的 conditions pipeline、`get_resolution_event` O(n)、Monster `desc` 尚未 expose、死亡／倒地不起標籤；另有 Character 抗性缺 machine-readable 欄位、`is_hostile` 仍由 subject kind 決定等既有邊界。見 P4 各 Subphase closeout／設計，不自行擴入 P5。
- **延期驗收／內容**：M04-C Bearer／純 HTTP／非目標平台相容記錄、M01-O deferred Feats，見限制索引。
- **測試效率／環境**：Builder 等待、M01-J browser 缺口、Windows Vite 見 KI 條目；U01 後續依 [U01-A §8 與 baseline](docs/U01/U01-A.md)。

## 文件索引與閱讀方式

開場確認 [AGENTS](AGENTS.md)、本檔與 `git log --oneline -10`。若最新 AGENTS 已完整載入上下文，不再全文重讀；其餘文件依任務搜尋標題，只讀相關段落與必要共用前言。

| 要找什麼 | 入口 |
|---|---|
| 修改授權、產品／工程守則、測試與 commit／push gate | [AGENTS](AGENTS.md) |
| 產品行為、玩法、權限、UI、第一版明確不做 | [規格企劃](規格企劃.md)，按章節讀 |
| 啟動／開發／發版、單機版操作 | [README](README.md)、[繁中](README-standalone.zh-TW.txt)／[English](README-standalone.en.txt) |
| 本機 Python／E2E／外部 reviewer 指令 | [local-tools](docs/others/local-tools.md)，按工作讀 |
| 派工／接手與新實作紀錄格式 | [conductor-handbook](docs/others/conductor-handbook.md)，共通段落＋所選 worker |
| 已關門 Subphase／驗收歷史 | [ROADMAP_HISTORY](docs/ROADMAP_HISTORY.md)、各 Phase 的 `*_CLOSEOUT.md` |
| 已知限制、未解問題與驗收缺口 | [已知問題](已知問題.md) |
| 基礎技術選型背景 | [技術棧討論](技術棧討論.md)，不是全專案 architecture spec |
| U 類單檔契約與證據 | [U01-A](docs/U01/U01-A.md) |

P／M 三份文件：**實作規格＝完成後必須為真；開發設計方針＝具體實作契約；測試指南＝驗收方式**。只讀所屬 Subphase 與必要共用前言；U 類使用單一 Subphase 文件。

| Phase | 實作規格 | 開發設計方針 | 測試指南 |
|---|---|---|---|
| M01 | [規格](docs/M01/實作規格.md) | [設計](docs/M01/開發設計方針.md) | [測試](docs/M01/測試指南.md) |
| P4 | [規格](docs/P4/實作規格.md) | [設計](docs/P4/開發設計方針.md) | [測試](docs/P4/測試指南.md) |
| P5 | [規格](docs/P5/實作規格.md) | [設計](docs/P5/開發設計方針.md) | [測試](docs/P5/測試指南.md) |
| M05 | [規格](docs/M05/實作規格.md) | [設計](docs/M05/開發設計方針.md) | [測試](docs/M05/測試指南.md) |
| P6 | [規格](docs/P6/實作規格.md) | [設計](docs/P6/開發設計方針.md) | [測試](docs/P6/測試指南.md) |
| M06 | [規格](docs/M06/實作規格.md) | [設計](docs/M06/開發設計方針.md) | [測試](docs/M06/測試指南.md) |

其餘已交付 Phase 的三份文件見 [歷史文件索引](docs/ROADMAP_HISTORY.md#已交付-phase-文件索引)。

`docs/暫用規則資訊/` 只供內容 authoring／review，runtime 規則住 `data/`，不解析 `docs/`；`舊文件/` 為封存，完全忽略。
