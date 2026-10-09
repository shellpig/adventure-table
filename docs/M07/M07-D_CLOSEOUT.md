# M07-D — Full M07 Integration & Closeout · Closeout

日期：2026-10-09　Branch：`feat/m07d-integration-closeout`（自 `main@80f08e76`）　Worker：Muse Spark 1.3 經 OpenCode CLI（D1、D2、D6 多數項目）、Codex（D2 指揮、D3、D4）、Muse 網頁版（D3 部分）、指揮者 Claude（審核修正、D5 真人驗收紀錄、D6 部分項目、本關門）

Commit：D1 `7d8bf52b`；D2 `5b519f00`＋`f024600c`；D3 `a15d5909`、`452d5daf`、`f79d3d10`、`e7b24c5f`；D4 文件；D6 `1175d92a`～`a080e920`（逐項見 [D6](M07-D_steps/D6.md)）；關門 gate 期間的 E2E 測試修正 `e17c2774`、`4c0816cf`、`098937ef`；本檔。

## 驗收對應

逐項 test node 與 browser flow 住各 step 紀錄，本檔只列入口，不重抄。

| 契約 | 證據 |
|---|---|
| M07-A～C 外部審查修補（F01～F19） | [D1](M07-D_steps/D1.md)「紀錄」：`test_m07d_secrecy.py`、`test_m07d_intent_retry.py`、`test_m07d_refs.py`、`test_m07d_resources_search.py`、`test_m07d_session_libraries.py`、`test_m07d_atomicity.py`、`test_m07d_postgres_race.py`；[D2](M07-D_steps/D2.md) 表格：F12～F19 對應 unit 與 `m07a`／`m07b`／`m07c`／`m07d-f13-f19-regression`／`m07d-session-libraries` E2E；Member DM 可達性 `test_m07d_member_dm_assignment.py` |
| D.1 整合旅程與真 PG migration | [D3](M07-D_steps/D3.md)「D.1 證據對照」：`test_m07d_migration_integration.py`（pre-M07 heads→current heads 空資料與 seeded、兩 Room／兩 Campaign、Session End 接續與 restart、Quick／空庫／零 Adventure、拒絕零副作用、Room hard delete）；browser `m07d-library-journey`（真 server-e2e restart、未決 OA 跨 Session） |
| D.2 P7 交接與 Member DM 文件對齊 | [D4](M07-D_steps/D4.md)：P7 三份契約、產品規格權限小節、P2／M07 契約對齊；focused 權限回歸 26 passed |
| D.2 真人使用驗收 | [D5](M07-D_steps/D5.md)「驗收結果」：H01、H02、H04、H14 PASS；H03、H05～H13 依使用者 2026-10-09 決定延後（見下方「延後與限制」） |
| D.4 怪物庫排序與篩選 | [D6](M07-D_steps/D6.md) 排序篩選列：`test_m07d_library_sort_filter.py`、frontend unit、E2E `m07d-library-sort-filter`；真人 H14 PASS |
| D5 期間追加 UI 修補 | [D6](M07-D_steps/D6.md) 交付紀錄逐項 commit 與驗證；剛開啟編輯器時配置名稱／footprint 由 E2E `M07-D D6g saved placements show names and footprints before monster mode is opened` 鎖定（修正前已重現失敗） |
| Standalone boundary／schema parity／Web↔Standalone exchange | 全套 backend 內的 `test_m03_import_boundary.py`、`test_m03d_schema_parity.py` 等；M07-D 未新增多人 module 命名，未改 Python 相依或打包 |

## 關門 gate

