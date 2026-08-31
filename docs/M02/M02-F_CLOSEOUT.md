# M02-F Closeout — PHB / SCAG / GoS Localization

日期：2026-08-31
分支：`m02-f-non-srd-localization`
合併：`eb6f534`（`Merge branch 'm02-f-non-srd-localization'`）

## 結論

M02-F 已完成 M01-B / M01-C 導入之非 SRD 內容的 `zh-TW` 覆蓋。四個 enabled pack 的 policy-required 欄位在兩個 supported locale 下皆無缺口：

```text
enabled packs: srd5.1, phb2014, scag, gos
zh-TW required completeness issues: 0
en   required completeness issues: 0
```

## 已完成資料

依 M02-C field policy，共 475 個 non-SRD presentation field 進入 `data/<pack>/locales/zh-TW/`：

| Shard | Entries | Fields |
|---|---:|---:|
| `data/phb2014/locales/zh-TW/backgrounds.json` | 18 | 36 |
| `data/phb2014/locales/zh-TW/origins.json` | 13 | 13 |
| `data/phb2014/locales/zh-TW/roleplay-01.json` | 4 | 104 |
| `data/phb2014/locales/zh-TW/roleplay-02.json` | 4 | 104 |
| `data/phb2014/locales/zh-TW/roleplay-03.json` | 5 | 130 |
| `data/scag/locales/zh-TW/backgrounds.json` | 13 | 30 |
| `data/gos/locales/zh-TW/backgrounds.json` | 4 | 58 |

涵蓋 PHB Backgrounds / Variants、Variant Human 與 PHB subraces、origin features、Background Features、13 個 SCAG Background、4 個 GoS Background 與其 optional flavor table。

`docs/暫用規則資訊/` 的既有繁中譯名作為 priority reference input；與 M02-C glossary 衝突處以 glossary 為準。

## Roleplay suggestion inheritance

Roleplay 繼承只重用 suggestion **presentation**，不改變 identity：

- PHB variant 沿用母 background 的譯文，但保留自己的 suggestion identity。
- SCAG background 沿用 PHB 譯文，identity 仍屬 SCAG。
- SCAG 自帶 explicit roleplay 時不被 inheritance 覆蓋。

「roleplay inheritance != mechanical inheritance」在兩個 locale 下都成立。GoS optional flavor（Fishing Tale / Marine Hardship）翻譯後仍是 optional，未成為 Confirm blocking choice。

## Automated gates

`apps/server/tests/test_m02f_non_srd_localization.py`（10 個 case）：

1. non-SRD required scope completeness。
2. shipped required name / roleplay 必須為繁體中文，不得直接出貨英文原文。
3. PHB variant / SCAG roleplay inheritance 的譯文重用與 identity 保持。
4. SCAG explicit roleplay 不被 inheritance 取代。
5. localization 不改動 canonical content 與 English presentation。
6. 跨 source 同名項目仍以 StableKey 區分，不因譯名 dedupe。
7. 跨 pack 的 SRD reference presentation 仍由 SRD overlay 擁有。
8. GoS optional flavor table 的譯文與 stable identity。
9. background feature grant 具備可在地化的 presentation identity（見下）。

`apps/web/e2e/m02f-non-srd-localization.spec.ts` 為 real-browser spec，**本次未執行**（見下方未竟事項）。

## 修正：background feature 名稱無法在地化

M02-F 期間發現 Review「已解析授予項目」中的 background feature（例如 `Position of Privilege`）在 zh-TW 下仍顯示英文，即使譯文早已存在。

根因不在資料而在 DTO：background feature 是 background entry 的 inline 欄位，沒有自己的 StableKey，grant 只帶 `reference_id`（為 null），前端無從解析。

修正方式：

- `BuilderGrantSummary` 新增 `presentation_field`，background feature 填 `data.feature.name`；`reference_id` 維持「獨立 entry StableKey」的語意不變。
- 前端 presentation hook 支援解析 `name` 以外的 field path。
- 全部 36 個 background（srd5.1 1 / phb2014 18 / scag 13 / gos 4）皆有 gate 保護。

後續回歸：第一版修正曾把額外 field path 併入同一個 batch request，導致 endpoint 整批 404，使**所有** grant 都退回英文。已改為依 field set 分組送出（`groupPresentationRequests`），並加上「額外欄位不得混進不需要它的 reference」的前端測試。

## Runtime / identity 邊界

M02-F 未改變 StableKey、content refs、Builder choice ID、`CharacterBuild`、`CharacterState`、Draft revision 或任何 mechanics。Localization 仍只是 presentation overlay。

## 同批合併的非 localization 工作

依使用者明確決定，以下兩項在本分支一併完成，未另開 M Phase：

- **Build Edit / Correction 按鈕合併**：兩者原本走同一條 code path，只差 version history 標籤。UI 收斂為單一「編輯角色配置」，新版本一律記 `build_edit`；`correction` kind 保留供既有紀錄顯示。
- **角色 Archive / 永久刪除**：`characters.archived_at`（migration `0006_character_archive`）、`GET /api/characters?archived=true`、archive / unarchive / delete 端點、封存後可讀不可寫的守衛（置於既有 locked transaction 內）、Workshop「封存角色」區塊與打字確認的永久刪除。

此決定使本分支的 PR 同時包含 localization 與角色生命週期兩種主題。

## 驗證狀態

合併後於 `main` 重跑：

```text
backend pytest   250 passed
frontend vitest   59 passed (11 files)
tsc --noEmit + vite build  passed
alembic heads    single head 0006_character_archive
```

## M02-F Definition of Done

- [x] `phb2014` / `scag` / `gos` policy-required fields 同時具備 `zh-TW` / `en`。
- [x] 跨 pack reference 在兩語下指向同一 StableKey。
- [x] selector / Review / Sheet 顯示正確 locale 的 source-aware names。
- [x] roleplay suggestion reuse 不造成 mechanical grant pollution。
- [x] Background variant / branch 切換語言後維持相同 active identity。
- [x] 缺 required non-SRD translation 會使 gate 失敗，不 silent fallback。
- [x] `docs/暫用規則資訊/` 作為 reference input，glossary 為最終準則。
- [ ] Docker full stack + Playwright E2E 實際執行；`m02f-non-srd-localization.spec.ts` 自建立起尚未跑過。
- [ ] shard `review_status` 仍為 `draft-human-review-required`，人工術語 review 尚未由專案 owner 正式接受。

## 下一步

```text
M02-G — Localized Search, Errors & Completeness Gates
```

M02-G 尚未開始。上方兩個未打勾項目應在 M02-H（Full M02 Integration & Closeout）前補齊，或在 M02-H 一併驗收。
