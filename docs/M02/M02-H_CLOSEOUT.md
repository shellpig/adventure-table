# M02-H Closeout — Full M02 Integration & Closeout

日期：2026-08-31
分支：`m02-h-full-integration-closeout`（已直線帶入 `main`，head `d300573` + 本次 doc-sync commit）

## 結論

M02 關門。網站現在是 `zh-TW` / `en` 兩個純語言模式：同一份 rules identity，兩套 presentation，切換不重載、不動 Draft / Build / Current State。M02-G 留下的最後一個語言缺口（disabled reason 只有英文自由文字、繁中只能顯示通用句）已補完；四個 enabled pack 在兩個 locale 下的 policy-required completeness 仍為 0 issues。

下一步固定為 **M01-D — VGM Race Expansion**。

---

## H.0 補完 M02-G 遺留的 structured message 契約

`docs/M02/M02-H_TODO.md` 記錄的契約已全部實作：

- `BuilderIssue` 新增 `message_params`。
- `BuilderChoice` / `BuilderChoiceOption` 新增 `disabled_reason_code` 與 `disabled_reason_params`（`apps/server/app/domain/character_builder/schemas.py:183`、`:201`、`:303`）。
- Multiclass 與 Feat prerequisite 改以語言中立的 ability + minimum score 結構表示；content identity 一律走 StableKey（`class_ref` / `feat_ref`）。
- Nested choice、ASI prerequisite / cap / branch guard 使用穩定的 disabled-reason code。
- Compiler 的 effective-ability 第二輪 eligibility pass 會同步重算 code + params，不再只覆寫英文 prose。
- 前端 `apps/web/src/i18n/systemMessages.ts` 直接消費 `code + params` 格式化，不 regex-match server 英文句子；`zh-TW` 未知 code 仍走純中文 fallback。

繁中 disabled 選項因此顯示具體原因，而不是 M02-G 當時的單一通用句。

---

## H.1～H.4 全站雙語 / Draft-safe / state 驗收

自動化覆蓋落在兩個新 spec：

- `apps/web/e2e/m02h-bilingual-site-smoke.spec.ts`：`zh-TW` / `en` 各跑一次 desktop route crawl（Landing / Workshop / Builder 全 step / Review / Character Sheet / Version History），檢查在地化 chrome 與水平 overflow。
- `apps/web/e2e/m02h-localization-state-integrity.spec.ts`（4 個 case）：
  - `en → zh-TW → reload` 的完整 Create → Confirm → Sheet，不產生 domain mutation。
  - `zh-TW → en → reload` 反向流程。
  - 具備 race / subrace / background / class progression / spell / equipment / roleplay 自由文字的 Draft 連切四次語言，revision 不增、payload 與 selected StableKeys 不變、使用者文字不變。
  - Character Sheet 的 HP / Temp HP / condition / resource / prepared spell / inventory live state 跨多次切換與 reload 不變。

後端契約鎖在 `apps/server/tests/test_m02h_structured_messages.py`（3 case）與 `test_m02h_message_contract_static.py`（2 case）。

---

## H.5 / H.9 Content completeness 與 translation evidence

`zh-TW` overlay 實際覆蓋（自 `data/<pack>/locales/zh-TW/` 直接統計）：

| Pack | StableKeys | Presentation fields | Shards |
|---|---|---|---|
| `srd5.1` | 1,635 | 3,391 | 64 |
| `phb2014` | 31 | 387 | 5 |
| `scag` | 13 | 30 | 1 |
| `gos` | 4 | 58 | 1 |

非 SRD 合計 475 個 field，與 M02-F closeout 的數字一致。`srd5.1` 的 3,391 個 field 含 M02-D 的 names / labels / structured text 與 M02-E 的 spell / feature / condition `data.desc.*`。

Translation method（`srd5.1` 64 個 shard 的 metadata）：

```text
canonical-srd-translation-with-m02c-glossary            55
machine-assisted-draft-with-stablekey-human-overrides    7
machine-assisted-draft-readable-fallback                 2
```

Review status：

```text
srd5.1   human-reviewed 1 / human-review-ready 54 / draft-human-review-required 9
phb2014  draft-human-review-required 5
scag     draft-human-review-required 1
gos      draft-human-review-required 1
```

Completeness gate（policy × enabled packs × locales）：

