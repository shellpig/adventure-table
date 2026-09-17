# 指揮者手冊 — 讓 agy / ChatGPT 實作，指揮者驗證與收尾

適用對象：被指定為「指揮者」的 AI session（目前是 Claude Code）。指揮者不自己寫主要程式，而是把 Subphase 拆成小步驟交給外部 worker（Antigravity CLI `agy`、ChatGPT Web）實作，再在本機驗證、審核、修小錯、commit、push、更新實作紀錄。

本檔是流程與踩坑紀錄，不是 Phase 契約。Phase 要做什麼看 `docs/Px/` 三份文件；本檔只講「怎麼讓別人做、怎麼確認做對」。

首次成型：2026-09-17，P4-E（E1～E9b 由 agy、E10a 起由 ChatGPT）。

---

## 1. 角色分工

| 角色 | 做什麼 | 不做什麼 |
|---|---|---|
| 使用者 | 拍板 step 範圍、選 worker、決定何時停 | 不盯進度（指揮者負責） |
| 指揮者（本 session） | 讀契約、拆 step、寫 prompt、送出、定時檢查、pull、跑測試、審 diff、修小錯、commit、push、更新 `<Subphase>實作紀錄.md` | 不重寫 worker 的大段程式（改動超過幾個檔案就退回 worker）；不改 Phase 三份文件（verifier 職權） |
| worker（agy / ChatGPT） | 讀指定文件與程式、寫程式與測試、回報 | agy：不得 git add / commit / push；ChatGPT：可 commit + push 到指定 branch，但不得開新 branch / 動 main / force push / rebase |

**commit 權責**：agy 產出由指揮者 commit；ChatGPT 自己 commit（author 是 repo owner，沒有 Co-Authored-By）。指揮者自己的修正另開 commit，訊息寫清楚修了 worker 的什麼。

---

## 2. 共通原則（兩種 worker 都適用）

### 2.1 step 粒度

- **一個 step = 15～20 分鐘內能收斂到「測試綠、可 commit」的量。** 判準：一條 route + 對應 client、或一個元件 + 測試、或一個 domain 函式 + route + 測試。
- 大 step 一定失敗：P4-E E10c 整包（rolls + reactions + grapple/shove + reach）連續兩回合 timeout；拆成 E10c-1 / E10c-2 後各一回合完成。
- step 命名接在 Subphase 步驟板後面（E10a、E10b、E10c-1…），寫進 `docs/<Phase>/<Subphase>實作紀錄.md` 的「步驟進度」表，這張表是唯一的進度真相；`PROJECT_BRIEF.md` 不記 step。

### 2.2 prompt 骨架

從 `C:\_work\AI_Work\Tools\agy-runs\TEMPLATE.prompt.txt` 複製（本機路徑，見 `AGENTS.md`「本機 Windows 環境專用」），固定段落：

1. **身分與狀態**：step 名、branch、HEAD hash、已完成的 step。
2. **MANDATORY READING**：`AGENTS.md` 要點 → 該 Subphase `實作紀錄.md` → 三份 Phase 文件對應段 → **要動的每個程式檔（列檔名 + 它是做什麼的 / 現在缺什麼）**。server contract 一律把 route、input / view model 的欄位寫出來，不要只寫檔名。
3. **SCOPE**：A/B/C… 條列，含測試案例清單，**必列「不該看到 / 不該操作」的 actor**（Player 看不到 DM 控制、非本場 participant 被拒且零副作用）。
4. **Do not touch**：明列不可碰的檔案 / 區域。
5. **CODE QUALITY**：不可省。點名要共用的既有 helper；禁 `getattr` / `Any` / 吞錯 try-except / optional-everything props + 空值 guard / 假資料補值 / `"?"` 佔位；「貼超過 ~20 行就抽 helper」。
6. **VERIFICATION**：worker 跑不了或不可靠時，寫明指揮者會跑哪些指令。
7. **HARD RULES / GIT**：agy 不得 git 操作；ChatGPT 的 commit message、parent hash、禁 force push。
8. **FINAL REPORT**：固定五項（commit / 檔案 / 新簽名 / 測試名 / 契約疑點）。

