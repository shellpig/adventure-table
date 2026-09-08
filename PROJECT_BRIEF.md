# Adventure Table 專案簡報

最後更新：2026-09-09

本檔是**當前進度、Roadmap、下一步與文件索引的單一事實來源**，供新的 AI Session 或實作者接手。產品行為以 [規格企劃.md](規格企劃.md) 為準；實作契約與歷史驗收證據請依下方索引查閱，不在本檔重述。

## 專案定位與目前能力

Adventure Table 是朋友間私人使用的**輕量、桌上跑團優先 D&D 5e 2014 Web VTT**。真人 DM 主要靠口頭敘事，網站負責共享、同步、計算、保存、權限與外部 AI 接入；不做 CRPG 或包山包海的平台。

- **目前 code 可用**：Character Workshop、Lv1／高等創角、Multiclass／Subclass／ASI／Feat／Spellcasting／Starting Equipment、Character Sheet、Current State 編輯、Level Up、Build Edit、Version History、Archive／永久刪除、角色卡 HTML 輸出。Web 已是 Room-first：首頁只有 Create / Enter Room + Recent Rooms，Room access／heartbeat 已交付，**Character／Draft／Import／Export 全部收進 Room Character Workspace**（`/rooms/{roomId}/characters`），舊的 global `/characters`／`/api/characters` 已於 P2-B 收口。Room 另可建立 Campaign 與 Party Roster（`/rooms/{roomId}/campaigns`）：Campaign lifecycle 為 Owner-only，Roster 由 Owner／DM 管理，且只 reference 同 Room Character、不複製 Current State。Room 目前選中的 active Campaign 可再進 Lobby（`/rooms/{roomId}/campaigns/{campaignId}/lobby`）：建立 DM／Player／Spectator Seat、指派 Human controller、為 Player Seat 選本場角色，presence 沿用 P2-A heartbeat 顯示 Connected／Offline。DM Seat 的 controller 指派為 Owner-only。Lobby 之後可由 Owner 事前 assign 的 DM Seat controller Start Session（`/rooms/{roomId}/campaigns/{campaignId}/sessions/{sessionId}`）：本場 DM Controller 與每個 Player Seat 的 Active Character 在 Start 當下固定，支援 Late Join、End、Abandon 與 Resume；同一 Character 不得同時在兩場 active Session，由 DB lease 保證。
- **內容與語言**：以 SRD 5.1 為基礎，已擴充多來源角色內容；介面與目前正式呈現的規則內容支援 `zh-TW`／`en`。Enabled pack 清單以程式中的 `Settings.enabled_content_packs` 為準。
- **已交付單機版**：同一份角色核心與前端可打包成 Windows 離線 portable zip，使用 SQLite 保存；提供 Character JSON 匯入／匯出。**測試指南 E.9 的乾淨 Windows 11 冷啟動已於 2026-09-06 由使用者人工補驗完成。** Standalone 永久保持 Character-first，不導入 Room／Campaign／Session／Seat。
- **Session table runtime（P3-A）**：每場 Session 有自己的 durable ordered event stream 與 runtime revision。event 可標示 public／DM-only／actor+DM／指定 Seat private 四種 audience，一律由 Server 在 projection 階段過濾；browser 初次進場拿完整 Resume，之後只用 `after_seq` cursor 增量補齊，long-poll 等待期間不佔 DB connection，斷線自動重連並沿用同一 cursor，server restart 後順序與 revision 不倒退。**這層目前只是 substrate**，還沒有任何玩家可直接操作的內容寫進去。
- **尚未實作**：正式 AI 桌內接入、Exploration／Roll／Combat／Adventure Runtime。Room 目前有 access、Character workspace、Campaign／Party Roster、Lobby／Seat 配置、Session lifecycle 與 P3-A 的 event substrate；但桌上開場後仍沒有任何 in-session 玩法面（沒有 Chat／Action／Check／骰子／Combat），Session 目前只是「誰在這一場、用哪隻角色」加上一條還沒有人往裡面寫東西的 event stream，離可跑團還很遠。
- **技術基礎**：React + TypeScript + Vite；Python + FastAPI + Pydantic；SQLAlchemy + Alembic；網頁版 PostgreSQL、單機版 SQLite。啟動與開發指令見 [README.md](README.md)。

