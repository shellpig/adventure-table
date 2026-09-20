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

- 待補。
