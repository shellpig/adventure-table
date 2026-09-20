# A4b — web：Adventure editor

## Scope

- `apps/web/src/features/rooms/AdventureEditorPage.tsx`：definition 欄位（name／summary）編輯；entries 列表（依 `sort_order`，section 子項縮排）；新增 entry：選 kind → 顯示該 kind 最小欄位（title／body／visibility 通用；`suggested_check` ability／skill／DC；`monster_ref` template ref；`map` caption）；編輯／刪除／上下移（reorder）；entry 圖片：上傳 image asset（`dm_only` 或 `room`）並 attach 到 entry（role image／map），顯示縮圖經 `roomAssetContentUrl`；finalize／archive 按鈕沿用 A4a client；archived 時全部唯讀。
- `adventuresCopy.ts` 追加 editor copy 兩 locale。
- Vitest：`AdventureEditorPage.test.tsx`（entry CRUD 呼叫正確 client、kind 欄位切換、invalid payload 400 顯示、archived 唯讀、asset upload→attach 順序）。

## 對應契約

實作規格 P6-A「Adventure entry 至少可表達…」「Human UI…可建立、瀏覽、編輯」；設計 §A.2、「REST / UI surface ▸ Adventure editor」。

## 前置

A4a clients／routing；A1b asset routes。

## 驗收

- `npm test -- --run`、`npm run build`（cwd `apps/web`）通過。

## 紀錄

（派工後補）
