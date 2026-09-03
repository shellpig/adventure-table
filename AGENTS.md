# Agent Instructions

# Adventure Table

一個**輕量、桌上跑團優先的 D&D 5e 2014 VTT**。真人 DM 像實體跑團一樣主要靠口頭敘事，只在需要時使用網站工具；外部 AI 透過 MCP / Site Tools 正式進桌當 DM 或 Player，與真人共用同一套 Game State、規則與權限。

- **類型**：Web VTT（虛擬桌面），非 CRPG、非 Foundry 式全能平台
- **一句話**：網站只管需要共享、同步、計算、保存、權限與 AI 接入的東西，其餘還給 DM 的嘴巴
- **首發規則集**：D&D 5e 2014；Built-in Content：SRD 5.1（CC BY 4.0），非 SRD 內容依私人專案需求逐步加入
- **專案性質**：朋友間私人使用，非預計商品化平台
- **目前階段**：**P0 與 P1 已完成並關門。M02 — Traditional Chinese / English Localization 已完成 M02-A～M02-H 並關門；網站現在是 `zh-TW` / `en` 兩個純語言模式。M01 已完成 M01-A～M01-K 並關門；M01 尚未 full closeout。K 後是否新增其他 M01 規則 Subphase、以及 Full M01 Integration & Closeout 的 Subphase ID 仍由使用者後續拍板。只有 final M01 closeout 完成後才回到 P2 — Room / Campaign / Session / Seat 的規劃。**
- **目前進度**：以 `PROJECT_BRIEF.md` 為單一事實來源
- **基礎技術棧**：目前方向見 `技術棧討論.md`。該檔只討論語言／Framework／DB 等基礎選型，不承擔各 Phase 的實作設計

## New Conversation Opening Check

**Layer 1 — 必讀：**
1. `AGENTS.md`（本檔）
2. `PROJECT_BRIEF.md`（當前 Phase、Roadmap、文件索引）
3. `git log --oneline -10`

**Layer 2 — 按任務讀對應文件／段落：**
- `規格企劃.md` — **產品與玩法的單一事實來源**。約 70 KB，一律標題定位、只讀該段
- `技術棧討論.md` — 只在基礎技術選型／Framework 討論時讀；不要把它當成全專案 architecture spec
- `docs/Px/` / `docs/Mxx/` — 某個 Phase 開工後，該 Phase 的正式實作規格、開發設計與測試文件

> 不要為了「先想完整」而提前設計後續 Phase。資料模型、API、事件、權限實作、Snapshot、Combat、Tactical 等細節，原則上等對應 Phase 再決定。

Report to user: current progress, and any issues with their scope of impact.

**Layer 0 — 每個任務開工前先過這張表（不是只有開場）：**

| 任務類型 | 先讀 |
|---|---|
| 診斷 bug、分析錯誤、找根因、效能回歸 | `diagnose` |
| 需求不清、規格討論、要問釐清問題 | `grill-me` |
| 前端／本機 web app 驗證、UI 行為除錯、瀏覽器截圖或 console log | `webapp-testing` |

判斷任務類型是開工的第一步，不是可選項。

## 文件查閱規則

`AGENTS.md` 與 `PROJECT_BRIEF.md` 開場整份讀。**`規格企劃.md` 一律標題 grep 定位、只讀該段**（讀到下一個同級標題為止），整份讀會被工具截斷。

**不要依賴行號**——行號隨編輯漂移，一律以標題或關鍵字定位。

`規格企劃.md` 的定位鍵是章節中文數字與 `###` 小節：

```bash
grep -n "^## \\|^### " 規格企劃.md
```

十四個章節的對照：

| 找什麼 | 去哪章 |
|---|---|
| 硬原則、一句話摘要 | 〇 產品基線 |
| 定位、SRD / 非 SRD 內容策略 | 一 |
| Seat / Role / Controller / 權限 / AI 接手 / DM 修改權 | 二 |
| Room / Campaign / Session / Party Roster / Resume | 三 |
| Homepage / Main UI / Character Sheet / Exploration / DM Toolbar | 四 |
| Character Workshop / Builder / 版本 / 法術 / Temp HP / Hit Dice | 五 |
| Combat Engine / Quick / Tactical / Conditions / Death Save | 六 |
| Adventure / Campaign Runtime / AI DM write-back / Importer | 七 |
| NPC / Monster / Scene / Knowledge / Roll System | 八 |
| Timeline / GameTransaction / Snapshot | 九 |
| Inventory / Loot / Shop / Quest / Rest | 十 |
| 資料生命週期 / Export / Import | 十一 |
| **第一版明確不做** | 十二 |
| 文件維護與討論規則 | 十三 |
| 開發接手原則 | 十四 |