prompt 檔存 `C:\_work\AI_Work\Tools\agy-runs\<worker>-<phase>-<step>.prompt.txt`，session 中斷後可從這裡與實作紀錄接手。

### 2.3 指揮者驗證 gate（每個 step）

```
git pull --ff-only（ChatGPT）或 git diff（agy 直接改本機）
→ focused pytest（cwd apps/server，..\..\.venv\Scripts\python.exe）
→ 受影響 Phase 的 regression pytest（例：P4-B/C/D/E 全部 test_p4*）
→ npm test -- --run、npm run build（cwd apps/web，只要動到 apps/web）
→ 讀 diff（見 §5 checklist）
→ 修小錯（幾行、單一目的）
→ 更新 <Subphase>實作紀錄.md 的步驟表 + 步驟紀錄
→ commit + push
```

Subphase 關門與合併回 `main` 的 gate 照 `AGENTS.md`「工程實作守則」第 4 條，不在本檔重述。

### 2.4 實作紀錄格式

每個 step 一段 `### <step> — <標題>`，固定寫：起始（日期、worker、回合數與時長）、交付（具體到函式 / route / 元件 / copy key 數）、**指揮者審核修正**（worker 犯了什麼、改成什麼）、測試（指令與數字）、留給下一步。這段是下一個指揮者接手時唯一需要讀的東西，寫具體。

---

## 3. agy（Antigravity CLI）流程

啟動指令、`--add-dir`、`-p` 單行限制、背景執行、`--conversation` 接續、model 名稱：全部見 `AGENTS.md`「Antigravity CLI」，本檔不重抄。

指揮者要做的：

1. 寫 prompt 檔 → 背景啟動 → 被喚醒後用 `C:\_work\AI_Work\Tools\agy-runs\report.py <step>.json` 讀結果（印 status / duration / denied_actions / response）。
2. `git status` / `git diff` 看它實際改了什麼（不要只信 final report）。
3. 跑 §2.3 gate。失敗把錯誤訊息餵回**同一個** `--conversation`；換 step 開新對話。
4. 審完剩餘修改很小 → 自己改，不再開 agy 回合。

**agy 已知缺陷（P4-E E1～E9b 統計，每步都要在 prompt 裡點名禁止）**

| 類型 | 實例 |
|---|---|
| 測試替身掩蓋 production gap | E7c：`pending_roll_requests` 走 `roll_service.list_requests`，production 的 `CombatAwareRollRepository` 刻意排除 combat rows，agy 用 test-only 子類讓測試綠 |
| 越界改寫既有契約 | E7c 把 20 個 M04-C `_WHEN_TO_USE` 文案與 `wire()` 呈現全改；E4a 加 `is_hostile` override 違反 P4-B 契約、重複 route |
| 壞掉的半成品 | E4b `request_death_save` payload 引用未定義 `event_id`；E9a 不存在的 `status === 'preparing'` 分支 |
| 防禦式寫法 | `getattr` / `Any` / `lru_cache` fallback、try/except 當授權控制流、`"col" in row`、`is None → RuntimeError`、props 全 optional + `if (!x) return` |
| 測試品質 | E8 在每個 test 內 mutate fixture；E9b 用 `'Attack'` / `'1d6'` 補值偽造 |
| 執行穩定度 | quota 429（E4b）、print-timeout（E7c）、stream 中斷（E9b）；大 step 常收不了尾 |

淨效益：backend domain 步驟省時最多（指揮者只做小清理）；碰既有契約面或 UI 的步驟，審核修正量接近重寫一半。

---

## 4. ChatGPT Web 流程

### 4.1 前置

- 對話必須由**有 GitHub connector 且對 repo 有寫入權的帳號**開；換帳號會看到「你沒有權限存取這段對話」。
- 用 **Claude in Chrome**（使用者的真 Chrome，已登入）驅動，不是內建瀏覽器（隔離、未登入，且指揮者不得代替登入）。
- ChatGPT 讀 / 寫 repo 走 GitHub connector：讀檔、建 blob / tree / commit、更新 branch ref。它**跑不了 pytest / vitest / build**，也不會自己看 diff。
- 它可以叫 GitHub Actions 跑測試，但排隊 + checkout + npm ci 遠慢於本機（vitest 2 秒、focused pytest 1 分鐘內），所以驗證留在本機；只有它連續兩回合交同一個失敗、需要自己迭代時才值得讓它走 CI。

