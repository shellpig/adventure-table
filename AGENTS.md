# Agent Instructions

# Adventure Table

一個**輕量、桌上跑團優先的 D&D 5e 2014 VTT**。真人 DM 像實體跑團一樣主要靠口頭敘事，只在需要時使用網站工具；外部 AI 透過 MCP / Site Tools 正式進桌當 DM 或 Player，與真人共用同一套 Game State、規則與權限。

- **類型**：Web VTT（虛擬桌面），非 CRPG、非 Foundry 式全能平台
- **一句話**：網站只管需要共享、同步、計算、保存、權限與 AI 接入的東西，其餘還給 DM 的嘴巴
- **首發規則集**：D&D 5e 2014；Built-in Content：SRD 5.1（CC BY 4.0）
- **專案性質**：朋友間私人使用，非預計商品化平台
- **目前階段**：產品規格已定案，**尚未進入實作**。下一步是規劃 P0 `Character Core + SRD / Rules Foundation`
- **目前進度**：以 `PROJECT_BRIEF.md` 為單一事實來源
- **技術選型**：**討論中，尚未正式拍板**。目前 review 中的推薦方案見 `技術棧討論.md`；只有整理進 `開發設計方針.md` 後才算正式 technical SSOT

## New Conversation Opening Check

**Layer 1 — 必讀：**
1. `AGENTS.md`（本檔）
2. `PROJECT_BRIEF.md`（當前 Phase、Roadmap、文件索引）
3. `git log --oneline -10`

**Layer 2 — 按任務讀對應文件／段落（見下方查閱規則）：**
- `規格企劃.md` — **產品與玩法的單一事實來源**。約 70 KB，一律標題定位、只讀該段
- `技術棧討論.md` — **暫時性技術 review 文件**；只有做技術選型、架構討論、P0 開發設計前置審查時才讀。它不是正式 technical SSOT

**Layer 3 — 尚未建立，Phase 開工時才生：**
- `實作規格書.md` — 該 Phase 必須做到什麼＋驗收意圖
- `開發設計方針.md` — 正式實作契約與 technical SSOT（架構、模組、API、MCP、資料流；implementer 角色）
- `測試指南.md` — 操作層驗收（verifier 角色）
- `待決事項.md` — 只收真正無法從既有規格推導、且會影響核心玩法的問題

> 不要為了湊齊文件而預先建立空檔。目前 repo 的主要專案文件是 `AGENTS.md`、`PROJECT_BRIEF.md`、`規格企劃.md`、`技術棧討論.md`。其中 `技術棧討論.md` 是暫時 review 文件，討論完成後內容應編入 `開發設計方針.md`，再停止維護或刪除。

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

`技術棧討論.md` 只在技術選型／架構 review 任務使用；如果 `開發設計方針.md` 已建立且某決策已正式落入方針，**正式方針優先，討論稿不再覆蓋它**。

**不要依賴行號**——行號隨編輯漂移，一律以標題或關鍵字定位。

`規格企劃.md` 的定位鍵是章節中文數字與 `###` 小節：