```text
enabled packs: srd5.1, phb2014, scag, gos
locales:       zh-TW, en
required completeness issues: 0
```

無 required missing translation 被列為 accepted exception。仍未翻譯的是 policy 判定為目前非 user-visible 的欄位（item / background long-form 的大部分），以及本 repo 根本未收錄的 Monster / Beast 素材。

---

## H.6 Regression 證據

本機於 2026-08-31 實跑：

```text
backend pytest            262 passed（exit 0）
frontend vitest            71 passed（12 files）
tsc --noEmit               passed
alembic upgrade head       passed（fresh SQLite）
Playwright（--workers=1）   37 passed（37）
```

Playwright 於獨立 SQLite 資料庫與獨立 uvicorn process 上執行，先套 `alembic upgrade head` 再 `app.scripts.seed_p0_fighter_wizard`，未使用開發用資料庫。P0 / P1 / M01-A～C 的既有 spec 全數包含在這 37 個 case 內，核心能力無 regression。

---

## H.8 Documentation closeout

同步的專案 SSOT：

- `AGENTS.md`：目前階段切回 M01-D；工程實作守則新增第 6 條「Supported locale 同步交付」，明文規定缺任一語言視同該 Subphase regression。
- `PROJECT_BRIEF.md`：M02-A～H 全部 ✅、M02 標記關門、下一個 coding step 改為 M01-D，Roadmap / 執行順序 / 接手原則 / 文件樹同步。
- `規格企劃.md`：〇 產品基線第 12 條由「介面以中文為主」改為「支援繁體中文與英文兩種語言」，只寫產品層行為，不寫 schema / API。
- `data/srd5.1/NOTICE.md`：新增 CC BY 4.0 繁中 translation / adaptation 聲明，明確標示 SRD 5.1 素材已被修改、譯文範圍限於 policy required 欄位加上 spell / feature / condition 描述，並明講**不是**整份 SRD 的完整翻譯。
- `docs/M02/M02-H_TODO.md`：標記已完成並指向本檔。
- M02 三份文件：preamble 加上 closeout 狀態與 evidence 索引。

---

## 已知未竟事項

- **Playwright 在預設 worker 數下仍會間歇性失敗。** 同一份 clean DB，`--workers=1` 為 37/37；預設平行度下曾出現 2 個 case 在「Confirm & Create Character 仍為 disabled」逾時。這是 M02-G closeout 已記錄的既有現象，根因是多 worker 對單一 backend process，不是 localization 缺陷。CI 應固定限制 worker 數。
- **Docker 全端組態未在本次驗證中執行**（本機目前沒有安裝 docker）。M02-D 已把 localization data 封進 server image，但 M02-H 沒有重新以 docker compose 驗一次。
- **非 SRD shard 的 `review_status` 仍為 `draft-human-review-required`**（`phb2014` / `scag` / `gos` 共 7 個 shard，自 M02-F 承接）。`srd5.1` 的術語 review 已由專案 owner 接受。
- **H.7 真人 browser gate 由專案 owner 認定已通過**，本檔未附獨立的人工巡覽紀錄。

## M02-H Definition of Done

- [x] server 送出語言中立的 `disabled_reason_code` / `disabled_reason_params` 與 issue `message_params`。
- [x] 前端以 `code + params` 格式化，不 regex-match server 英文。
- [x] 繁中 disabled 選項顯示具體原因。
- [x] 全站 `zh-TW` / `en` route crawl 與 overflow gate。
- [x] Draft 連續切換不增 revision、不改 payload 與 selected StableKeys。
- [x] Character live state 跨切換與 reload 不變。
- [x] 四個 enabled pack × 兩個 locale 的 required completeness = 0 issues。
- [x] translation batch evidence 彙整（H.9）。
- [x] P0 / P1 / M01-A～C regression 全綠。
- [x] `AGENTS.md` / `PROJECT_BRIEF.md` / `規格企劃.md` / `NOTICE.md` / M02 三份文件 doc-sync。
- [ ] docker compose 全端組態複驗（延後，非 localization blocker）。
- [ ] 非 SRD shard 的人工術語 review 正式接受。

## 下一步

```text
M01-D — VGM Race Expansion
```

M01-D 起，每個新增／修改／首次 expose user-visible system / rules content 的 Subphase 都必須同步交付 `zh-TW` / `en`；缺任一語言視為該 Subphase 未完成。
