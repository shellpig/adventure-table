# 暫時分析交接：M01-K E2E timeout 與 State CAS 修復的關係

日期：2026-09-09

分析基線：`main` / `5e4e672`

用途：交給其他 AI 繼續調查。這是暫時調查筆記，不取代 `已知問題.md`、Phase 契約或驗收文件；以下不是已確認的根因，也不是修復完成聲明。

## 1. 背景與問題

先前發現 Standalone Character State 並行 PATCH 會 lost update，接著又發現 Level Up reconciliation 可覆蓋已提交的 State PATCH。修復分支 `fix/character-state-cas` 最後驗證版本為 `344fd35f8fa62468b03aa79d5c84cc0fd704c36c`，已經由 `e07aec6` 合併回 main。

該次驗證包含 static review、40 個 focused tests，以及 SQLite 預設 DELETE journal 下的受控 Standalone HTTP interleaving。未跑完整 E2E、真 PostgreSQL 或 frozen build。因此不能由當時的通過結論推論「修復後所有 E2E 都應正常」。

之後 P3-A 關門期間，`已知問題.md` 的 KI-P1D-001 新增 M01-K 失敗證據。使用者希望了解它是否與前述修復有關。

## 2. 本次實際做了什麼

- 讀取最新 `已知問題.md` 與最近提交。
- 直接讀取下列 GitHub Actions 的 failed-job log，沒有只依文件摘要推論。
- 追查 M01-K spec、Builder UI 存檔、SearchableSelect、Draft persistence，以及 CAS 修復 diff。
- 沒有修改產品程式或測試，沒有本機重跑 E2E，沒有量測單次 PATCH latency，也沒有取得 browser trace 的 request/response 時序。

## 3. 最重要的發現：兩種 timeout 被混為一談

直接檢查的 CI：

