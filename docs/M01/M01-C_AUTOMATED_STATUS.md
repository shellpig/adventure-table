# M01-C Automated Status

M01-C — SCAG / GoS Background Expansion 的 mechanics、data、regression 與 real-browser automated coverage 已完成。

## Automated regression status

Closeout mechanics head：`c063cf7d1cea771ee09129a6612de58597cfa69d`

GitHub Actions evidence：

- Workflow：`P1 Full Regression`
- Run：`#573` (`33313151350`)
- Result：`success`
- Backend：`210 passed`，1 個 upstream/dependency deprecation warning。
- Alembic fresh-database validation：passed。
- P0 → P1 migration 與 legacy Character compatibility：passed。
- Frontend TypeScript / Vite build：passed。
- Vitest：5 files，14 tests passed。
- Docker Compose config / build / startup / readiness：passed；server image 包含 `srd5.1`、`phb2014`、`scag`、`gos` content packs。
- Playwright：17 tests passed。
- Closeout smoke screenshots：12 files uploaded by workflow artifact。
- Server restart persistence verification：passed。

## M01-C-specific automated evidence

- Dataset completeness：精確驗證 13 個 SCAG Background + 4 個 GoS Background、source identity、manifest / registry loading 與 full StableKey uniqueness。
- Mechanical matrix：17 筆 Background 全部逐筆 machine-check skill / tool choices、language choices、starting equipment shape / quantity、starting gold 與 Background Feature identity。
- SCAG roleplay inheritance isolation：PHB roleplay suggestions 可 reuse，但 SCAG mechanics / `background_ref` 不被 PHB target Background 污染。
- Source audit：Faction Agent / Inheritor 的 roleplay table reuse 與 Uthgardt Tribe Member 的 structured foraging metadata 有 focused regression。
- Variant / branch：Investigator 保存 `variant_of` identity；City Watch → Investigator switch 不保留 inactive stale branch grants。
- Source collision：Waterdhavian Noble 與 PHB Noble 同時存在，selector 保留 source label，Draft reload 後仍保存 `scag:background:waterdhavian-noble` full StableKey。
- GoS flavor tables：Fisher Tale / Marine Hardship 保持 optional roleplay data，不成為 legality / structural Builder choice。
- Equipment：GoS Fisher starting equipment deterministic；Create / reload 不 duplicate，Level Up 後仍只保留一份 live Inventory。
- E2E：SCAG Background + SRD Race/Class，以及 GoS Background + PHB Subrace + SRD Class 都完成 Confirm → Character Sheet → browser reload；GoS flow 另外完成 Level Up regression。

## Closeout boundary

`docs/M01/測試指南.md` 的 M01-C C.1～C.8 沒有新增 mandatory Human Gate；M01-B 的 mandatory first real-character-creation Human Gate 已在 M01-B closeout 完成，不在 M01-C 重複建立第二個 gate。

M01-C closeout 後依既定 Roadmap **暫停 M01，下一個可開工 Subphase 是 M02-A — Locale Foundation & Runtime Switch**。M02 未 closeout 前不得開始 M01-D。

本文件的 run #573 驗證的是 mechanics/test closeout head；closeout documentation / `PROJECT_BRIEF.md` handoff commit 仍須由最新 PR-head CI 再驗一次後才 merge。