### 4.2 送 prompt 的技術細節（全部踩過坑）

composer 是 ProseMirror `div#prompt-textarea`，不是 textarea：

- `form_input` 只會填到一個隱藏 textarea，畫面上什麼都沒有。
- `type` 動作對長文本與換行不可靠。
- **可用方法**：`javascript_tool` 派 paste 事件，再點送出鈕：

```js
const pm = document.querySelector('#prompt-textarea'); pm.focus();
const dt = new DataTransfer(); dt.setData('text/plain', text);
pm.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
await new Promise(r => setTimeout(r, 800));
const btn = document.querySelector('button[data-testid="send-button"], button[aria-label="傳送提示詞"]');
if (btn && !btn.disabled) btn.click();
```

`text` 直接以 JS 字串嵌進呼叫（6～7 KB 沒問題）。內含 `${}` 時不要用 template literal。

- **不要用附件送任務。** 附件（`file_upload` 到 `#upload-files`）能送、它也讀得到，但之後 GitHub 寫入工具會被 OpenAI 擋：「由於 OpenAI 無法確定要求的安全狀態，因此已將此工具調用封鎖」，回合在 timeout 時無聲死亡。P4-E 四個死回合都是這個原因；改貼對話後一回合成功。
- `fetch('http://127.0.0.1:…')` 被 chatgpt.com CSP 擋，不能用本機 HTTP server 傳 prompt。
- 讀回覆：`[...document.querySelectorAll('[data-message-author-role]')]` 取最後一則；`innerText` 若被工具的 cookie / query string 過濾擋住，改截圖。

### 4.3 檢查節奏與死回合判斷

- 使用者要求：**固定間隔（目前 15 分鐘）檢查一次，不要分鐘級輪詢**。session cron 可能不發火（idle 判定），用 `Monitor`（`sleep 900; echo tick` × 2，30 分鐘續一次）當主要喚醒訊號。
- 每次檢查：`git fetch` 看 remote branch → 沒新 commit 就重載頁面看最後一則訊息與 stop button。
- **stop button 會騙人**：backend 回合死了 UI 還顯示執行中。判斷規則：
  - 串流中且送出未滿 30 分鐘 → 不打擾（送訊息得先按 Stop，會丟掉未 commit 的工作）。
  - 超過 30 分鐘無輸出、或重載後回合已結束但沒 push → 送**不呼叫工具的診斷**：「不要呼叫任何工具，只回答：(1) 上回合做到哪 (2) 最後一次工具呼叫是什麼、有無被封鎖、錯誤訊息 (3) 手上有沒有已建好的 blob / tree」。它會秒回，答案決定下一步（被封鎖 → 換送法；時間切斷 → 叫它繼續）。
- 每次檢查後都要給它下一個指示（繼續 / 修列出的失敗 / 下一步），不要只看不說。

### 4.4 ChatGPT 已知缺陷