```bash
grep -n "^## \|^### " 規格企劃.md
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
| Timeline / GameTransaction / Undo / Snapshot | 九 |
| Inventory / Loot / Shop / Quest / Rest | 十 |
| 資料生命週期 / Export / Import | 十一 |
| **第一版明確不做** | 十二 |
| 文件維護與討論規則 | 十三 |
| 開發接手原則 | 十四 |

**提新功能前先看第十二章。** 那份清單是刻意砍掉的東西，不是還沒做的待辦。

## 文件分工與單一事實來源

**同一件事只住一個地方。**

| 住哪 | 放什麼 | 例 |
|---|---|---|
| **`規格企劃.md`** | 產品行為與**為什麼**：跑團方式、權限、規則選擇、UI 行為、明確不做 | 「Quick Combat 不追移動距離，Dash 只是敘事宣告」 |
| **`PROJECT_BRIEF.md`** | 當前 Phase、Roadmap、下一步、文件索引 | 「下一步：規劃 P0」 |
| **`技術棧討論.md`** | **暫時性 review / 提案**；收集技術候選、外部 AI 意見與尚未正式落檔的架構選擇 | 「Vite vs Next.js」「Permission projection 怎麼做」 |
| **SRD / 規則資料檔**（P0 建立） | **所有規則內容與可調數值** | Spell、Monster stat block、Class progression table |
| **`實作規格書.md`** | 該 Phase 什麼必須為真（驗收意圖） | 「從空白可建出合法的 Fighter 5 / Wizard 5」 |
| **`開發設計方針.md`** | **正式 technical SSOT**：技術棧、架構、模組、API、MCP、資料流、接線 | 「Reference file truth → idempotent DB import」 |
| **`待決事項.md`** | 真正還沒拍板、會影響核心玩法的問題 | — |

`技術棧討論.md` 的生命週期：

```text
技術提案 / 外部 Review
↓
討論收斂
↓
正式決策編入 開發設計方針.md
↓
技術棧討論.md 停止維護／刪除
```

**文件裡不寫規則數值**，一律指向資料檔。理由：SRD 內容量大且會逐步擴充，文件抄一份就會過期。

判準沿用規格企劃的開頭：**如果一句話不同，DM／Player 的實際跑團方式可能就不同 → 進 `規格企劃.md`；否則就是實作細節，自己決定。**

## 修改授權與驗證規則

（單一事實來源；其他文件不重複本節內容。）

除非使用者明確要求「修」、「修改」、「實作」、「處理某個 phase」、「commit」或「提交」，否則不得：

- 修改任何程式碼、文件或設定檔
- 自行套 patch
- stage 檔案
- 建立 commit

當使用者要求「驗證」，或只是描述錯誤、貼截圖、詢問原因、要求解釋、要求列出問題、詢問某功能怎麼使用時：只能進行檢查、讀檔、執行測試、code review、啟動本機服務與回報結果。若發現問題，只列出問題、影響範圍與建議修法，等待使用者下一步指示。

(English mirror: only modify files when the user explicitly requests fix / implement / commit. Verify / diagnose = report only.)

## 設計討論的方式

**每個問題都要先想好一個解法再拿出來討論。** 不要把開放題原封退回給使用者。

- 有多種讀法時，把選項連同取捨一起端出來，並且**給出推薦**。
- 發現設計有洞時，講清楚**影響範圍**（哪個系統、哪條規則、哪個既有決策會被打到），不要只說「這裡怪怪的」。
- **新提議與 `規格企劃.md` 衝突時，先指出衝突，不得默默推翻既有規格。**
- 使用者重申某個決定時，那就是拍板；照做，不要重新辯論。

只有符合以下條件才回頭問使用者：A/B 選擇會明顯改變跑團方式、影響 DM / Player 核心權利、改變規則玩法、造成難以逆轉的產品方向，而且從既有規格無法合理推導。純技術或一般 UX 問題自己決定。

## 產品層實作守則

這幾條是本專案最容易做錯、而且做錯就違反產品定位的地方：

1. **Server 是唯一真實狀態來源。** AI 不直接操作 DB raw fields；Human 點 Attack 與 AI 呼叫 `attack()` 走同一條 GameAction → Validation → GameTransaction → State。**不要為 AI 開後門 API。**
2. **秘密靠 Server 過濾，不靠 UI 隱藏。** Secret DC、DM Notes、Hidden Monster、他人 private knowledge 根本不送給 Player / AI Player。先送再用 CSS 或 prompt 藏起來就是 bug。
3. **Optional 不得變 Mandatory。** Quest、Scene、NPC、Position Note、Campaign Fact 等都可以完全不建立而繼續跑團。任何「必須先建 X 才能做 Y」的流程都要先確認規格是否真的要求。
4. **網站不接 LLM API。** 後端沒有模型可呼叫，所有 AI 能力來自使用者的外部 AI Session。看到「這裡叫個 LLM 就好了」的設計，先停下來。
5. **內容是逐步擴充的，SRD 5.1 是起點不是上限。** 使用者需要某個 Race / Class / Subclass / Feat / Spell / Item / Monster 時就提供資料，然後補進系統，內容資料一路長進 repo。**不要因為某個東西不在 SRD 就拒絕做**，也不要求第一版把內容做齊；底層資料結構要能容納非 SRD 內容。
6. **Human UI 與 AI MCP 共用同一份 backend logic**，不做兩套遊戲邏輯。

## 工程實作守則

1. **API 簽名預先核對**：呼叫任何專案內模組或 API 前，先 grep / 讀檔核對最新定義與參數列，不憑記憶編寫。
2. **編譯／型別錯誤同 turn 修完**：跑測試或檢查時取同步結果；有錯就在同一個 turn 內修到通過，不讓錯誤流向使用者。
3. **角色分離**：實作者改程式碼、測試、fixture 與 `開發設計方針.md`（implementer-owned）。`測試指南.md`、`PROJECT_BRIEF.md` 屬 verifier 角色，實作者只列建議、不直接改。實作者跑完只提供證據（exit code、報告路徑、實際數字），打勾與落檔由 verifier 做——**要求實作者自己勾自己的驗收就是分工失效**。
4. **驗收對應與變異保真**：每條驗收契約都要有可定位的測試證據；完成後暫時反轉目標判斷，確認對應測試確實轉紅，再還原並重跑全綠。不得只憑測試名稱、註解或成功路徑宣稱已覆蓋。
5. **權限與可見性必測**：涉及 Role / Seat / Controller 的功能，除了 happy path，至少要有一條「不該看到的人收不到」與一條「已撤銷 token 被拒絕」的測試。
6. **拒絕原子性與 fixture 隔離**：契約要求零副作用的拒絕操作，前後可序列化狀態必須逐字一致；測試注入的 mock／壞資料必須在案例結束後完整還原，不得污染後續測試。

## 文件關門的固定提交流程

verifier 完成已知問題或 Phase 的文件關門後，在同一 turn `commit` 並 `push`，不必等待再次提醒。這只適用已獲授權的文件關門；其他程式、資料或設定修改仍依「修改授權與驗證規則」。

---

## 本機 Windows 環境專用

> 本段僅適用於使用者本機 Windows 環境（工具都在 `C:\`）。**remote / CI / Linux session 沒有這些路徑與工具，跳過本段。**

專案路徑：`C:\_work\AI_Work\Projects\adventure-table`

### Python 執行環境規則

⚠️ 本專案目前**沒有 `.venv`**，技術選型仍在 review。若正式方針採 Python backend，先在專案根目錄建立 `.venv`，之後一律使用 `.\.venv\Scripts\python.exe`，讓 agent 與使用者看到一致結果。

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
cmd /c "C:\Users\User\AppData\Local\agy\bin\agy.exe -p `"<任務>`" --model `"<模型>`" --add-dir `"C:\_work\AI_Work\Projects\adventure-table`" --dangerously-skip-permissions --print-timeout 540s < NUL > <輸出檔> 2>&1"
```