產品硬原則包含 Server authoritative、Human／AI 共用 backend logic、秘密由 Server 過濾、敘事輔助資料 optional 不變 mandatory。**網站本身不接 LLM API**；未來 AI 能力來自使用者外部 AI Session。完整行為與明確不做項目見產品規格，不以本段取代。

## 當前狀態與下一步

**P0、P1、P2、M02、M03 已完成並關門；M01-A～M01-N 已逐項關門，M01 是長期保持 open 的 Character Content Expansion / Maintenance track。P3 已完成 Subphase A～F 拆分與三份正式文件，並於 2026-09-08 完成 P3 開工前 preflight blocker 文件修正。P3-A 已於 2026-09-09 關門；下一步是 P3-B。**

P2 已交付並必須繼續維持的核心方向：

- **Web Room-first**：首頁先 Create / Enter Room；Character / Builder Draft 在 P2-B 後全部由 Room workspace 管理，不再有跨 Room global Character Workshop。
- **Standalone Character-first**：Character Core / Builder / JSON exchange 不依賴多人 domain，單機版不建立假 Room。
- **同一 Character 不跨 Room共享 identity**；跨 Room用 Export / Import / Copy-as-new。
- **同 Room多 Campaign可 reference同一 Character，Current State共用同一份。**
- **同一 Character不可同時成為兩個 active Session 的 Active Character。**
- **Character JSON 在 P2-A 鎖定 v1**，但仍接受 M03 最後 `unstable`格式並 normalize。
- **P2-A 先拆 Alembic shared-character / web-multiplayer migration tracks**，避免 standalone SQLite長出 Room / Campaign / Session schema。

P3 已拍板並寫入正式文件的核心方向：

- **P3 只做 Exploration + Roll + AI**：Quick Combat留P4、Adventure Runtime留P6、完整Timeline / Snapshot留P7。
- **P3 session runtime / event 必須 durable**：reload、Human / AI reconnect、server restart後可由canonical state + cursor恢復；不依賴舊browser或AI conversation memory。
- **Event wait必須是非阻塞 async path**：等待期間不持有SQLAlchemy connection / transaction，不把整段30–60秒timeout佔在sync worker；process-local notifier只負責wake，DB cursor仍是canonical truth，並要有並發waiter不餓死一般DB request的測試。
- **Main Stage只做最小Room-scoped image + text**：不提前建立Asset Library / Scene / Adventure entity。
- **AI至少交付一條真實可用MCP入口**：底層application service保持transport-neutral；Human UI與AI Tool共用permission / roll / state logic。
- **P3 gameplay caller統一成typed `TableActorContext`／等價 actor abstraction**：Human以`access_session_id`識別，AI以`grant_id + generation`識別；AI不偽造`RoomAccessAuthority`。P3-C新service先保持actor-neutral，P3-D正式把P2 Human-only Session / live Character authorization入口演進成Human/AI共用。
- **Player支援Human ↔ AI控制權交接；DM整場固定controller**。P3新增AI DM作為一場新Session的起始DM Controller，但不支援Session中途Human ↔ AI DM handoff。
- **P3-D controller authority以Seat `controller_epoch`為current SSOT**：Seat current AI binding保存grant id + 單調epoch；`ai_controller_grants.generation`只保存mint時的immutable epoch snapshot，Session fixed DM / Participant join generation也只是歷史snapshot。每次AI授權必須同時驗current grant id與`seat.controller_epoch == grant.generation`，不能只看grant status。
- **P3-D pre-session AI DM grant不是永久 bearer**：`session_id=NULL` 時必須有有限TTL，只能讀自己DM Seat/Campaign的最小Start context與呼Start；Seat controller變更/rotate/archive/delete、Campaign離開Start-eligible active、Room active Campaign切離、Owner revoke或TTL到期都使未綁grant失效。Start成功後才轉為該Session固定DM credential。
- **Player `Take Back Control`只認原handoff Human access session**：`Let AI Control`會保存`handoff_return_access_session_id`；其他Room member、相同display name或重新進Room得到的新access session都不能self-service Take Back。P2目前沒有跨裝置持久Human identity；原access session遺失/revoked時，改走Owner/DM既有Player Seat administrative reassignment，並原子revoke AI grant + 前進Seat epoch + audit。
- **P3-D必須演進P2 controller binding schema**：新的web migration為Seat加入current AI grant + `controller_epoch`，Session fixed DM snapshot、Participant join snapshot加入AI grant + generation，並drop/re-add `ck_campaign_seats_controller_binding`、`ck_sessions_dm_controller_binding`、`ck_session_participants_controller_binding`；不得回頭改歷史`0013` / `0014`。
- **P3 event不是P7完整Timeline**：P3只保存當場玩法、pending與reconnect需要的durable truth；跨Session history browser / search / Snapshot / Restore仍留P7。

