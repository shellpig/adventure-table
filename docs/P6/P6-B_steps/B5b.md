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

- 待補。