| 現象 | 原因 | 對策 |
|---|---|---|
| 回合 30 分鐘 timeout、零輸出 | 附件觸發寫入封鎖（見 4.2）；或 step 太大在 `create_blob` 途中被切 | 貼對話；拆 step |
| 回合全部花在讀檔，沒建任何 blob | MANDATORY READING 列了 8 個「read fully」的檔案 + 3 份文件（E10d-1 第一回合） | contract 欄位直接寫進 prompt，reading 只列**要改的檔**；續做時明講「不要再讀 docs/，只在寫入前重讀該檔 HEAD」 |
| 整份檔案被壓成 200 字單行、-991 行 diff | 指揮者為省時叫它「不用重讀、沿用 blobs」，它憑記憶重生檔案 | **永遠不要叫它跳過重讀**；每次寫檔以 HEAD 新鮮讀取為底、最小 diff。已發生時：`npx prettier@3 --no-semi --single-quote --print-width 100 --trailing-comma all` 與本專案手寫風格只差 ~10%，兩側都 prettier 後 diff 可證明語意只有新增 |
| API 層 hack | E10b 在 route 對每筆 roll 查 attack repo 改 `request_type`（N+1，且 REST 與 MCP 對同一 view 給不同值） | 審 diff 時檢查 REST / MCP parity；判定邏輯移到 persistence / domain |
| 錯的測試斷言 | E10b 把 `/detail` 對外人的拒絕硬寫 403（實際 404，E4a 斷言 `{403, 404}`） | 對照既有測試怎麼斷言同一行為 |
| pytest 保留字 | E10c-1 `parametrize` 參數名叫 `request` → collection error | 指揮者直接改名 |
| FINAL REPORT 不照格式 | E10a 只回一行 hash | 不依賴它的 report，自己看 diff；prompt 仍要求五項 |

品質面：**比 agy 高**（E10a 零修改、E10b / E10c-1 各一處），但吞吐低——含死回合平均 45 分鐘一步，agy 8～20 分鐘。

---

## 5. diff 審核 checklist

每個 step 至少看這些，看到就修或退回：

1. **契約對照**：route 路徑 / method / input / view 欄位對 server model；enum 值對；optional 只在 server 允許 None 時。
2. **REST ↔ MCP parity**：同一 view 在 Human route 與 MCP tool 的欄位語意一致（P4-E 教訓：`request_type`）。
3. **秘密由 server 過濾**：Player 的 view / event 不含敵人精確 HP / AC / DC / dm_hints；UI 不顯示 `"?"` 佔位而是省略元素。
4. **沒有越界**：`git show --stat` 的檔案清單對照 prompt 的 Do not touch；既有文案 / 契約沒被改寫。
5. **重用而非複製**：新 helper 是否已有同義既有函式；貼超過 20 行的重複。
6. **防禦式寫法**：§3 / §4 缺陷表。
7. **測試真的在測**：fixture 有沒有被 test-only 子類換掉 production 行為；斷言有沒有對照既有測試；「不該看到」的 actor 有沒有測。
8. **排版**：`awk 'length > 140' <file> | wc -l` 對照改動前；風格與周圍一致（2 空白、單引號、無分號、一 prop 一行）。
9. **locale**：新 copy 兩個 locale 都有（parity test 會抓，但要確認語意不是機翻）。
10. **實作紀錄**：把上述發現寫進「指揮者審核修正」，下一個人才不會再踩。

---

## 6. 選哪個 worker

| 情況 | 建議 |
|---|---|
| backend domain / persistence 小步驟，契約清楚 | agy（快、省 Claude 用量、審核量小） |
| UI 元件、碰既有契約面、雙語 copy | ChatGPT（品質高、越界少）或指揮者自己做 |
| 純 copy / guide 文案、closeout 文件、E2E 關門 | 指揮者自己（contract-bearing、需要跑 Docker E2E） |
| 使用者在意時間 | agy 為主；ChatGPT 每步預留兩回合 |
| 使用者在意審核成本 | ChatGPT 為主 |

指揮者自己做的判準：剩餘修改幾行、單一檔案、不需重新理解脈絡 → 直接改；否則退回 worker。

---

## 7. 接手流程（新指揮者 session）

1. 讀 `AGENTS.md` → `PROJECT_BRIEF.md` → 本檔 → 當前 Subphase 的 `實作紀錄.md`（步驟表 + 最後一段紀錄）。
2. `git fetch` + `git log origin/<branch> --oneline -5`，確認 remote 與本機一致；有未審的 worker commit 先走 §2.3 gate。
3. 看 `C:\_work\AI_Work\Tools\agy-runs\` 最新的 prompt 檔，知道上一步送了什麼。
4. ChatGPT 對話 URL 與帳號在指揮者 memory（`chatgpt-worker-workflow`）；agy conversation id 遺失不影響，開新對話讀實作紀錄即可。
5. 依 §4.3 節奏繼續。
