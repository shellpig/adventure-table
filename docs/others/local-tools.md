# 本機工具與執行規則

本檔承接 [AGENTS.md](../../AGENTS.md) 的本機 Windows 與外部 reviewer／worker 指令。不是開場必讀；執行相關工作前只讀對應段落。

| 工作 | 先讀本檔段落 |
|---|---|
| Python／pytest／alembic／uvicorn | Python 執行環境規則 |
| E2E | E2E 測試執行規則 |
| Standalone 打包／smoke | Python 執行環境規則的發版例外，以及 [README](../../README.md) 發版步驟 |
| 外部 reviewer／worker | 本機工具、外部 Reviewer / Worker CLI 的共通規則與所選工具；實作派工另讀 [指揮者手冊](conductor-handbook.md) 共通段落與所選 worker 段落 |

## 本機 Windows 環境專用

> 本段僅適用於使用者本機 Windows 環境（工具都在 `C:\`）。**remote / CI / Linux session 沒有這些路徑與工具，跳過本段。**

專案路徑：`C:\_work\AI_Work\Projects\adventure-table`

### Python 執行環境規則

一律使用專案根目錄的 `.\.venv\Scripts\python.exe`，讓 agent 與使用者看到一致結果。

Backend server app 的指令（`pytest`、`alembic`、`uvicorn`）cwd 一律為 `apps/server`，直譯器一律 `..\..\.venv\Scripts\python.exe`。兩行分開下，**不要用 `cd ... && ...` 串成單行**——本機是 Windows PowerShell 5.1，沒有 `&&`：

```
cd apps/server
..\..\.venv\Scripts\python.exe -m pytest tests/test_<subphase>_*.py
```

`pyproject.toml` 的 addopts 預設 `-n 8 --dist loadgroup`（pytest-xdist，dev extra）：全套約 1 分鐘，focused run 多付約 2 秒 worker 啟動；要單程序跑（例如 `--pdb` 或看 print）加 `-n 0`。Postgres 測試以 `xdist_group("postgres")` 固定在同一個 worker，因為它們共用並重置同一個 `P4_POSTGRES_URL` 資料庫。parametrize id 不得含隨機值（`uuid4()` 等），否則各 worker 收集結果不一致、xdist 拒跑。

`tests/test_m03b_migration.py` 等測試用裸相對路徑讀 `alembic.ini` 與 `alembic/versions/`，cwd 不在 `apps/server` 會失敗；pytest 的 rootdir 解析到 `apps/server/pyproject.toml` 不代表 cwd 也跟著換。

例外：`scripts\` 底下的發版與 smoke 工具從 repo root 執行，並使用 AGENTS.md「工程實作守則」第 8 條指定的 `.standalone-venv` / `STANDALONE_PYTHON`，不是這裡的 `.venv`。

### E2E 測試執行規則

**Windows 上不得讓 Playwright 託管 vite。** dev server 會在跑測試途中停止接受連線，造成數十個 `net::ERR_CONNECTION_REFUSED`（KI-ENV-001，上游 vite 未修）。整套 E2E 一律走容器裡的 Linux dev server：

```
cd apps/web
npm run test:e2e:docker
```

該 script 內的 `--build` 不可省——`web` service 沒有掛 bind mount，略過重建會靜默測到上一版 frontend。

無參數時 script 依 `playwright.config.ts` 的三個 project 分三趟跑，每趟各自 reset DB：`parallel`（大多數 spec，每個 worker 自建 Room，預設 2 workers，`E2E_PARALLEL_WORKERS` 可調——server-e2e 是單一 uvicorn process，2 個 worker 就到 ~100% CPU，4 個不會更快且 Builder review 會開始 flake）、`baseline-room`（依賴 seed 出的 P0 fixture 角色的 spec，只在 global setup 建的第一個 Room 有這個角色，單 worker）、`serial-restart`（會 `docker compose restart server-e2e` 的 P4-F journey，單 worker）。帶參數時只跑一趟，預設 1 worker；新 spec 若依賴 fixture 角色或會重啟 server，要加進 config 對應清單，否則會被放進 `parallel`。

`playwright.config.ts` 會直接擋下 Windows 託管路徑；要重現該 dev server問題才設 `ALLOW_WINDOWS_VITE_E2E=1`。細節見 `已知問題.md` 的 KI-ENV-001。

### 本機工具

外部工具不放進本專案 repo。

| 工具 | 路徑 | 用途 |
|---|---|---|
| Codex DeepSeek home | `C:\_work\AI_Work\Tools\codex-deepseek-home` | DS reviewer 環境 |
| Antigravity CLI | `C:\Users\User\AppData\Local\agy\bin\agy.exe` | agy reviewer |

### 外部 Reviewer / Worker CLI

把 agy 或 ChatGPT 當 **worker**（實作而非 review）時，流程、step 粒度、檢查節奏與踩坑一律看 `docs/others/conductor-handbook.md`；本段只保留啟動指令。

三個 reviewer 共通：**預設 read-only**——不寫檔、不刪檔、不 stage、不 commit、不 push，不讀 `.env` 與 `C:\_work\AI_Work\Tools\`；非互動呼叫必須 `< NUL` 關閉 stdin，否則會停在等待輸入永久卡死；輸出重導到檔案保留；結果只當第二意見，回報前先自己審一遍，並以 `git status` / `git diff` 確認實際改動。

| 觸發語 | 走哪個 |
|---|---|
| 「要 ds4 / ds4 pro / ds4 flash 做 XXX」 | DeepSeek via Codex CLI |
| 「要 agy 做 XXX」「用 agy 審 / 驗證 XXX」 | Antigravity CLI |
| 「要 codex 做 XXX」（不帶 `ds4`） | Codex CLI (OpenAI) |

**DeepSeek via Codex CLI**：透過本機 Moon Bridge DeepSeek 設定，用 `CODEX_HOME=C:\_work\AI_Work\Tools\codex-deepseek-home`。Model：`ds4 pro` → `deepseek-v4-pro`；`ds4 flash` → `deepseek-v4-flash`；只說 `ds4` 用 `deepseek-v4-pro`。

**Antigravity CLI**：binary 在 user PATH，但部分 shell 的 PATH 快照可能沒有，直接用完整路徑最穩。agy 有兩種用法：**review**（沿用上方 read-only 共通規則）與 **worker**（可寫程式與測試，但仍不得 stage / commit / push；commit 權在 Claude）。

```powershell
cmd /c "C:\Users\User\AppData\Local\agy\bin\agy.exe -p `\"<任務>`\" --model `\"<模型>`\" --add-dir `\"C:\_work\AI_Work\Projects\adventure-table`\" --dangerously-skip-permissions --output-format json --print-timeout 20m < NUL > C:\_work\AI_Work\Tools\agy-runs\<步驟>.json 2>&1"
```

- `--add-dir` 讓 agy 讀到專案，`--dangerously-skip-permissions` 單次生效不動持久設定，兩者都不可省。
- **`-p` 只能放單行短句，任務本文寫進檔案讓 agy 自己讀**（例：`-p "Your full task is in C:\_work\AI_Work\Tools\agy-runs\<步驟>.prompt.txt. Read it first, then follow every instruction in it."`，並多加一個 `--add-dir C:\_work\AI_Work\Tools\agy-runs`）。多行 prompt 經 `cmd /c` 會在第一個換行截斷，後面的 flag 與重導全部遺失，agy 會以無權限狀態靜默結束。
- **一律 `run_in_background` 啟動**，不同步等；結束時 Claude 會被喚醒，直接讀輸出檔審結果。輸出落在 repo 外的 `C:\_work\AI_Work\Tools\agy-runs\`，session 中斷也找得回。不再使用寫死的 `--print-timeout 540s`。
- `--output-format json` 回傳 `conversation_id`／`status`／`duration_seconds`／`usage`。**同一步驟的修改回合用 `--conversation <id>` 接續**（已驗證可在 `--print` 模式保留脈絡；每輪整段重送、無 cache，累積數輪即換新對話）。**換下一步驟一律開新對話**。
- **prompt 骨架**：一律從 `C:\_work\AI_Work\Tools\agy-runs\TEMPLATE.prompt.txt` 複製再填：必讀清單（已載入的 AGENTS.md 不重讀 → 精簡 PROJECT_BRIEF.md → 該 Subphase 接手摘要與步驟板、自己那步紀錄 → 三份 Phase 文件對應段及必要共用前言 → 要動的程式檔與相關 API 定義）→ scope（含「不該看到／不該操作」的 actor 測試）→ code quality 條款 → 測試指令 → hard rules → final report。**code quality 條款**：`getattr` 帶 default／bare `Any`／吞錯 broad except 由 `apps/server/tests/test_code_quality_gate.py` 擋（每次 pytest 都跑），prompt 只需要求通過該測試；仍要點名每個要共用的既有 helper，並禁 `lru_cache` fallback global、沒人呼叫的參數、重複 route、整段複製既有函式。
- **拆步原則**：每個 agy 任務要在 15～20 分鐘內收斂到可驗證狀態；prompt 自足，只指向該步要讀的規格段落，明列交付物、focused test 指令與「不得 commit」。Subphase 進度只寫在 `<Subphase>實作紀錄.md` 的步驟板；新紀錄的摘要與各步檔案格式見 [指揮者手冊 §2.4](conductor-handbook.md#24-實作紀錄格式)，新對話只讀摘要、步驟板與相關步驟；agy 對話 ID 遺失不影響交接。
- 每步結束後 Claude 以 `git diff` 審改動、跑該步 focused test，通過才 commit；失敗把錯誤餵回同一對話修。**審完若剩餘修改很小（幾行、單一檔案、不需重新理解脈絡），Claude 直接自己改完再 commit，不再開 agy 回合。**
- Model：`--model` 用 `agy models` 列出的完整顯示字串，未指定時預設 `"Gemini 3.8 Flash (High)"`。

**Codex CLI (OpenAI)**：用預設 `CODEX_HOME`。

```powershell
cmd /c "codex exec `\"<任務>`\" --sandbox read-only -C `\"C:\_work\AI_Work\Projects\adventure-table`\" --ephemeral -o `\"<結果檔>`\" < NUL > `\"<過程log檔>`\" 2>&1"
```

`--sandbox read-only` 是引擎層強制唯讀，寫入任務才改 `--sandbox workspace-write`；`-o <結果檔>` 只寫最終回覆，與 stdout 的完整過程 log 分離。Model：預設依本機 Codex 設定，要換用 `-m <model>`，專注程度用 `-c model_reasoning_effort="low/medium/high"` 覆蓋。