下一步依序為：

1. **實作 P3-B — Exploration, Chat & Actions**；在 P3-A 的 event substrate 上做 Main Stage text/image、Dialogue / Action / OOC / Whisper DM / Narration 與 DM proxy，不建立 Scene / Asset Library。開工前先讀 [P3-A closeout](docs/P3/P3-A_CLOSEOUT.md) 的 Handoff 段，該段列出必須沿用而不得另造第二套的 substrate。
2. 之後依固定順序完成 P3-C → P3-D → P3-E → P3-F；每個Subphase都依三份P3正式文件獨立實作、驗證與closeout。
3. P4～P8 仍維持大 Phase，不提前拆分或設計 schema / API / module。

P2 的正式契約：

- [P2 實作規格](docs/P2/實作規格.md)
- [P2 開發設計方針](docs/P2/開發設計方針.md)
- [P2 測試指南](docs/P2/測試指南.md)

P3 的正式契約：

- [P3 實作規格](docs/P3/實作規格.md)
- [P3 開發設計方針](docs/P3/開發設計方針.md)
- [P3 測試指南](docs/P3/測試指南.md)
- [P3-A closeout](docs/P3/P3-A_CLOSEOUT.md)

**M01 不再有「必須 final closeout 後才能開始 P2」的 gate。** A～N 是目前已完成的角色內容 baseline；之後若再拍板新的角色內容或既有角色系統強化，從 **M01-O** 起繼續新增 Subphase。M01 可以在 P2／P3 等正常產品 Roadmap 繼續前進時保持 open，不要求先建立一個假的「全部 D&D 內容已完成」里程碑。

新的 M01 Subphase若只補 content / presentation，依當時既有 regression contract驗證；若碰到 Character Build／State／Version／StableKey／Builder provenance／Character JSON schema 或其他共享角色核心，除了 M01 自身驗證外，還必須同步做**當時已存在的後續 P Phase compatibility review**與 **M03 standalone compatibility review**。P2-A 起 shared Character migration 必須落在 `character` Alembic track，不得讓 maintenance 工作反向依賴多人層。

## 未結清事項與驗收限制

