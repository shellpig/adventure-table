# B5b — Runtime CRUD 與 Quick Add UI

## Scope

- Campaign Changes 實作 Scene/NPC/Item/Quest/Fact/Secret/other create/edit/archive。
- Human DM Quick Add：NPC 只需 Name、Fact 只需文字、Scene 可只需 Name或Description；typed fields 只呈現契約支援者。
- visibility、character recipients、needs_review、provenance 可正確檢視／編輯；非法組合在 client/server error 中可理解呈現。

## 契約與輸入

- 依賴 B5a；P6 規格 P6-B、設計 B.1/B.4。

## 驗收

- component tests 覆蓋最小 quick add、typed edits、character-only recipients、archive、conflict refresh。
- zh-TW/en、全 web unit、build 通過。

## 完成紀錄

- **起始**：2026-09-21；agy 同一 conversation `f246c464-b419-4582-9290-7e04d14a461b` 三回合實作與修正，總計約 19 分鐘；prompt 位於 `C:/_work/AI_Work/Tools/agy-runs/agy-p6b-B5b*.prompt.txt`。
- **交付**：Campaign Changes 支援 Scene／NPC／Item／Quest／Fact／Secret／Other 建立、編輯、封存；Quick Add 最小欄位、typed NPC／Item／Other state、character recipients、needs_review、provenance 與 zh-TW／en 顯示／驗證皆接線。Hazard 僅可顯示與封存，不進 B5b 編輯序列化器。
- **指揮者審核修正**：三輪完整審查收斂封存取消後 pending 卡死、Hazard 誤顯示 Edit、typed state 未顯示、conflict reload 失敗被吞、optional result bag／非空斷言、頁面過度集中與重複 loader；再以 create/edit discriminated union 封死 Hazard edit path，並區分 mutation 失敗與「寫入已成功但 reload 失敗」，後者關閉表單、保留最後正確清單並要求重新整理，避免以新 idempotency key 盲目重送。
- **測試**（驗證 commit `c47c0ce0`）：`npm test -- --run` → 97 files／612 tests passed；`npm run build` → passed；`..\..\.venv\Scripts\python.exe -m pytest tests/test_code_quality_gate.py -q -n 0` → 2 passed；`git diff --check` 通過。既有 Vite dynamic-import／chunk-size warning 不影響輸出；正式 browser E2E 依步驟留在 B6。
- **未解問題／下一步**：B5b 無未解；下一步 B5c 實作 Adventure Overrides、needs_review 與 Current Context UI。
