# M01-N Closeout Checklist

M01-N — Character Sheet HTML Export closeout scope：

- [x] 角色卡上可以叫出 HTML 輸出，輸出範圍由使用者選（`角色配置` / `當前快照`），既有 Character JSON 匯出入口行為未變。兩個 action 並列在同一個 sheet header，彼此獨立。
- [x] 輸出檔自足：不含 `<script>`、不連外部樣式／字型／圖片、不打任何 API。`assertSafeCharacterSheetHtml()` 在每次輸出時檢查 script / 外部 URL / `src=` / `href=` / 表單控制項 / `role="tablist"`，違規即拋錯而非產出壞檔。
- [x] 輸出檔是完整角色卡：三個分頁內容攤平在同一份文件，不靠分頁互動。三段各自保留 `.sheet-content`，分頁列已移除。
- [x] 角色配置不輸出 Current State：目前 HP／臨時 HP／剩餘 Hit Dice／剩餘法術位／剩餘職業資源／狀態／已準備標記／物品欄皆不出現；Max HP、Hit Dice 總量、法術位總格數、資源容量照常出現。
- [x] 角色配置仍輸出完整法術存取清單但不標記已準備；`.prepared-limit` 改寫為準備上限（快照為 `已準備 N / M`）。
- [x] 角色配置仍輸出 AC，並在文件內以 `export-ac-note` 註明計算基準包含目前裝備。
- [x] 當前快照輸出角色卡目前顯示的全部內容，含上述所有 Current State 與物品欄。
- [x] 兩份輸出一眼可分辨：檔名為 `<角色名>-v<版本>-<build|snapshot>.html`，文件開頭標明範圍與 Build Version，當前快照另標輸出時間。
- [x] 輸出檔可列印：`@media print` 以 A4 版面、白底、`break-inside: avoid` 輸出，法術三張一排、物品兩張一排。
- [x] 語言凍結在輸出當下的 locale，`zh-TW` / `en` 皆可正確輸出，輸出檔本身不提供語言切換。
- [x] 沒有任何 Import 路徑接受這個格式：`ImportCharacterDialog` 維持 `accept="application/json,.json"`，server 端無 HTML import 路徑。
- [x] 只輸出請求者本來就看得到的資料：輸出取自 Character Sheet 已持有的 query cache，透過 `createFrozenExportQueryClient()` 的 `staleTime: Infinity` 私有 cache 渲染，不因輸出而新增任何 API 讀取。
- [x] 單機版行為與網頁版一致：本 Subphase 未動任何 `apps/server` 檔案，standalone boundary 與 import boundary gate 未受影響。

## Verification evidence

2026-09-06 最終驗證，分支 `m01-n-character-sheet-html-export` HEAD `60778a5`：

```text
cd apps/web
npm test -- --run
31 test files / 158 tests passed

npm run build
tsc --noEmit clean；vite build 成功

npm run test:e2e:docker
99 passed, 3 skipped (6.7m)；xge-less 第二輪 7 passed

docker compose config
exit 0
```

Playwright 走 `npm run test:e2e:docker`，對容器化的 server / web 執行。3 個 skip 中的 2 個是 `m03c-character-import.spec.ts` 保留給 xge-less 第二輪的案例，該輪已通過；剩下 1 個為既有的 `KI-M01J-001`（`test.fixme()`），與 M01-N 無關。`KI-P1D-001` 本輪未重現，但不以單次通過推論根因已修復。

Backend 於 `f74e482` 執行全套 `pytest`：966 collected、exit 0、2 skipped。`60778a5` 只改 `apps/web/src/features/character-sheet/`，未觸及 backend、DB 或打包相依，故未重跑。

M01-N 相關前端覆蓋為 5 個測試檔共 32 個測試：