- [main / run 34295347049](https://github.com/shellpig/adventure-table/actions/runs/34295347049)
- [P3-A / run 34295350916](https://github.com/shellpig/adventure-table/actions/runs/34295350916)

兩邊都以 `--repeat-each=3` 跑 `e2e/m01k-phb-feats-and-spells.spec.ts`。

`M01-K keeps two Elemental Adept acquisitions and a PHB spellbook spell`（當時 spec:392）的三次失敗都出現：

```text
Test timeout of 30000ms exceeded
```

其中後兩次同時顯示：

```text
Expected: > 51
Received:   51
Call Log:
  - Test timeout of 30000ms exceeded
```

stack 指向：

```text
waitForDraftRevision
→ chooseFirstEnabled
→ fillEmptyComboboxes
→ finishAndReview（當時 spec:278，Equipment 步驟）
→ test（當時 spec:415）
```

**這些 log 證明整支測試碰到 30 秒期限，不足以證明最後一次存檔已獨立等待 5 秒仍未完成。** `Received: 51` 只表示截止時尚未觀察到下一版。請不要把當前 assertion 的位置直接當成根因。

同一份 log 另有 `Timeout: 5000ms`，但那是其他失敗（例如同名角色卡片數量斷言），必須按 test 區塊分開讀，不能混用。

目前 `已知問題.md` 把這批證據歸入「revision 確實等滿 5 秒仍不推進」，並認定已取得舊問題的穩定重現；這個歸因需要重新確認。**這不否定舊的 m01e／m01m 案例，只表示新增 m01k 案例尚不能據此判為同一根因。**

## 4. 程式路徑：Draft revision 與 State revision 是兩套東西

### 創角選項存檔

```text
SearchableSelect.choose → onChange
→ CharacterBuilderPage 的 save mutation
→ patchBuilderDraft(draftId, view.draft.revision, payload)
→ Room Builder PATCH / CharacterBuilderService.patch_draft
→ character_build_drafts.revision
→ onSuccess 更新 ['builder-draft', draftId] query cache
→ UI 顯示新 Draft revision
```

入口：

- `apps/web/src/components/SearchableSelect.tsx`：`choose`、`onClick`、搜尋／blur 行為。
- `apps/web/src/features/character-builder/CharacterBuilderPage.tsx`：`const save = useMutation`。
- `apps/server/app/api/rooms/character_builder.py`：`patch_builder_draft`。
- `apps/server/app/domain/character_builder/service.py`：`patch_draft`。
- `apps/server/app/persistence/builder_drafts.py`：以 expected revision 條件更新 Draft 並將 revision 加一。

### 前面修的 Character Current State

```text
PATCH Character State
→ mutate_state_against_version
→ character_states.state_revision CAS / retry

Level Up / Build Edit Confirm
→ create_build_version_from_builder_draft
→ reconciliation + State revision CAS / 整個交易 rollback/retry
```

`:392` 報錯時仍在建立 Wizard 8 的草稿，尚未進入 Create Confirm，更不是 Level Up Confirm。前述 State CAS 並非該次選項存檔的直接路徑。

比較 `3c9de65..e07aec6`，以下範圍沒有 diff：

- `apps/server/app/persistence/builder_drafts.py`
- `apps/server/app/domain/character_builder/service.py`
- `apps/web/src`
- `apps/web/e2e/m01k-phb-feats-and-spells.spec.ts`

這支持「沒有直接修改到失敗步驟」，**但仍不能憑此排除間接效能、環境或資料變化**。

## 5. 為什麼優先查整支測試的時間預算

該 spec 會建立 Wizard 8、逐級選擇職業、取得兩次 Elemental Adept、選 Fire／Cold、加入 Chromatic Orb，接著掃描並補滿其他選項與法術。失敗時已走到 revision 51，表示前面已完成大量存檔。

`chooseFirstEnabled` 會逐一讀取選項文字；`fillEmptyComboboxes` 反覆掃描畫面中的 combobox；每次選擇後都等待 Draft revision 前進。這些操作可能累積成整體耗時，但目前沒有逐步量測，不應把其中任何一個 helper 直接定為根因。

`playwright.config.ts` 與本 spec 未設定較長的 test timeout；CI log 明確呈現 30 秒整體期限。

## 6. 不要混在一起的其他失敗

`M01-K takes a PHB feat at an ASI during Level Up`（當時 spec:342）：

- repeat 執行時，固定角色名稱 `M01-K Level Up Tough` 搭配 `.workshop-card.filter({ hasText: name })`，但斷言要求只有一張卡。
- log 實際出現同名卡片多於一張的 `toHaveCount` 失敗。這是獨立的測試資料／定位隔離問題，不能當成 Draft revision 卡住。
- 已知問題另記錄全套執行時 `toHaveURL`／`readSheet` timeout；本次尚未逐一調閱那些 run，不對其根因或與 CAS 的關係下結論。

## 7. main／P3-A 對照能與不能證明什麼

- 同樣失敗出現在 P3-A 合併前的 main，支持「P3-A 不是必要觸發因素」。
- **兩個對照版本都已包含 CAS 修復。** 所以這不是 CAS 前／後對照，不能拿來排除 CAS 修復的影響。
- 「CAS 修復後觀察到」也不等於「CAS 引入」。要驗證因果，需選 CAS 前後版本，固定 runner、資料初始化、測試內容與執行參數。

## 8. 建議下一位 AI 的調查順序

優先區分三種可檢驗的假設：

1. **整體時間預算耗盡**：前面步驟累計接近 30 秒，最後一個 request／assertion 被整體期限截斷；單次存檔未必異常。
2. **Draft PATCH 發出但失敗／延遲**：應看到 request、非成功 response 或長 latency，並對應到 UI error／pending。
3. **選擇未真正觸發存檔或選到了不改變資料的操作**：應看到 click 後沒有預期 PATCH；需確認 option identity、disabled、現有值與前端 callback。

先分析現有 trace／artifact（若有），記錄：測試開始、選項 click、PATCH 發出／完成、response revision、UI revision、timeout 的時間。缺資料才設計隔離環境下的最小重現。

暫不直接提高 timeout 當成修復，也不要把此案例加入 fixme 或沿用舊 KI 豁免。先確定是哪一種 deadline、哪段流程耗時，再決定測試是否需要拆分／明確驅動，或產品存檔路徑是否真的有問題。

若重跑：

- 遵守 Windows Docker E2E 路徑；不使用 Windows Playwright 託管 Vite。
- 使用可拋棄的測試 DB。既有 global setup 會清空資料，不能直接對有使用者角色的 DB 開啟 destructive reset。
- 確認 backend 與 frontend 都是目標版本；既有 wrapper 只明確 rebuild web。
- 單獨定位 `keeps two Elemental Adept acquisitions` 可避免把 Level Up 同名卡片失敗混進訊號，但單跑與全套的負載不同，記錄這項限制。
- 本文件僅交接分析，不構成修改授權；是否修改依使用者下一步要求決定。

## 9. 目前結論

**尚未確認根因。已確認的關鍵差異是：新增 m01k 證據顯示整體 30 秒 test timeout，不能據此宣稱單次 Draft revision 等滿 5 秒仍不推進。**

優先追時間預算與 request 時序；不要先假定是 State CAS 回歸，也不要先把它歸入既有 autosave 競態。
