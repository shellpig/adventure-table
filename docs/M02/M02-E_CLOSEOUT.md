# M02-E Closeout — SRD 5.1 User-Visible Descriptions

日期：2026-08-31  
分支：`m02-e-srd-descriptions`

## 結論

M02-E 已依 M02-C 的 **field-level product visibility policy** 完成 scope audit。

本 Subphase 的 required SRD long-form translation count 為：

```text
0
```

這不是把英文長文當成已翻譯，也不是以 fallback 掩蓋缺漏；原因是目前產品畫面沒有 render SRD spell / condition / magic-item / background-feature 的 canonical long description。

因此 M02-E 不建立「為未來可能使用」的整份 SRD 長文繁中庫，符合 M02 規格明確要求：只翻 M02 closeout 當下已 user-visible 的 field，未 expose 的 field 延後到首次 expose 它的 Subphase。

## Surface audit

目前既有產品 surface 的實際接線確認如下：

- Character Builder / Spellcasting：顯示 spell name、spell level、access model、slot/resource summary 與 frontend-owned helper copy；不 render `spell.data.desc.*`。
- Character Sheet / Spells：顯示 spell name、access / prepared state、resource state；不 render `spell.data.desc.*`。
- Character Sheet / Conditions：顯示 condition name 與使用者自行輸入的 note；不 render `condition.data.desc.*`。
- Character Sheet / Inventory：顯示 item/equipment name 與結構化 mechanics summary（equipment category、damage dice/type、AC、cost）；不 render `item.data.desc.*`。
- Background feature long description：目前 Review / Sheet 沒有 render `background.data.feature.desc`。

目前 policy 對應的 deferred long-form rules：

```text
background.data.feature.desc
item.data.desc.*
spell.data.desc.*
condition.data.desc.*
```

全部維持：

```text
localizable = true
currently_user_visible = false
required_locales = []
```

## 防止未來留下英文漏翻

新增 `apps/server/tests/test_m02e_description_scope.py`，鎖定以下行為：

1. 目前 SRD policy 不得存在未處理的 required long-form field。
2. 證明 canonical SRD 的 spell / condition / item 確實含大量英文長文；required count = 0 是產品 surface 決策，不是資料不存在。
3. deferred long-form field 不得被 completeness 誤判成 M02-E 缺翻譯。
4. 未來任何 Subphase 若把 long-form field 的 policy 改成 `currently_user_visible = true` / required，M02-E scope test 會立即失敗，迫使同一變更同步加入 `zh-TW` / `en` coverage，而不能把英文直接露到正式 UI。

## 為什麼沒有批量翻整份 SRD

M02 規格已明確禁止為尚不存在的 UI surface 提前翻譯完整 SRD 長文庫。

例如 `items.json`、spells、conditions 中雖有大量 canonical English description，但目前 UI 不顯示它們。現在先翻會造成：

- 大量無產品用途的 translation debt / review debt。
- 未來真正做 detail UI 時可能因 presentation contract 改變而重做。
- 違反 M02-C field-level visibility policy 的 SSOT 原則。

因此本 closeout 不宣稱「整份 SRD 5.1 已完整繁中化」；只宣稱：

> M02-E 當下 **所有目前 user-visible 的 SRD long-form description fields 已完整處理，而其 required 集合為空**。

## English leakage 判定

使用者要求「不要像未審核機翻一樣留下大量英文」。M02-E 採更嚴格的邊界：

- required / user-visible long-form：不得缺繁中；未來一旦出現即由 completeness + scope regression 阻擋。
- deferred / non-visible canonical long-form：可以維持 SRD 原始英文，因為不會出現在目前產品畫面。
- 不把 deferred English 誤算成已完成的 zh-TW translation。

## M02-E Definition of Done

- [x] 依 M02-C policy 枚舉 SRD long-form scope。
- [x] Audit 現有 Builder / Character Sheet surface。
- [x] 確認目前 required long-form field count = 0。
- [x] 確認 canonical SRD 確實存在 deferred English long text，沒有把「資料不存在」當完成。
- [x] 新增 regression test 鎖定 policy / completeness boundary。
- [x] 不提前翻譯沒有 product surface 的 spell / item / condition / background feature 長文。
- [x] 不修改 StableKey、mechanics、Draft、CharacterBuild 或 CharacterState。

## 下一步

M02-E branch scope 完成後，下一個正式 Subphase 為：

```text
M02-F — PHB / SCAG / GoS Localization
```

M02-F 仍必須依同一份 `data/localization/localizable-fields.json` policy 處理 non-SRD current-surface presentation；不得因 E 的零 long-form scope 而放寬 non-SRD 翻譯要求。