| 項目 | 當前狀態與影響 | 證據／後續入口 |
|---|---|---|
| Builder Draft 存檔／重取競態 | **P2-D 解掉一半。** `character-builder` 那一支是測試缺陷：它是唯一還只以「Saved on server」當存檔完成條件的 Builder spec，該文字分不出這次與上一次存檔，已改用其餘十二支早就在用的 draft revision 等待（3 跑 3 敗 → 5 跑 5 過）。**`m01e`／`m01m` 未解**：那兩支本來就用 revision 等待，失敗是真的等滿 5 秒逾時，是延遲而非假通過，根因仍未確認。建議把 KI-P1D-001 拆成兩條 | [P2-D closeout](docs/P2/P2-D_CLOSEOUT.md)「順帶修掉的既有問題」；[已知問題.md](已知問題.md) KI-P1D-001 |
| P2-A Room 層取捨 | Throttle 為 process-local（多 worker 會稀釋）；`POST /api/rooms` 無 throttle 無授權；Room access token 以明文存 `localStorage` 且無到期機制 | [P2-A closeout](docs/P2/P2-A_CLOSEOUT.md)「已知限制」；P3-D因此明確不把新access session / display name視為原handoff Human |
| Journey 2（多 Room 隔離）只有後端證據 | HTTP 層由 `test_p2b_room_character_api.py::test_room_a_cannot_use_room_b_character_or_draft_ids` 完整覆蓋，但測試指南 §13 描述的「把 Room B 的 UUID 貼進 Room A route 會看到什麼」沒有 browser 斷言。隔離本身有保證，缺的是使用者視角證據 | [P2-F closeout](docs/P2/P2-F_CLOSEOUT.md)「已知限制」 |
| 雙語 browser crawl 未涵蓋 P2 新畫面 | `m02h-bilingual-site-smoke.spec.ts` 只跑三條 character 路由，沒有 `/campaigns`、`/lobby`、`/sessions/{id}`。目前靠 `hardcodedUiCopy.test.ts` 掃描與各 `*Copy.ts` locale parity 單元測試把關，缺整頁 overflow / raw key 的視覺層 crawl | [P2-F closeout](docs/P2/P2-F_CLOSEOUT.md)「已知限制」；P3-F要求把Session桌面納入完整crawl |
| Restart 整合測試跑在 SQLite | `test_p2f_restart_integration.py` 用 `metadata.create_all` 建 SQLite，dataset 完整但不是 Alembic 遷移後的 PostgreSQL。migration 面另有真 PostgreSQL 覆蓋，兩者合起來無未驗組合 | [P2-F closeout](docs/P2/P2-F_CLOSEOUT.md)「已知限制」；P3-F要求至少一條真PostgreSQL restart整合證據 |
| `test:e2e:docker` 只 rebuild `web` | 後端改動若不先 `docker compose up -d --build server`，整套 E2E 會靜默測到舊 backend。目前仍是操作者責任。P3-A 的 E2E 走一次性 workflow 從 clean checkout 執行，未觸發此 trap，也未收斂它 | [P2-F closeout](docs/P2/P2-F_CLOSEOUT.md)「已知限制」；**P3-B 是 P3 第一個有 backend-dependent E2E 的 Subphase，必須在該 Subphase 收斂**，見 [P3-A closeout](docs/P3/P3-A_CLOSEOUT.md) Handoff |
| Lobby 的 per-Seat N+1 查詢 | **P3-A 解掉 Resume 那一半。** `SessionResumeRepository.load_character_summaries()` 把 Active Character summary 改成單次批次查詢，且整份 Resume 已從 Session 頁的 heartbeat 移除。**Lobby 側未動**：`SeatService.lobby()` 仍對每個 Human-controlled Seat 各查一次 access session，而 Session 頁仍以 heartbeat 週期輪詢 Lobby。P3-A 沒有放大它（輪詢頻率不變、淨查詢量下降），但 P3-B 若讓 Session 頁更依賴 Lobby 衍生資料或提高頻率，必須先批次化 | [P3-A closeout](docs/P3/P3-A_CLOSEOUT.md)「已知限制」；[P2-E closeout](docs/P2/P2-E_CLOSEOUT.md)「已知限制」 |
| P3-A 的呈現層與測試替身取捨 | 三項：致命錯誤時 `error` banner 與 disconnected banner 會同時出現；重連中的狀態沿用 `error-banner` 告警樣式；waiter starvation 測試借用真實 `wait_after` 但 stub 掉 `list_after`，真實 endpoint 路徑未合成單一端到端資源斷言。都不影響 P3-A 契約，留待 P3-B 一併處理 | [P3-A closeout](docs/P3/P3-A_CLOSEOUT.md)「已知限制」 |
| 座位變動的即時同步仍是顯示層權宜 | P3-A 修正後，看得到 Lobby 的 caller 已恢復隨心跳更新座位標籤；無 Lobby 讀取權的 caller 其座位資訊仍凍結在進入 Session 頁當下。座位變動要成為桌上的一等事件屬 P3-B 範圍 | [P3-A closeout](docs/P3/P3-A_CLOSEOUT.md)「關門過程中修正的問題」第 1 項與「已知限制」 |
| Campaign status 仍無 transition 規則 | `active` 已累積「可開 Lobby」與「可開 Session」兩層語意，但 Campaign 仍可從 `completed` 退回 `draft`；`delete_draft_without_session_history()` 因此得同時檢查 status 與 Session history 才安全 | [P2-E closeout](docs/P2/P2-E_CLOSEOUT.md)「已知限制」；P3-D pre-session AI DM grant只要Campaign離開Start-eligible active就revoke，不依賴status transition單向性 |
| draft Campaign hard delete 會 cascade 掉整份 Roster | 符合契約，且 **P2-E 已把「無 Session history」從恆真變成真的檢查**（`delete_draft_without_session_history()`）。剩下的問題只在 UI：確認流程未顯示會連帶移除幾筆 roster。P2 未處理 | [P2-C closeout](docs/P2/P2-C_CLOSEOUT.md)「已知限制」；[P2-F closeout](docs/P2/P2-F_CLOSEOUT.md)「已知限制」 |
| Room Hard Delete 是目前最容易造成不可逆資料遺失的入口 | 確認 modal 只要求輸入 Room 名稱，未顯示會連帶刪除幾個 Character／Draft／Campaign／Session，也未提示先匯出。行為符合契約，human smoke 期間實際造成兩隻角色永久遺失。P2 未處理 | [P2-B closeout](docs/P2/P2-B_CLOSEOUT.md)「已知限制」；[P2-F closeout](docs/P2/P2-F_CLOSEOUT.md)「已知限制」 |
| `display_name` 只在 Lobby 有去處 | **P2-D 起 Lobby 的 controller 下拉與 Seat 卡片會顯示它**，P2-B 記錄的「填了零反饋」部分解除；Room landing 與 Character workspace 仍不呈現 | [P2-D closeout](docs/P2/P2-D_CLOSEOUT.md)「已知限制」 |
| E2E global setup 無條件清空 Character | 已改為 `DELETE FROM characters` 並以 `ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1` 當閘門（CI 自動放行）。本機在有真實資料的 DB 上設此變數會直接刪光，跑之前必須自行備份 | [P2-B closeout](docs/P2/P2-B_CLOSEOUT.md)「已知限制」 |
| M01-J 直創／逐級升等等價 E2E | 測試目前 `fixme`，瀏覽器層證據仍有缺口；後端已有相關整合覆蓋 | [已知問題.md](已知問題.md) KI-M01J-001 |
| Windows Vite E2E 環境 | 使用既有 Docker Linux dev server 路徑驗證；不要走 Windows Playwright 託管 Vite 的整套路徑 | [已知問題.md](已知問題.md) KI-ENV-001；[README.md](README.md) |
| M01-N 匯出 HTML 缺行為測試 | `createCharacterSheetHtmlExport()` 對真實產出的 HTML 沒有斷言，目前由投影單元測試、原始碼字串斷言與 E2E 下載斷言間接把關；`prepared_limit` 改寫路徑因 fixture 為 `null` 而不在 CI 覆蓋內（已人工驗證） | [M01-N closeout](docs/M01/M01-N_CLOSEOUT.md)「已知限制」 |
| M03 測試／開發工具遺留 | `Settings()` import-time 快照的測試污染與 dev seed engine 入口未收斂，詳細限制及建議留在 closeout | [M03-G closeout](docs/M03/M03-G_CLOSEOUT.md)「M03 已知限制」與「留給後續 Phase 的建議」 |

