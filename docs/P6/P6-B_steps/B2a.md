# B2a — Typed payload、command／view DTO、projection 基礎

## Scope

- 定義 Runtime kind／visibility、typed `state_json` payload，以及 create／update command 與 DM／Player view。
- NPC optional monster refs 只作 reference；Item `holder_ref` 支援 scene／npc／character／party／unknown，不碰 Character inventory。
- projection 型別須能明確省略 `dm_notes` 與未授權內容，不以 optional-everything 或 UI hide 取代 Server filtering。
- 覆蓋 provenance、`needs_review`、revision 與 character recipient 驗證。

## 契約與輸入

- P6 規格「P6-B」；設計 B.1、B.4 與「Shared authority / projection」；測試 B.1、B.4。
- 依賴 B1 schema；參考既有 Adventure typed payload／schemas，但不得複製分叉同義 enum。

## 驗收

- domain model 單元測試覆蓋各 known kind、非法 payload／visibility、DM 與 Player projection shape。
- Player DTO 無 `dm_notes`／dm_only／他角知識欄位或資料。

## 完成紀錄

- **起始**：2026-09-20；agy 2 回合，初回 212 秒，修正回合完成時 conversation 累計 413 秒；conversation `4f274f44-a253-4a84-9d53-3bf81d31e4fd`。
- **交付**：8 種 strict typed payload與 parse/dump、Item holder／NPC ref、Create/Patch/canonical DTO、DM/Player 分離 view、explicit-audience projection、完整 domain tests。
- **指揮者審核修正**：初回的 canonical 同時持有 `state_json`＋`state` 且可矛盾、Create 未驗 raw state、Patch 可修改 kind、projection audience 有不安全預設；退回同對話修正並補測。第二回合後另發現非 dict `state_json` 被靜默替換成空 payload，指揮者改為明確拒絕並補 regression test。
- **測試**：`test_p6b_runtime_schemas.py`＋`test_code_quality_gate.py` 共 16 tests 全綠（pytest exit 0）。
- **驗證 commit**：待本次 B2a commit。
- **未解問題**：Patch 對既有 kind 的 state/minima 與 visibility/recipient 合併驗證由 B2c service 負責；B2b 只保存已驗證資料。