**提新功能前先看第十二章。** 那份清單是刻意砍掉的東西，不是還沒做的待辦。

同一 Phase 已拆出 Subphase 後，三份 Phase 文件的 Subphase 標題必須一字不差。實作或驗收某個 Subphase 時，只讀該段及必要的共用前言，例如：

```bash
grep -n "P0-C" docs/P0/實作規格.md docs/P0/開發設計方針.md docs/P0/測試指南.md
grep -n "M01-B" docs/M01/實作規格.md docs/M01/開發設計方針.md docs/M01/測試指南.md
grep -n "M01-D" docs/M01/實作規格.md docs/M01/開發設計方針.md docs/M01/測試指南.md
```

## 文件分工與單一事實來源

**同一件事只住一個地方。**

| 住哪 | 放什麼 |
|---|---|
| **`規格企劃.md`** | 產品行為與為什麼：跑團方式、權限、規則選擇、UI 行為、明確不做 |
| **`PROJECT_BRIEF.md`** | 當前 Phase、Roadmap、Subphase 進度、下一步、文件索引 |
| **`技術棧討論.md`** | 暫時性的基礎技術選型討論：語言、Framework、DB、基本測試／部署工具 |
| **`docs/Px/實作規格.md` / `docs/Mxx/實作規格.md`** | 該 Phase / Subphase 完成後什麼必須為真、驗收意圖；不寫具體 DB/API |
| **`docs/Px/開發設計方針.md` / `docs/Mxx/開發設計方針.md`** | 該 Phase / Subphase 的具體實作契約：資料模型、模組、API、資料流、接線、必要技術決策 |
| **`docs/Px/測試指南.md` / `docs/Mxx/測試指南.md`** | 該 Phase / Subphase 的自動／人工驗收流程與測試證據要求 |
| **SRD / 規則資料檔** | 所有規則內容與可調數值 |
| **`待決事項.md`** | 真正無法從既有規格推導、且會影響核心玩法／方向的未決問題 |

**文件裡不重複抄規則數值**，一律指向資料檔。

判準：**如果一句話不同，DM／Player 的實際跑團方式可能就不同 → `規格企劃.md`；如果是某 Phase 要做到什麼 → 該 Phase `實作規格.md`；如果是怎麼實作 → 該 Phase `開發設計方針.md`。**

## Phase / Subphase 設計原則

1. **只設計正在準備開工的 Phase。**
2. **所有正常產品 Phase 在 coding 開始前，都必須先拆成 `P<n>-A`、`P<n>-B`… 的 Subphases。所有 Maintenance / Modification Phase 在 coding 開始前，都必須先拆成 `M<nn>-A`、`M<nn>-B`… 的 Subphases。** 每個 Subphase 必須能獨立實作、驗證並 commit；完成時應處於可執行、可測試、沒有已知編譯／型別／該 Subphase 測試錯誤的狀態。
3. **M Phase 定位**：`M01`、`M02`… 用於補資料／補設定、既有能力加強、資料 migration、或不構成下一個正常產品里程碑的維護／修改工作。M Phase 可以插在 P Phase 之間，**也可以插在另一個 M Phase 的兩個 Subphase 之間**（目前 M02 就插在 M01-C 與 M01-D 之間）；但不改寫 `P0 → P1 → P2...` 的正常 Roadmap。被暫停的 M Phase 保留原本的 Subphase 編號與順序，恢復後照原順序接續。
4. **Subphase 只拆當前 Phase，不提前拆後續 Phase。** 尚未輪到的 P Phase 或 M Phase 保持大 Phase / 未建立狀態；可以記錄必要的跨 Phase 承接要求，但不得因此提前設計未來 Phase 的 schema / API / module。
   **唯一例外：使用者已明確決定要插入、且插入點已確定的 M Phase，可以在插入點到達前先完成拆分與三份文件**（M02 即為此例，插入點固定在 M01-C closeout 後）。此例外只適用已拍板的插入，不適用「將來可能會做」的 Phase。