| 檔案 | 測試數 | 對應測試指南 |
|---|---|---|
| `apps/web/src/features/character-sheet/CharacterSheetHtmlExport.test.ts` | 15 | 9.2 / 9.3 |
| `apps/web/src/features/character-sheet/CharacterSheetHtmlExport.static.test.ts` | 5 | 9.3 |
| `apps/web/src/features/character-sheet/CharacterSheetHtmlExport.build-copy.test.ts` | 1 | 9.2 |
| `apps/web/src/features/character-sheet/CharacterSheetHtmlExportButton.test.tsx` | 3 | 9.2 |
| `apps/web/src/features/character-io/ExportCharacterButton.test.tsx` | 8 | 9.2 |

前四個檔案為 M01-N 專屬（24 個測試）；`ExportCharacterButton.test.tsx` 沿用 M03-B 既有檔案，其中 M01-N 新增的是 HTML action 只掛在 Character Sheet placement 的那組斷言，不另建第二套 harness。

瀏覽器覆蓋為 `apps/web/e2e/m01n-character-sheet-html-export.spec.ts`（2 條真後端 flow：兩種範圍各產出一份檔案、HTML 輸出與既有 JSON 輸出彼此獨立）。

## M01-N Closeout Evidence

```text
Scope / expected inventory: 兩種輸出範圍 + A4 列印樣式 + 匯出物品閱讀順序
Content / schema validation: N/A — 不新增內容、不改 schema
Domain legality / calculations: N/A — 不改 Python domain
Persistence / versioning: N/A — 輸出不寫入任何狀態
Localization completeness: PASS（`m01nCharacterSheetExportCopy.ts` 17 條 copy × zh-TW / en 全覆蓋；實際輸出檔雙語確認無混語）
Runtime without docs: N/A — 不從 docs materialize
Focused API integration: N/A — 不新增 endpoint、不改 DTO
Focused Playwright: 2 / 2；合併回 main 前全套 E2E 99 passed / 3 skipped
Restart persistence: N/A — 無持久狀態
Human smoke: PASS（使用者於 2026-09-06 確認：離線雙擊開啟、列印預覽、zh-TW / en 各一份）
M03 standalone compatibility: PASS（靜態 — 零 `apps/server` 改動、無新 server 相依、import boundary 未變）
Downstream P compatibility: N/A — 不碰 shared Character contract
Existing focused regression: PASS（前端 158、build、docker compose config、全套 backend pytest）
Known manual/deferred effects: PDF 產生交給瀏覽器列印；不做歷史版本輸出、批次輸出與輸出檔內互動
```

## 關門過程中修正的問題

1. **索引配對會靜默標錯數字。** `applyBuildOnlyProjection()` 原本以 DOM 出現順序把 `.slot-card` / `.resource-list > div` / `.prepared-limit` / `.condition-chip` 對應到投影資料。角色卡日後只要改變這些清單的順序或數量，輸出就會把錯的數值配到錯的列，而且不會有任何錯誤訊號。已改為 `pairCharacterSheetIndexRows()`：以 `data-sheet-index-key` 做穩定鍵配對，key 缺漏、重複、對不上或有資料項沒配到列時一律拋錯，讓輸出失敗而不是產出錯的角色卡。

2. **角色配置的法術位面板副標仍寫「伺服器狀態」。** build-only 輸出裡沒有任何 server state，那個副標會誤導讀者。已改為「容量」。

3. **匯出渲染器與頁面資料存取混在同一個檔案。** `CharacterSheetPage.tsx` 同時承擔 query 取數與 861 行的呈現，匯出卻只需要後者。已抽出 `CharacterSheetView.tsx`（純呈現，861 行），`CharacterSheetPage.tsx` 縮為 79 行的資料存取層並 re-export view；靜態測試要求 view 不得出現 `getCharacterSheet` / `listContent` / `patchCharacterState` / `fetch`。

4. **列印排版浪費紙。** 法術原本兩張一排、物品一張一排，一個中等角色會印成好幾頁。已改為列印時法術三張一排、物品兩張一排。

5. **匯出的物品欄沒有閱讀順序。** 已裝備、未裝備的武器護甲與雜物混在一起。已在匯出 transform 內排序為「已裝備 → 其餘武器／護甲 → 其他」，同組維持原順序；排序只作用於匯出檔，真人角色卡順序不變。

