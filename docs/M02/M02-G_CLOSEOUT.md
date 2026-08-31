# M02-G Closeout — Localized Search, Errors & Completeness Gates

日期：2026-08-31
分支：`m02-g-localized-search-errors-gates`

## 結論

M02-G 已把 localization 從「畫面會切語言」推進到「搜尋、排序、錯誤訊息跟著 locale，而且缺翻譯會讓測試紅」。四個 enabled pack 在兩個 supported locale 下的 policy-required completeness 仍為 0 issues，並新增 orphan / duplicate / unsupported-locale 三道結構 gate。

## G.1 Localized search

`SearchableSelect` 在選項 value 具備 StableKey 形狀時，額外取得另一個 supported locale 的 presentation 名稱，作為隱藏 search alias：

- 繁中模式輸入 `fireball` 命中「火球術」，清單仍只顯示繁中。
- English 模式輸入「精靈」命中 `Elf`，清單仍只顯示英文。
- alias 只進搜尋比對，不進任何顯示字串。

跨 locale 的 alias 請求是 opt-in（`useContentPresentations(..., { includeSearchAliases: true })`），只有 `SearchableSelect` 開啟，其餘畫面維持單一 locale 的請求量。

## G.2 Locale-aware sorting

`sortSearchOptions` 依目前 locale 的 `Intl.Collator`（`sensitivity: 'base'`、`numeric: true`）排序 display name，同名時以 StableKey 決勝，確保順序穩定。

純數值選單（標準陣列）維持設定順序，不被字母／數值排序打亂。

## G.3 User-visible errors

`apps/web/src/i18n/systemMessages.ts` 以語言中立的 machine code 對應在地化字串；code 與 path 不因語言改變。

- Builder issue：server 送出的 **43 個 code 全部**具備 `zh-TW` / `en` 對應。
- Request error：`not_found` / `revision_conflict` / `validation_error` / `invalid_request`，另有 404 / 409 的 status fallback。
- 訊息以 getter 形式掛在 payload 上，於 render 時解析 locale，因此切換語言會即時更新已快取的 React Query 資料，不觸發 refetch，也不改動 Draft。
- `zh-TW` 的 fallback 一律為純中文，不串接 server 的英文原文。

## G.4 Completeness gate

```text
enabled packs: srd5.1, phb2014, scag, gos
locales:       zh-TW, en
required completeness issues: 0
```

缺任一 required translation 會使 `test_enabled_pack_required_localization_is_complete` 失敗，並輸出 pack / StableKey / field / locale。

## G.5 Orphan / duplicate gates

`load_content_localization_catalog` 現在強制：

- overlay 只能使用 supported locale 的檔案或目錄。
- overlay 的 StableKey 必須存在於 registry。
- overlay 的 field path 必須存在於 canonical payload。
- 同一 locale / StableKey / field 只能定義一次；**即使兩處值完全相同也視為衝突**，避免 shard 擁有權含糊。

`read_localization_path` 抽為公開 helper，runtime resolver 與 overlay 驗證共用同一份 path 語意，不再有兩套實作。

### 一併修掉的既有資料缺口

新的 field-path gate 抓到 `data/srd5.1/locales/zh-TW/core.json` 為 `srd5.1:background:acolyte` 保留了 26 個 `data.roleplay_suggestions.*` 譯文，但正規化後的 SRD Acolyte 並沒有 `roleplay_suggestions`（該 presentation 由 `phb2014` 擁有）。這 26 筆已刪除；`data/phb2014/locales/zh-TW/roleplay-01.json` 本來就擁有完全相同的 26 筆，沒有任何譯文遺失。`test_srd_acolyte_roleplay_orphan_is_not_exempted` 鎖住這個 key 不再享有豁免。

## G.6 Future visibility guard

`test_future_visibility_requires_every_supported_locale` 以 fixture 證明：把某個 canonical field 的 policy 改成 required 後，只有英文會讓 completeness 失敗，補上 `zh-TW` 才通過。這證明 M02 closeout 後「首次 expose 舊 content」不會無聲進入單語 UI。

## 驗證狀態

```text
backend pytest              257 passed
frontend vitest              69 passed (12 files)
tsc --noEmit                 passed
Playwright（serial, 乾淨 DB） 30 passed (30)
```

Playwright 於本機獨立資料庫（`adventure_table_e2e`）與獨立 API process 上執行，未使用開發用資料庫。

新增 `apps/web/e2e/m02g-search-sort.spec.ts`（4 個 case）覆蓋 G.1 別名搜尋雙向、G.2 兩個 locale 的排序差異、以及數值選單保序。

`apps/web/e2e/p1h-high-level.spec.ts` 的法術填選改為挑選環數最低的可選項。原本的「選第一個可選項」依賴選項位置，在 G.2 導入 locale 排序後會選出無法由合法逐級習得流程產生的法術書。

## 已知未竟事項

- **Disabled reason 在 `zh-TW` 沒有具體原因。** Server 目前以自由英文送出 `disabled_reason`，沒有 machine code，因此前端寫好的 `DISABLED_REASON_MESSAGES` 與其 `code + params` formatter 在 runtime 走不到，繁中一律顯示通用句。依使用者決定，M02-G 接受此狀態關門，改由 M02-H 補完 server 的 structured message 契約；詳見 `docs/M02/M02-H_TODO.md`。
- **Playwright 高並行下不穩定。** 以 10 workers 對單一 process 的本機後端執行時，`m02f` / `p1g` / `p1h` 會間歇性在「Confirm & Create Character 仍為 disabled」逾時；同樣的 spec 單獨執行或 `--workers=1` 全部通過。M02-G 讓每個 selector 的 presentation 請求量加倍，可能加劇此現象。應在 M02-H 以 CI 的 docker 全端組態確認，必要時限制 worker 數。
- **Locale shard 的 `review_status` 仍為 `draft-human-review-required`**（自 M02-E / M02-F 承接），人工術語 review 尚未由專案 owner 正式接受。
- **G.1 / G.2 / G.3 的人工瀏覽器驗收尚未由使用者執行**，自動化證據已具備。

## M02-G Definition of Done

- [x] rules-content selector 以目前 locale 顯示並搜尋，另一 locale 名稱可作 alias。
- [x] alias 不改變顯示語言。
- [x] 名稱排序依目前 locale display presentation。
- [x] 數值選單維持設定順序。
- [x] validation / request error 具備穩定且語言中立的 code。
- [x] server 送出的每個 builder issue code 都有兩個 locale 的在地化字串。
- [x] `zh-TW` fallback 不含英文原文。
- [x] 切換語言即時更新已顯示的錯誤，不觸發 Draft mutation。
- [x] policy × enabled packs × locales 的 completeness gate 會讓 CI 失敗。
- [x] orphan StableKey / orphan field path / duplicate definition / unsupported locale 皆可偵測。
- [x] future visibility guard 證明首次 expose 舊 content 需雙語。
- [ ] disabled reason 在 `zh-TW` 呈現具體原因（延至 M02-H）。
- [ ] 人工瀏覽器驗收（G.1 / G.2 / G.3）。

## 下一步

```text
M02-H — Full M02 Integration & Closeout
```

M02-H 需一併處理上方未打勾項目、M02-F 承接的 shard review status，以及 SRD CC BY 4.0 translation/adaptation NOTICE 的 closeout。