以上為接手時須注意的現況索引；問題詳情與歷史測試數字以連結文件為準，不代表本檔每次更新都重跑驗收。

## Phase Roadmap

先建立角色與規則基礎，再把角色帶進桌內。M Phase 為插入式維護／擴充，不改寫 P0 → P8 的產品 Roadmap；**M Phase 可以長期保持 open，而正常 P Roadmap 繼續前進。**

| Phase | 主題 | 交付範圍／狀態 |
|---|---|---|
| P0 | Character Core + SRD / Rules Foundation | 角色資料、角色卡、角色相關規則基礎；已關門 |
| P1 | Character Builder Complete | 完整創角、Progression、Level Up、Character Version；已關門 |
| M01 | Multi-Source Character Content Expansion | 長期角色內容／角色系統維護 track；A～N 已關門，整體保持 open，未來從 O 繼續，不阻塞 P2+ |
| M02 | Traditional Chinese / English Localization | 插於 M01-C 與 M01-D 間；雙語呈現、翻譯流程與完整性 gate；已關門 |
| M03 | Standalone Character Builder Distribution | P2 前插入；Windows 單機版、Character JSON exchange、standalone boundary；已關門，E.9 乾淨 Windows 11 冷啟動已於 2026-09-06 補驗完成 |
| P2 | Room / Campaign / Session / Seat | Room-first Web、Room Character Workspace、Campaign / Roster、Seat / Controller / Lobby、Session lifecycle；**A～F 全數關門，Phase 已關門** |
| P3 | Exploration + Roll + AI | Exploration、Chat／Action／Check、正式骰子、PendingAction、Human／AI 共桌；**A～F正式文件與preflight blocker修正已完成，P3-A已關門，下一步P3-B** |
| P4 | Quick Combat | 第一個完整可玩的 Combat MVP；首個 Subphase P4-A 承接 SRD Monster／Beast stat blocks |
| P5 | Tactical Combat | 同一 Combat Engine 上增加 Grid、Battle Map、Movement、Range、AoE 與空間系統 |
| P6 | Adventure + AI DM Runtime | Adventure Definition／Importer、Campaign Runtime、世界資料、AI DM context／write-back |
| P7 | Snapshot / Export | Timeline、Snapshot／Restore、broader Archive／Import／Export；角色 JSON exchange 已由 M03 先行，不做 Undo |
| P8 | QA / Polish | 全流程整合、權限、AI reconnect、效能、Responsive UI 與第一版收尾 |