5. 同一 Phase 的 `實作規格.md`、`開發設計方針.md`、`測試指南.md` 必須使用完全一致的 Subphase 名稱與順序，讓實作者可用 Subphase id 精準取得三份契約。
6. `PROJECT_BRIEF.md` 在當前 Phase 已拆分後，必須一列一個 Subphase 顯示進度，不可再用「P0（含 A～F）」或「M01（含 A～K）」合併成一列。
7. 可以記錄已知的跨 Phase 相容要求，例如 P0 可以要求 Character 資料模型不得排斥 Multiclass；但不用現在決定 P2 Token table 或 P5 Tactical renderer。
8. 後續 Phase 開工時，以當時真正存在的 codebase 為基礎再設計，比現在猜測更可靠。

## 修改授權與驗證規則

除非使用者明確要求「修」、「修改」、「實作」、「處理某個 phase」、「commit」或「提交」，否則不得：

- 修改任何程式碼、文件或設定檔
- 自行套 patch
- stage 檔案
- 建立 commit

當使用者要求「驗證」，或只是描述錯誤、貼截圖、詢問原因、要求解釋、要求列出問題、詢問某功能怎麼使用時：只能進行檢查、讀檔、執行測試、code review、啟動本機服務與回報結果。若發現問題，只列出問題、影響範圍與建議修法，等待使用者下一步指示。

(English mirror: only modify files when the user explicitly requests fix / implement / commit. Verify / diagnose = report only.)

## 設計討論的方式

**每個問題都要先想好一個解法再拿出來討論。** 不要把開放題原封退回給使用者。

- 有多種讀法時，把選項連同取捨一起端出來，並且給出推薦。
- 發現設計有洞時，講清楚影響範圍。
- 新提議與 `規格企劃.md` 衝突時，先指出衝突，不得默默推翻既有規格。
- 使用者重申某個決定時，那就是拍板；照做，不要重新辯論。
- **避免為還沒到的 Phase 過度討論實作。** 純技術細節能延後就延後到對應 Phase。

只有符合以下條件才回頭問使用者：A/B 選擇會明顯改變跑團方式、影響 DM / Player 核心權利、改變規則玩法、造成難以逆轉的產品方向，而且從既有規格無法合理推導。純技術或一般 UX 問題自己決定。

## 產品層實作守則

1. **Server 是唯一真實狀態來源。** AI 不直接操作 DB raw fields；Human 與 AI 使用同一套 GameAction / backend logic。
2. **秘密靠 Server 過濾，不靠 UI 隱藏。** Secret DC、DM Notes、Hidden Monster、他人 private knowledge 不送給 Player / AI Player。
3. **Optional 不得變 Mandatory。** Quest、Scene、NPC、Position Note、Campaign Fact 等可以完全不建立而繼續跑團。
4. **網站不接 LLM API。** 後端沒有模型可呼叫，所有 AI 能力來自使用者的外部 AI Session。
5. **內容逐步擴充，SRD 5.1 是起點不是上限。** 非 SRD 內容依實際需要逐步加入。
6. **Human UI 與 AI MCP 共用同一份 backend logic**，不做兩套遊戲邏輯。

## 工程實作守則

1. **API 簽名預先核對**：呼叫任何專案內模組或 API 前，先 grep / 讀檔核對最新定義與參數列，不憑記憶編寫。
2. **編譯／型別錯誤同 turn 修完**：跑測試或檢查時取同步結果；有錯就在同一個 turn 內修到通過，不讓錯誤流向使用者。
3. **驗收對應**：每條 Phase / Subphase 驗收契約都要有可定位的測試證據。
4. **權限與可見性必測**：當 Phase 涉及 Role / Seat / Controller 時，除了 happy path，必測不該看到／不該操作的 actor。
5. **拒絕原子性與 fixture 隔離**：契約要求零副作用的拒絕操作，前後狀態不可被污染；測試 fixture 必須完整還原。
6. **Supported locale 同步交付**：新增、修改，或因新畫面而首次 expose user-visible system / rules content 時，必須在同一個 Subphase 同步補齊所有正式 supported locale（目前為 `zh-TW` / `en`），包含 UI copy、rules presentation field、validation / error 訊息與 searchable 欄位。缺任一語言視同該 Subphase regression，不得以「先做英文、之後再補 M Phase」結案。

