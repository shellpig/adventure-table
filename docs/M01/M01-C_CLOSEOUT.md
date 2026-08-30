# M01-C Closeout Checklist

M01-C — SCAG / GoS Background Expansion closeout scope：

- [x] `scag` / `gos` production content packs enabled beside existing `srd5.1` / `phb2014` packs。
- [x] 13 個 supplied SCAG Background 全部 normalized 並使用 `scag:background:*` StableKey。
- [x] 4 個 supplied GoS Background 全部 normalized 並使用 `gos:background:*` StableKey。
- [x] 17 筆 Background mechanical matrix 全覆蓋 skill / tool / language / equipment / gold / feature identity。
- [x] SCAG roleplay-table reuse 僅繼承 roleplay suggestions，不繼承 PHB mechanics。
- [x] Background variant identity 與 stale branch isolation 有 focused regression。
- [x] 同名／近似 Background 的 source-aware selector 與 full StableKey Draft reload 有 regression。
- [x] GoS optional flavor tables 不影響 Build legality。
- [x] SCAG / GoS starting equipment 走既有 P1 equipment path，Create 初始化一次、reload 不 duplicate、Level Up 不重建 live Inventory。
- [x] SCAG Background + SRD Race/Class real-browser Create / Confirm / Sheet / reload 通過。
- [x] GoS Background + PHB Subrace + SRD Class real-browser Create / Confirm / Sheet / reload 通過，並額外通過 Level Up inventory preservation。
- [x] Full repository regression green：`P1 Full Regression` #573 (`33313151350`)；210 backend tests、14 Vitest tests、17 Playwright tests、migration / Docker / restart persistence 全部通過。

## Human Gate boundary

M01-C C.1～C.8 沒有定義新的 mandatory Human Gate，因此不把 Playwright 冒充真人驗收，也不自行新增未規定的 closeout 阻塞條件。M01-B 已完成的 mandatory first real-character-creation Human Gate 維持有效。

## Handoff

M01-C 完成後：

```text
M01-A ✅ → M01-B ✅ → M01-C ✅
                         ↓
                     暫停 M01
                         ↓
                 M02-A → ... → M02-H
                         ↓
                     回到 M01-D
```

下一個可開工 Subphase：**M02-A — Locale Foundation & Runtime Switch**。

在 M02 closeout 前：

- 不開始 M01-D。
- 不提前拆 P2～P8。
- 不把 locale 寫進 Character / Build / State domain。

本 checklist 在 closeout documentation / `PROJECT_BRIEF.md` handoff 的最新 PR head CI 再次全綠後才視為 merge-ready。