## Subphase 進度

以下每個 Subphase 各列一項；✅ 代表該項已關門，⬜ 代表正式規格已存在但尚未實作。未結清的驗收限制仍以上方索引為準。詳細規格、設計與證據由各 Phase 文件承擔。

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

> **M01 保持 open。** A～N 是目前已交付的 baseline。再下一個已拍板的 M01 工作從 **M01-O** 起編號。沒有預留給「Full M01 Closeout」的字母。

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
| **M02-H — Full M02 Integration & Closeout** | ✅ | structured disabled-reason / issue params、全站雙語 crawl + overflow gate、Draft / Character state integrity、translation evidence 彙整、doc-sync / CC BY NOTICE |

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
| **P3-B — Exploration, Chat & Actions** | ⬜ | Main Stage text/image、最小Room-scoped Stage upload、Dialogue / Action / OOC / Whisper DM / Narration、Stage與Chat分離、不建立Scene/Asset Library |
| **P3-C — Roll, Check & PendingAction** | ⬜ | RollGroup / RollRequest / Result、Server RNG、Group / Secret / physical / quick roll、PendingAction、formal roll idempotency、actor-neutral Character State + event atomic boundary；AI resolver留P3-D接線 |
| **P3-D — AI Controller, Scoped Token & Handoff** | ⬜ | typed TableActorContext、P2 Human-only Session/live-write授權入口migration、hashed scoped AI Join Token、Seat current grant + controller_epoch SSOT、Session/Participant grant-generation snapshots與三條CHECK migration、finite-TTL pre-session AI DM grant、origin-only Take Back + Owner/DM admin recovery、Player Human ↔ AI handoff、AI DM可作新Session固定DM Controller |
| **P3-E — AI Tool Surface & Event Delivery** | ⬜ | MCP `2026-07-28` stateless Streamable HTTP入口、shared application services、structured tools/errors、`get_pending_events` / `wait_for_event`沿用P3-A async wait、真external MCP client gate |
| **P3-F — Full P3 Integration & Closeout** | ⬜ | Human/AI Exploration journeys、secret/group roll、Late Join、AI handoff、AI DM、grant TTL/epoch/Take Back authorization、restart、cross-scope matrix、PostgreSQL concurrency、waiter resource safety、P2 caller regression、standalone / bilingual / full regression closeout |