- **全套 backend pytest**（`e17c2774`，cwd `apps/server`，repo venv，`P4_POSTGRES_URL=…/adventure_table_p4`）：exit 0，3,306 passed、39 skipped、0 failed。39 個 skip 與 M07-A～C、D1～D3 相同，是 P0／P2／P3 專屬 PG URL 的環境條件；M07 與 P4／P5 的 PG 測試全部實跑。
- **Frontend**（`a080e920`；之後只改 E2E spec 與文件）：`npm test -- --run` 1,064 passed；`npm run build` 通過（只有既有 chunk-size 警告）。
- **`docker compose config`**：通過。
- **Frontend build 複驗**：關門期間修改 E2E spec 後 `npm run build`（含 E2E TypeScript）通過。
- **全套 E2E**（`npm run test:e2e:docker` 無參數，隔離的 `adventure_table_e2e`）：
  - 第一輪（`e17c2774`）暴露四個測試缺陷，皆非產品問題，逐一修正並先以強制條件重現：`p6g-empty-campaign` 與 `p6g-adventure-journey` 的 seat card 定位（D2 起 DM Seat 的 Controller 選單列出 Player member，`hasText` 命中兩張卡，`e17c2774`／`4c0816cf`）；p6g 兩支與 `p4e-quick-combat` 的攻擊迴圈在第一擊落空後未推回合，選 `attack` 卡到單測逾時（`4c0816cf`／`098937ef`，以 AC 30 強制落空驗證會跑滿 6 輪停在預期斷言）；`pickSrdMonster` 在 serial-restart 共用 worker Room 內遇到 `m07d-library-journey` 複製出的同名自訂 Goblin（`098937ef`）；p6g 落空後重試成功時，事件斷言誤取第一筆（落空）攻擊結果（`435a1577`，以 AC 15 `--repeat-each=5` 驗證落空後命中的跑次通過）。
  - 最終一輪（`435a1577`）`parallel`：134 passed、2 failed、3 skipped，script 隨即中止。失敗 `m01k-phb-feats-and-spells`「Martial Adept」為 `waitForDraftRevision` 單次 poll 等滿 5 秒（KI-P1D-001 簽章）；`p5f-tactical-combat` 0ms 以 `3221226505` 結束（KI-ENV-002）。兩支單獨補跑 7 passed。M07-D 未改 Builder 或角色 API。
  - 依 script 相同步驟補跑後續：`baseline-room` 30 passed、1 skipped；`serial-restart` 3 passed（含 `m07d-library-journey`）；以不含 xge 的 pack 清單（`srd5.1,phb2014,scag,gos,vgm,vrgr,tce,mtf`）重啟 E2E 服務後 `m03c-character-import` 7 passed，再還原完整 pack 清單。
  - 先前各輪另見 `m01i-optional-features`（KI-P1D-001 疑似同族、與既有紀錄同簽章，單跑 5 passed）與 `m07d-library-journey` 一次 KI-ENV-002 崩潰（單跑通過）；`p1f-character-creation` 本次各輪皆通過。

## 使用者決定（2026-10-09）

- **真人驗收範圍**：使用者先打磨不含地圖戰鬥的部分，H03 與 H05～H13 延後，M07-D 以 H01、H02、H04、H14 的真人結果加上自動化 gate 關門。延後項目登記於已知問題，地圖戰鬥流程的真人使用證據目前不存在。
- **怪物庫搜尋框**：以名稱為主是預期行為，類型改用 D.4 的類型篩選（雙語）；不補 zh-TW 類型文字搜尋。D1 留下的「繁中 type 搜尋待決」以此結案。後端目前仍比對英文 type／subtype（`test_m07a_library_lifecycle` 斷言 `humanoid` 命中 Goblin），本次不改。

## 延後與限制

- **D5 真人 H03、H05～H13 未做**：底圖格線、兩種載入、最新模板／批次拒絕、兩人同步與保密、真正跑一輪、runtime 保留、第二 Campaign／Room、Member DM 與 Player、封存與引用、Quick／空資料手感。自動化證據見 D3，但不等於真人使用結果。見已知問題索引。
- **真實 AI client 未驗**：沿用 2026-10-05 決定，已列已知問題索引，不記 AI 實測 PASS。
- **地圖編輯器幾何復原在 dev 模式重複推入**：React StrictMode 讓 updater 執行兩次，牆／門／地形／繪製的復原堆疊可能需多按一次 Ctrl+Z；production build 不受影響，配置堆疊已處理。日常站跑 vite dev，會碰到。
- **間歇失敗**：D3 觀察的 `p5g-map-editor-save` reload 後一直 Loading 未再現也未診斷（已開 `trace: 'retain-on-failure'`）；`m07b-map-library` zh-TW 旅程在大批平行時曾一次 `toHaveURL` 逾時，單跑連兩次通過。
- **戰鬥加怪選單同名難辨**：自訂複製未改名時與內建 SRD 同名同 CR，選單看不出來源；登記已知問題，產品未修。
- `KI-P5A-001`（已結束戰鬥 hidden Monster 歷史洩漏）仍由 P7-A 處理，本 Subphase 不涉及。
- 合併 main 後，daily server 啟動時 Alembic head 不變；M07-D 沒有新 migration。
