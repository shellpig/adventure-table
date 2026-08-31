# M01-E Closeout Checklist

M01-E — SCAG Half-Elf Variant & Grant Replacement closeout scope：

- [x] 新增 generic `race-variant` StableKind、typed content schema、Builder selection 與 backward-safe `CharacterBuild.race_variant_ref`。
- [x] Moon Elf or Sun Elf、Wood Elf、Aquatic Elf、Drow 四種 Half-Elf descent 使用獨立 StableKey，並維持 `srd5.1:race:half-elf` base identity。
- [x] Variant Human 保持完整 Race identity，不 retro-fit 成 `race_variant_ref`。
- [x] 最小通用 Grant Replacement 以 stable grant identity 移除 Skill Versatility，inactive / stale branch 不進 Review 或 compiled Build。
- [x] Keep Skill Versatility branch 保留原本 exactly-two skill choice 與實際 skill effects。
- [x] Moon / Sun Wizard cantrip 從 runtime Wizard cantrip pool 產生，使用 INT casting ability。
- [x] Wood Fleet of Foot 產生 walking speed 35；Aquatic Swimming Speed 保留 walking 30 並新增 swim 30。
- [x] Character Sheet 以 typed `zh-TW` / `en` UI copy 呈現 walking / swim / climb / fly movement modes。
- [x] Drow Magic 依 Character Level 1 / 3 / 5 取得 Dancing Lights / Faerie Fire / Darkness，limited-use spells 使用獨立 live resources，不污染 normal class spell slots。
- [x] Draft save / reload、Create Version 1、Build Edit Wood → Aquatic、Version 2 與 Version History 走正式 API / repository / persistence round-trip。
- [x] `race-variant` name 納入 localization field policy；variant / feature names與 ancestry validation messages 同步 `zh-TW` / `en`。
- [x] Keep Skill Versatility、Wood Fleet of Foot、Moon / Sun cantrip、高等 Drow 四條 M01-E real-browser Create / Confirm / Sheet flow 通過。

## Verification evidence

2026-09-01 最終驗證：

```text
.\.venv\Scripts\python.exe -m pytest apps/server/tests
294 passed

cd apps/web
npm test -- --run
14 test files / 74 tests passed

npm run build
TypeScript / Vite build passed

npx playwright test e2e/m01e-half-elf-variants.spec.ts --workers=1
4 passed
```

Docker images、migration、PostgreSQL / FastAPI health 均通過。

完整本機 Playwright 在單 worker 下為 `44 passed / 1 failed`；唯一 failure 是使用者明確要求保留測試資料後，既有 P1-D fixed-name assertion 同時命中兩份 `P1-D Browser Hero` 草稿。M01-E 四條 spec 全綠，其他 44 條通過；使用者已於 2026-09-01 接受此 fixture-isolation 限制並決定關門。高並行本機 run 曾使 Vite dev server 中止，故關門證據採穩定的 single-worker run，不將該環境負載 failure 歸為產品回歸。

## Boundary

- M01-E 不建立任意 patch language，只交付本次內容需要的最小 Grant Replacement primitive。
- Drow Magic 不使用 normal class spell slots；正式 Rest workflow 仍留給後續對應 Phase。
- Aasimar / lineage transformation 不納入 M01-E；下一個 Subphase 由 M01-F 承接 VRGR Lineage & Dhampir。
- 本次 verifier 只更新關門文件與 SSOT；沒有修改產品碼、測試或 fixture，也沒有在 commit / push 階段重跑測試。

## Handoff

M01-E 已完成並關門。下一個可開工 Subphase：**M01-F — VRGR Lineage & Dhampir**。

M01-F 繼續遵守 M02 localization Definition of Done：新增、修改或首次 expose 的 user-visible system / rules content，必須在同一 Subphase 同步 `zh-TW` / `en`。