## 接手時必須保留的跨 Phase 約束

- **M01 是 long-running maintenance/content track**：A～N 是目前 baseline，未來從 O 繼續；M01 open 不阻塞 P2+。任何後續 M01 若修改共享 Character contract，必須 regression 當時已存在的後續 P Phase，並同步做 M03 standalone compatibility review。
- **Web Room-first / Standalone Character-first 是永久產品邊界**：Web Character / Draft在 P2-B 後一定由 Room workspace管理；Standalone不建立 Room。多人層只可依賴 Character Core，Character / Builder / Interop與 `app.standalone`不得反向 import多人層。契約見 [規格企劃.md](規格企劃.md) 第三、四、五章與 [P2 開發設計方針](docs/P2/開發設計方針.md)。
- **Standalone boundary 是常駐約束**：`app.standalone` 不得 import `app.main` 或 P2+ multiplayer modules。P3每新增 multiplayer module / table / MCP route時都必須同步確認 `test_m03_import_boundary.py` 與 `test_m03d_schema_parity.py` 的 forbidden coverage；standalone migration只升 `character@head`，不能把Web multiplayer schema灌進SQLite。
- **Character JSON v1 是 P2-A 起的相容基線**：新 export 已鎖 v1（`schema_version="1"` / `schema_status="locked"` / `export_type="character"`）；legacy M03 `unstable` 仍可由新版本 import並normalize。Room / Campaign / Seat / Session / P3 runtime identity不得塞進Character JSON。
- **P2 active Session write scope是P3唯一Character寫入授權地基，但caller abstraction必須演進**：P3 GameAction / MCP action要擴充 `live_character_write_scope()` 系列，不能另建AI-specific或table-specific bypass；P3-D把現有Human-only `RoomAccessContext`入口收斂成Human/AI都能resolve的typed `TableActorContext`，Human Room authority與AI gameplay scope保持分離。
- **P3 controller persistence的current authority在Seat，不在grant row**：新的web migration讓Seat保存current AI grant id + non-null monotonic `controller_epoch`；grant `generation`、Session fixed DM generation、Participant join generation只做snapshot。每個AI request都必須重驗Seat current grant binding + epoch/generation，歷史`0013` / `0014`不可改寫。
- **P3 pre-session AI DM grant必須有限期且受Seat/Campaign lifecycle約束**：未綁Session時只可minimal pre-session context + Start；TTL、Seat controller變更/rotate/archive/delete、Campaign離開Start-eligible active、Room active Campaign切離或Owner revoke都會使其失效。成功Start後才進Session lifecycle，End/Abandon再原子revoke。
- **P3 Take Back不假裝有跨裝置Human account identity**：self-service只接受原`Let AI Control`保存的exact `handoff_return_access_session_id`。同Room member、相同display name、新access session都不是可信同一人；原session遺失時由Owner/DM administrative reassignment恢復Player Seat並原子revoke AI + 前進epoch + audit。
- **P3 event wait是資源correctness contract**：HTTP wait為async；await期間不持有DB connection / transaction、不長期占sync worker；wake / timeout後以DB cursor recheck，並以受限pool下多waiter不starve一般DB request作自動證據。
- **P3 durable event不等於P7完整Timeline**：P3只為當場play/reconnect保留canonical event/message/roll/action；cross-Session timeline browser、history search、Snapshot / Restore與broader export仍由P7設計。
- **AI transport與game logic分離**：P3至少正式交付一條MCP入口，但Human UI / MCP / future Site Tools共用同一application/domain service；網站本身不接LLM API，不保存外部模型API key。
- **雙語是持續交付要求**：新增、修改或首次呈現給使用者的 system／rules content，必須同一 Subphase 同步交付 `zh-TW`／`en`；locale 只影響呈現，不改角色／草稿／P3 canonical gameplay data。細則見 [AGENTS.md](AGENTS.md) 與 [M02 實作規格](docs/M02/實作規格.md)。
- **P4 承接內容範圍**：P4 的第一個 Subphase 為 P4-A，須承接 P0 延後的 SRD Monster／Beast stat blocks；schema、API 與 combat representation 到 P4 開工才設計。
- **M Phase 插入不重編既有順序**：可插在另一 M Phase 的 Subphases 之間，也可長期保持 open 與 P Roadmap 並行；只拆當前要做的工作，例外僅為使用者已拍板且插入點確定的 M Phase。完整規則見 [AGENTS.md](AGENTS.md)。