四個參數都是必要的，各修一個已驗證的失敗模式：

- `< NUL`：非 TTY 下 agy 會癡等 stdin 永久卡死（連自己的 print-timeout 都不會觸發）。主因是 stdin，不是權限確認框。
- `> 檔案`：非 TTY 下 stdout 不導檔就看不到任何輸出。
- `--add-dir <專案路徑>`：不加的話 agy 只在自己的 sandbox 暫存區活動，cwd 不算數——它會回報成功但專案裡什麼都沒發生。
- `--dangerously-skip-permissions`：單次生效，不動持久設定。

Model selection：`--model` 吃 `agy models` 列出的**完整顯示字串**（含括號內專注程度），例如 `"Gemini 3.5 Flash (High)"`。未指定時一律預設 `"Gemini 3.5 Flash (High)"`。

Default mode: read-only reviewer.
- prompt 內明確要求：不建立 / 修改 / 刪除任何檔案、不跑會寫檔的命令、輸出純文字報告。
- 跑完必以 `git status` / `git diff` 確認實際改動；agy 的口頭回報不可作為改動依據。

### Codex CLI (OpenAI) Reviewer

使用者說「要 codex 做 XXX」「用 codex 審 / 驗證 XXX」（不帶 `ds4`）時，用預設 `CODEX_HOME` 走 `codex exec`。

```powershell
cmd /c "codex exec `"<任務>`" --sandbox read-only -C `"C:\_work\AI_Work\Projects\adventure-table`" --ephemeral -o `"<結果檔>`" < NUL > `"<過程log檔>`" 2>&1"
```

- `< NUL`：非 TTY 下會停在 `Reading additional input from stdin...` 永久卡死，與 agy 同族病因。
- `--sandbox read-only`：引擎層強制唯讀（比 prompt 口頭約束可靠）；寫入任務改 `--sandbox workspace-write`。
- `-o <結果檔>`：只寫最終回覆，與 stdout 的完整過程 log 分離。

Model selection：預設 `gpt-5.5` + `model_reasoning_effort = "high"`（來自 `~/.codex/config.toml`）。要換模型用 `-m <model>`，專注程度用 `-c model_reasoning_effort="low/medium/high"` 覆蓋。

Default mode: read-only reviewer；結果當第二意見。