## 文件關門的固定提交流程

verifier 完成已知問題或 Phase 的文件關門後，在同一 turn `commit` 並 `push`，不必等待再次提醒。這只適用已獲授權的文件關門；其他程式、資料或設定修改仍依「修改授權與驗證規則」。

---

## 本機 Windows 環境專用

> 本段僅適用於使用者本機 Windows 環境（工具都在 `C:\`）。**remote / CI / Linux session 沒有這些路徑與工具，跳過本段。**

專案路徑：`C:\_work\AI_Work\Projects\adventure-table`

### Python 執行環境規則

⚠️ 本專案目前**沒有 `.venv`**。若開始 Python 實作，先在專案根目錄建立，之後一律使用 `.\.venv\Scripts\python.exe`，讓 agent 與使用者看到一致結果。

### 本機工具

外部工具不放進本專案 repo。

| 工具 | 路徑 | 用途 |
|---|---|---|
| Codex DeepSeek home | `C:\_work\AI_Work\Tools\codex-deepseek-home` | DS reviewer 環境 |
| Antigravity CLI | `C:\Users\User\AppData\Local\agy\bin\agy.exe` | agy reviewer |

### DeepSeek Codex CLI Reviewer

使用者說「要 ds4 pro 做 XXX」「要 ds4 flash 做 XXX」時，透過本機 Moon Bridge DeepSeek 設定走 Codex CLI。

Model mapping：`ds4 pro` → `deepseek-v4-pro`；`ds4 flash` → `deepseek-v4-flash`；只說 `ds4` 用 `deepseek-v4-pro`。

Default mode: read-only reviewer.
- 用 `CODEX_HOME=C:\_work\AI_Work\Tools\codex-deepseek-home`。
- 不寫檔、不刪檔、不 stage、不 commit、不 push。
- 不讀 `.env`、`C:\_work\AI_Work\Tools\`。
- 結果當第二意見，回報前先自己審一遍。
- 非互動呼叫（`codex exec`）必須 `< NUL` 關閉 stdin，否則會停在 `Reading additional input from stdin...` 永久卡死。

### Antigravity CLI (agy) Reviewer

使用者說「要 agy 做 XXX」「用 agy 審 / 驗證 XXX」時走 `agy`。

Binary 在 user PATH，但部分 shell 的 PATH 快照可能沒有，直接用完整路徑最穩。

```powershell
cmd /c "C:\Users\User\AppData\Local\agy\bin\agy.exe -p `\"<任務>`\" --model `\"<模型>`\" --add-dir `\"C:\_work\AI_Work\Projects\adventure-table`\" --dangerously-skip-permissions --print-timeout 540s < NUL > <輸出檔> 2>&1"
```

四個參數都是必要的：

- `< NUL`：非 TTY 下避免等待 stdin。
- `> 檔案`：保留輸出。
- `--add-dir <專案路徑>`：讓 reviewer 讀到專案。
- `--dangerously-skip-permissions`：單次生效，不動持久設定。

Model selection：`--model` 使用 `agy models` 列出的完整顯示字串；未指定時預設 `"Gemini 3.5 Flash (High)"`。

Default mode: read-only reviewer；跑完必以 `git status` / `git diff` 確認實際改動。

### Codex CLI (OpenAI) Reviewer

使用者說「要 codex 做 XXX」「用 codex 審 / 驗證 XXX」（不帶 `ds4`）時，用預設 `CODEX_HOME` 走 `codex exec`。

```powershell
cmd /c "codex exec `\"<任務>`\" --sandbox read-only -C `\"C:\_work\AI_Work\Projects\adventure-table`\" --ephemeral -o `\"<結果檔>`\" < NUL > `\"<過程log檔>`\" 2>&1"
```

- `< NUL`：避免非 TTY 等待 stdin。
- `--sandbox read-only`：引擎層強制唯讀；寫入任務改 `--sandbox workspace-write`。
- `-o <結果檔>`：只寫最終回覆，與 stdout 完整過程 log 分離。

Model selection：預設依本機 Codex 設定；要換模型用 `-m <model>`，專注程度用 `-c model_reasoning_effort="low/medium/high"` 覆蓋。

Default mode: read-only reviewer；結果當第二意見。
