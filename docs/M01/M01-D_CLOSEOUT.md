# M01-D Closeout Checklist

M01-D — VGM Race Expansion closeout scope：

- [x] `vgm` production content pack 已啟用並封裝進 server image。
- [x] Goblin / Hobgoblin / Aasimar parent race 與 Protector / Scourge / Fallen Aasimar subrace 使用穩定的 VGM StableKey。
- [x] Goblin grants、Fury of the Small 與 Nimble Escape 已納入既有 Character Build / State 路徑。
- [x] Hobgoblin grants、Light Armor 與任選 2 種 Martial Weapons 的結構選擇已完成。
- [x] Aasimar 必須選擇且只能選擇一個合法 subrace；parent grants 不重複套用。
- [x] 三種 Aasimar transformation feature 依 Character Level 3 解鎖，Direct Create、Level Up 與 multiclass total-level gate 使用同一規則。
- [x] racial limited-use resource 使用 deterministic feature resource key，可初始化並在 Level Up reconciliation 中維持正確容量與已用量。
- [x] VGM user-visible content 同步提供 `zh-TW` / `en`，localization completeness 與 grant signature 有 focused regression。
- [x] Goblin Create / Confirm / Sheet / reload real-browser E2E 通過。
- [x] Hobgoblin + two martial weapon choices Create / Confirm / Sheet / reload real-browser E2E 通過。
- [x] Aasimar required subrace selection / Confirm / reload real-browser E2E 通過。
- [x] Aasimar Lv2→Lv3 Level Up 建立 immutable Build v2、解鎖 Radiant Soul 並於 reload 後保留的 real-browser E2E 通過。

## E2E evidence

2026-08-31 使用既有 PostgreSQL / FastAPI test stack，執行：

```text
cd apps/web
npm run test:e2e -- e2e/m01d-vgm-races.spec.ts
```

最終結果：`4 passed (14.4s)`。

首次執行因資料庫殘留兩張同名 `M01-D Threshold Hero`，Playwright strict locator 命中兩個按鈕而停止；透過正式 archive / delete API 只清除 8 筆名稱以 `M01-D ` 開頭的既有 E2E 測試角色後，同一 commit、同一 spec 無程式修改即全綠。此失敗歸類為測試資料隔離，不是產品功能 failure。

同步遠端最新 M01-D commits 後重驗時，舊 helper 曾要求畫面必須恰好停在 `previous revision + 1`，遇到 autosave 已前進兩版時產生假陰性。M01-D helper 已對齊既有 M02-H canonical 判準，等待 revision 大於動作前值；清除本 spec 建立的測試角色後，最終四條情境全部通過。

## Boundary

- M01-D 不執行 Bonus Action / Reaction timing、spatial ally count、fear target resolution 或 Rest auto-recovery。
- Aasimar subrace change 繼續使用既有 Build Edit / Correction 與 immutable Version，不新增 transformation subsystem。
- 本次關門只補 M01-D E2E 驗證、M01-D autosave revision wait helper 與文件同步；沒有重跑其他測試，也沒有修改產品碼。

## Handoff

M01-D 已完成並關門。下一個可開工 Subphase：**M01-E — SCAG Half-Elf Variant & Grant Replacement**。

M01-E 開工時繼續遵守 M02 localization Definition of Done：新增、修改或首次 expose 的 user-visible system / rules content，必須在同一 Subphase 同步 `zh-TW` / `en`。