## Boundary

- 輸出是單向的。HTML 永遠不是第二種序列化格式，機器往返一律走 Character JSON。
- 不做 Build Version 之外的歷史版本輸出、不做多角色批次輸出、不做 PDF 產生（交給瀏覽器列印）。
- 不做輸出檔內的互動（搜尋、分頁、折疊）。三個分頁攤平為同一份文件是刻意選擇：使用者於 2026-09-06 檢視列印結果後確認維持攤平，不改成 CSS 分頁。
- 不因為「順便」而輸出角色卡目前沒有呈現的資料。
- 不新增 server endpoint、不改 `CharacterSheetDTO`、不改 Character JSON schema。
- 物品閱讀順序的「裝備類」判定為 `rules.equipment_category.index` 等於 `weapon` 或 `armor`（盾牌在 SRD 屬 `armor`），其餘歸「其他」；分類讀不到的物品落到最後一組，不讓輸出失敗。

## 已知限制

- **匯出產出的 HTML 沒有行為測試。** 測試指南 9.2 第 1～6 項目前由三種間接證據承擔：`projectCharacterSheetForExport()` 的投影單元測試、對 exporter 原始碼字串的 `toContain` 斷言，以及 E2E 的「有產生檔案」斷言。`createCharacterSheetHtmlExport()` 與 `applyBuildOnlyProjection()` 對真實 render 產出的 HTML 沒有任何斷言。實務上的安全網是上述第 1 項修正帶來的 fail-loud 配對加上 E2E 下載斷言——配對錯誤會讓輸出拋錯、E2E 隨即失敗——但那與「斷言輸出內容正確」不是同一件事。補這層測試留給後續 Subphase。
- **`prepared_limit` 路徑不在 CI 覆蓋內。** P0 E2E fixture 的 `spellcasting[].prepared_limit` 為 `null`，因此 `.prepared-limit` 的改寫在自動測試中一次都不會執行。該路徑已於 2026-09-06 以攔截 sheet API 注入 `prepared_limit` 的方式人工驗證：角色配置輸出「準備上限 5」、當前快照輸出「已準備 3 / 5」。要進 CI 需要一個帶 prepared limit 的 fixture。
- **`INEFFECTIVE_DYNAMIC_IMPORT` build 警告仍在。** `CharacterSheetHtmlExportButton` 以動態 import 取得 `CharacterSheetView`，但 `CharacterSheetPage` 必然靜態 import 同一個模組，因此不會分出獨立 chunk。不影響契約（`react-dom/server` 未進 runtime，靜態測試把關），但動態 import 目前沒有 bundle 上的效果。
- **輸出檔留有 `role="tabpanel"` 與 `aria-label`。** 三段 `.sheet-content` 沿用角色卡的 markup，分頁列已移除但 panel role 還在，形成沒有 tablist 的孤立 tabpanel。`assertSafeCharacterSheetHtml()` 只擋 `role="tablist"`。純語意瑕疵，不影響呈現或列印。

## Handoff

M01-N 已完成並關門。M01 **不是** full closeout；A～N 是目前已交付的 baseline，下一個新的 M01 工作從 **M01-O** 起編號。

下一步是 **P2-A — Room Foundation & Web Entry**。

後續 Subphase 直接繼承 M01-N 的兩項 substrate，不得再造第二套：

- **匯出列的穩定鍵配對**：任何要把投影資料寫回既有角色卡 markup 的轉換，一律以 `data-sheet-index-key` 經 `pairCharacterSheetIndexRows()` 配對，不用 DOM 位置；對不上就讓輸出失敗，不要 fail-open。
- **匯出渲染器與頁面資料存取分離**：`CharacterSheetView` 是純呈現元件，任何 API 取數留在 `CharacterSheetPage`。匯出只吃已持有的 query cache，不得為了輸出而新增讀取。

M01-N 未新增任何 server 相依，P2 引入多人層時不需要為本 Subphase 調整 standalone import boundary gate。