## 文件索引與閱讀方式

| 要找的資訊 | 正式入口 |
|---|---|
| Agent 開工、修改授權、測試 gate、commit／push 與本機工具規則 | [AGENTS.md](AGENTS.md) |
| 當前進度、下一步、Roadmap | 本檔 |
| 產品定位、玩法、權限、UI 行為、第一版明確不做 | [規格企劃.md](規格企劃.md)：先搜尋標題，只讀任務相關章節；不要整份讀 |
| 啟動、開發與測試指令 | [README.md](README.md) |
| 基礎技術選型的討論背景 | [技術棧討論.md](技術棧討論.md)：不是現行全專案 architecture spec |
| 已確認但尚未修復的問題 | [已知問題.md](已知問題.md) |
| 單機版使用說明 | [繁中](README-standalone.zh-TW.txt)／[English](README-standalone.en.txt) |

各 Phase 的三份正式文件分工：**實作規格＝完成後必須為真；開發設計方針＝具體實作契約；測試指南＝驗收方式。** 實作／驗證某 Subphase 時，讀該段與必要的共用前言，不整批重讀所有 Phase。

| Phase | 實作規格 | 開發設計方針 | 測試指南 |
|---|---|---|---|
| P0 | [規格](docs/P0/實作規格.md) | [設計](docs/P0/開發設計方針.md) | [測試](docs/P0/測試指南.md) |
| P1 | [規格](docs/P1/實作規格.md) | [設計](docs/P1/開發設計方針.md) | [測試](docs/P1/測試指南.md) |
| M01 | [規格](docs/M01/實作規格.md) | [設計](docs/M01/開發設計方針.md) | [測試](docs/M01/測試指南.md) |
| M02 | [規格](docs/M02/實作規格.md) | [設計](docs/M02/開發設計方針.md) | [測試](docs/M02/測試指南.md) |
| M03 | [規格](docs/M03/實作規格.md) | [設計](docs/M03/開發設計方針.md) | [測試](docs/M03/測試指南.md) |
| P2 | [規格](docs/P2/實作規格.md) | [設計](docs/P2/開發設計方針.md) | [測試](docs/P2/測試指南.md) |
| P3 | [規格](docs/P3/實作規格.md) | [設計](docs/P3/開發設計方針.md) | [測試](docs/P3/測試指南.md) |

歷史完成過程與驗收證據查各 Phase 目錄的 `*_CLOSEOUT.md`；M01-B 真人創角 Gate 另見 [M01-B_HUMAN_GATE.md](docs/M01/M01-B_HUMAN_GATE.md)。最近**已完成產品Phase**的整合交付見 [P2-F_CLOSEOUT.md](docs/P2/P2-F_CLOSEOUT.md)；P3目前只有正式設計文件，尚無code closeout。

`docs/暫用規則資訊/` 是內容 authoring／review input，**不是 runtime 資料來源**。正式規則與可調數值住 `data/`，runtime 不解析 `docs/`；`舊文件/` 為歷史封存，接手時忽略。

開場先完整讀 [AGENTS.md](AGENTS.md)、本檔與 `git log --oneline -10`，再依任務定位正式契約。不要把歷史 closeout 的「當時待辦」當成目前未完成事項，也不要因本檔列出下一步就自行開始 coding。
